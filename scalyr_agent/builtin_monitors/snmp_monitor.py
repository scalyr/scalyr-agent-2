# Copyright 2016 Scalyr Inc.

import re

from scalyr_agent import ScalyrMonitor, define_config_option, define_log_field
from scalyr_agent.json_lib import JsonObject

import pysnmp
from pysnmp.hlapi import CommunityData, ObjectIdentity, ObjectType, SnmpEngine, UdpTransportTarget, UsmUserData
from pysnmp import hlapi

from pysnmp.smi.error import MibNotFoundError

__monitor__ = __name__

define_config_option(__monitor__, 'module',
                     'Always ``scalyr_agent.builtin_monitors.snmp_monitor``',
                     convert_to=str, required_option=True)

define_config_option(__monitor__, 'error_repeat_interval',
                     'Optional (defaults to 300). The number of seconds to wait before repeating an error message.',
                     default=300, convert_to=int)

define_config_option(__monitor__, 'mib_path',
                     'Optional (defaults to None).  An absolute path to a location on disk that contains ASN1 MIB files',
                     default=None, convert_to=str)

define_config_option( __monitor__, 'oid_groups',
                     'A JSON object that maps custom names to a list of OIDs/variables defined as strings such "group1" : ["IF-MIB::ifDescr",  "1.3.6.1.2.1.2.2.1.16.1"].',
                     default=None )

define_config_option( __monitor__, 'poll_targets',
                     'A JSON array contain a list of target devices to poll.  Each element of the array is a JSON object that contains'
                     'a list of target devices, and a list of "oid_groups" to query.  Each "target device" in the list is a JSON object containing'
                     'variables that define the target (host, port, authentication details) and each "oid_group" is a string key from the'
                     'previously defined "oid_groups" configuration option.',
                     default=None )

define_log_field(__monitor__, 'monitor', 'Always ``snmp_monitor``.')
define_log_field(__monitor__, 'poll_target', 'The device that was queried to retrieve this value, e.g. ``demo.snpmlabs.com``')
define_log_field(__monitor__, 'oid', 'The OID for the retrieved value, e.g. ``IF-MIB::ifDescr."1"``')
define_log_field(__monitor__, 'value', 'The value reported by the device.')


class SNMPMonitor( ScalyrMonitor ):
    """
    The SNMP Monitor polls SNMP-enabled devices on the network to collect values specified in the configuration
    file.

    You can configure the monitor to collect values from one or more devices.  Each of these devices can be
    configured to retrieve a different set of values, if desired.

    Values can be retrieved using either OIDs or by variable names if you have installed an appropriate
    MIBs file.

    By default, no MIBs files are provided with the Scalyr Agent.  Users are expected to provide any MIBs they
    are interested in.  There is documentation below describing how to configure the this monitor to use any installed
    MIBs files.

    A sample/test configuration is provided below, followed by an explanation of the critical fields.

    {
        module: "scalyr_agent.builtin_monitors.snmp_monitor",
        mib_path: "/usr/share/mibs/",
        oid_groups: {
            "group1" : [ "IF-MIB::ifInOctets", "1.3.6.1.2.1.2.2.1.16.1" ],
            "group2" : [ "IF-MIB::ifDescr" ]
        }

        poll_targets: [
            {
                "targets": [ { "host": "demo.snmplabs.com" }, { "host": "demo.snmplabs.com", "port": 1161 } ],
                "oids" : [ "group1", "group2" ]
            },
            {
                "targets": [
                    {
                      "host": "demo.snmplabs.com",
                      "port": 3161,
                    },
                ],
                "oids" : [ "group2" ]
            }
        ]

    }

    Field descriptions:

    mib_path - the full path on disk for any MIB files.  In this example, it is assumed that /usr/share/mibs will
               contain MIB files describing IF-MIB and its related MIBS.

    oid_groups - a JSON object mapping a name to a list of OIDs/variables, e.g.
        "oid_groups" : {
            "group1" : [ "IF-MIB::ifInOctets", "1.3.6.1.2.1.2.2.1.16.1" ],
            "group2" : [ "IF-MIB::ifDescr" ]
        }

        Each list can contain a mix of OIDs or MIB variable names.  This grouping allows users
        to specify common groups of values that can be queried across multiple hosts (see below
        more detail)

    poll_targets - a JSON array containing a list of target devices to poll.  Each poll_target
    in the array is a JSON object with a list of target devices (host, port, authentication) as
    well as a list of OID groups to query. e.g.

        "poll_targets": [
            //first set of targets
            {
                //a list of target devices to poll
                "targets": [ { "host": "demo.snmplabs.com" }, { "host": "demo.snmplabs.com", "port": 1161 } ],

                //oid groups to query for the above targets
                "oids" : [ "group1", "group2" ]
            },
            //second set of targets
            {
                //a list of target devices to poll
                "targets": [
                    {
                      "host": "demo.snmplabs.com",
                      "port": 3161,
                    },
                ],
                //oid groups to query for the above targets
                "oids" : [ "group2" ]
            }
        ]

        With the above example, the SNMP module will query 3 devices on the network.  demo.snmplabs.com on the
        default port of 161, demo.snmplabs.com on port 1161, and demo.snmplabs.com with the port 3161.  The two
        devices from the first set of targets will be queried for OIDs in 'oid_groups' "group1" and "group2",
        whereas the devices specified in the second set of targets will only be queried for OIDs in "group2".

        In addition to the 'host' and 'port', each target can have the following fields defined:

            {
                "host": "mydevice.example.com", //domain or IP address of device to query
                "port": 161, //port to connect to, defaults to 161
                "version": "SNMPv2", //version string to use a specific version of the SNMP
                                     //protocol.  Valid values are SNMPv1, SNMPv2, SNMPv3, with
                                     //SNMPv2 as the default, unless the 'user' field is specified
                                     //and then SNMPv3 is the default.
                "timeout": 1, //the connection timeout in seconds, defaults to 1
                "retries": 3, //the number of times to retry the connection, defaults to 3
                "user" : {
                    //user authentication details - see below for more information.
                    //Note, if 'user' is specified, version must be SNMPv3
                }
            }

        If the 'user' field is specified, it is a JSON object with the following fields:

            "user" : {
                "username": "myuser", //the username to authenticate as, defaults to ''
                "auth_key": "authkey", //the authentication key/password, defaults to ''
                "auth_protocol": "None", //the hash protocol for the authentication key.
                                         //Valid values are 'None', 'MD5' and 'SHA'.  Defaults
                                         //to 'None' if auth_key is empty, or 'MD5' if auth_key
                                         //is specified.
                "priv_key": "privkey", //the private key to use if the auth_key needs to be encrypted,
                                       //defaults to ''.
                "priv_protocol": "None" //The encryption protocol to use, valid values are:
                                        // 'None', 'DES', '3DES', 'AES128', 'AES192', 'AES256'
                                        //Defaults to 'None' if 'priv_key' is empty, otherwise defaults
                                        //to 'DES'.  Note: In order to use encryption, the python
                                        //crypto module PyCrypto needs to be installed.  This is not
                                        //included with the scalyr-agent as it uses native code.

            }

    """
    def _initialize( self ):

        #get the mib path
        self.__mib_path = self._config.get( 'mib_path' )
        if self.__mib_path:
            self.__mib_path = 'file://' + self.__mib_path

        #build a list of oid groups
        oid_groups = self._config.get( 'oid_groups' )
        groups = self.__build_oid_groups( oid_groups, self.__mib_path )

        #build a list of poll targets
        poll_targets = self._config.get( 'poll_targets' )
        self.__poll_targets = self.__build_poll_targets( poll_targets, groups )

        #other config options
        self.__error_repeat_interval = self._config.get( 'error_repeat_interval' )

        # for legacy
        self.__use_legacy_format = self._config.get('use_legacy_format', default=False, convert_to=bool)

    def __build_poll_targets( self, poll_targets, groups ):
        result = []
        if not poll_targets:
            return result

        for poll_target in poll_targets:
            #each poll target needs a 'targets' and a 'oids' list.
            if 'targets' not in poll_target:
                raise Exception( "Configuration Error, poll_target does not contain a \"targets\" list." )

            if 'oids' not in poll_target:
                raise Exception( "Configuration Error, poll_target does not contain an \"oids\" list." )

            targets = []
            #build a list of PySNMP TransportTargets
            for target in poll_target['targets']:

                #each target needs to have a host
                if 'host' not in target:
                    raise Exception( "Configuration Error, each target must specify a \"host\"" )

                name = target['host']

                #get the port, and create the targets name (a combination of the host:port).
                port = 161
                if 'port' in target:
                    port = target['port']
                    name += ":%d" % port

                #load timeout and retry values
                timeout = target.get( 'timeout', 1 )
                retries = target.get( 'retries', 3 )

                #create the transport
                transport = UdpTransportTarget( (target['host'], port), timeout=timeout, retries=retries )

                #get the version - default to v2, unless the 'user' field is specified, then default
                #to v3
                version = 'snmpv2'
                if 'user' in target:
                    version = 'snmpv3'

                if 'version' in target:
                    version = target['version'].lower()

                #Sanity check - if 'user' is provided, version must be 'snmpv3'
                if 'user' in target and version != 'snmpv3':
                    raise Exception( "Configuration Error, user authentication is only supported for SNMPv3" )

                #depedning on the version, create the appropriate authentication object
                auth = None
                if version == 'snmpv1':
                    auth = CommunityData( 'public', mpModel=0 )
                elif version == 'snmpv3':
                    auth = self.__build_snmpv3_user( target )
                else:
                    auth = CommunityData( 'public' )

                #add the transport, auth and name to the list of targets
                targets.append( { "transport" : transport, "auth": auth, "name": name } )

            #build a list of oids for the targets
            oids = []
            for oid in poll_target['oids']:
                #the oid groups need to be in the previous list of oids
                if oid not in groups:
                    raise Exception( "Configuration Error, '%s' is not a valid oid group" % str( oid ) )
                oids += groups[oid]

            if not oids:
                raise Exception( "Configuration Error, no oid groups specified for poll_target" )

            #add our target list and oid list to the list of poll_targets
            result.append( { "targets" : targets, "oids" : [oids] } )

        return result

    def __build_snmpv3_user( self, target ):
        """
        Build a UsmUserData object, based on the 'user' field of the 'target'.  Target should be a
        JSON Object.
        """
        #default object is blank
        user = {}

        if 'user' in target:
            user = target['user']

        #get username
        name = user.get( 'username', '' )

        #get the authentication key
        auth_key = None
        if 'auth_key' in user:
            auth_key = user['auth_key']

        #get the auth_protocol and map it to the appropriate constant
        auth_protocol = None
        if 'auth_protocol' in user:
            protocol = user['auth_protocol'].lower()
            if protocol == 'none':
                auth_protocol = hlapi.usmNoAuthProtocol
            elif protocol == 'md5':
                auth_protocol = hlapi.usmHMACMD5AuthProtocol
            elif protocol == 'sha':
                auth_protocol = hlapi.usmHMACSHAAuthProtocol
            else:
                raise Exception( "Configuration Error, invalid Authentication Protocol.  Valid values are 'None', 'MD5' and 'SHA'" )


        #get the priv_key
        priv_key = None
        if 'priv_key' in user:
            priv_key = user['priv_key']

        #get the priv_protocol and map it to the appropriate constant
        priv_protocol = hlapi.usmNoPrivProtocol
        if 'priv_protocol' in user:
            protocol = user['priv_protocol'].lower()
            if protocol == 'none':
                priv_protocol = hlapi.usmNoPrivProtocol
            elif protocol == 'des':
                priv_protocol = hlapi.usmDESPrivProtocol
            elif protocol == 'aes128':
                priv_protocol = hlapi.usmAesCfb128PrivProtocol
            elif protocol == 'aes192':
                priv_protocol = hlapi.usmAesCfb192PrivProtocol
            elif protocol == 'aes256':
                priv_protocol = hlapi.usmAesCfb256PrivProtocol
            elif protocol == '3des':
                priv_protocol = hlapi.usm3DESEDEPrivProtocol
            else:
                raise Exception( "Configuration Error, invalid Encryption Protocol.  Valid values are 'None', 'DES', 'AES128, 'AES192', 'AES256' and '3DES'" )

        #create the object
        return UsmUserData( name, authKey=auth_key, privKey=priv_key, authProtocol=auth_protocol, privProtocol=priv_protocol )


    def __build_oid_groups( self, oid_groups, path ):
        """
        Build a list of ObjectType( ObjectIdentifier() ) for all the oids specified in 'oid_groups'.
        'oid_groups' is a dict of key -> lists, and each element of the list is a string with an OID/variable name
        'path' is a path on the filesystem that contains MIB definitions.
        """

        groups = {}

        if not oid_groups:
            return groups

        # regex to match MIB::variable
        mib_re = re.compile( '^([^:]+)::(.+)$' )

        # for each item in oid_groups
        for group, oids in oid_groups.iteritems():
            objects = []
            # get the list of oids
            for oid in oids:
                # check to see if it's an oid or a variable name
                match = mib_re.match( oid )
                if match:
                    # it's a variable name, so make sure to add the MIB path to the
                    # ObjectIdentity
                    identity = ObjectIdentity( match.group( 1 ), match.group( 2 ), 1 )
                    if path:
                        identity = identity.addAsn1MibSource( path )

                    objects.append( ObjectType( identity ) )
                else:
                    #just a regular oid
                    objects.append( ObjectType( ObjectIdentity( oid ) ) )

            #if we have values, add to the result
            if objects:
                groups[group] = objects

        return groups

    def __process_command( self, engine, name, auth, transport, queue ):
        """
        Queries a SnmpEngine for all OIDS in the queue, using the specified
        authentication and transport objects.
        Name is the host:port of the device being queried
        """

        #create a new 'get' command, and step to the 'next' element to prepare
        #the command for sending queries
        cmd = pysnmp.hlapi.getCmd( engine, auth, transport, pysnmp.hlapi.ContextData() )
        next( cmd )

        # for each object in the queue
        for obj in queue:
            try:
                # send the query
                errorIndication, errorStatus, errorIndex, varBinds = cmd.send( obj )

                if errorIndication:
                    #error
                    self._logger.error( errorIndication )
                elif errorStatus:
                    #error
                    self._logger.error( '%s at %s' % (
                            errorStatus.prettyPrint(),
                            errorIndex and varBinds[int(errorIndex)-1][0] or '?'
                        )
                    )
                else:
                    #success, emit the value to the log
                    for oid, value in varBinds:
                        if self.__use_legacy_format:
                            extra = { "oid" : oid.prettyPrint(), "value": value.prettyPrint() }
                            self._logger.emit_value( 'poll-target', name, extra )
                        else:
                            extra = { "oid" : oid.prettyPrint(), "poll_target": name }
                            self._logger.emit_value( oid.prettyPrint(), value.prettyPrint(), extra )

            except MibNotFoundError, e:
                self._logger.error( 'Unable to locate MIBs: \'%s\'.  Please check that mib_path has been correctly configured in your agent.json file and that the path contains valid MIBs for all the variables and/or devices you are trying to query.' % str( e ), limit_once_per_x_secs=self.__error_repeat_interval, limit_key='invalid mibs')
            except Exception, e:
                self._logger.error( 'An unexpected error occurred: %s.  If you are querying MIBs, please make sure that mib_path has been set and that the path contains valid MIBs for all the variables and/or devices you are trying to query.' % str( e ), limit_once_per_x_secs=self.__error_repeat_interval, limit_key='invalid mibs')

    def run( self ):
        #create the SnmpEngine
        self.__snmpEngine = SnmpEngine()
        ScalyrMonitor.run( self )

    def gather_sample( self ):

        #for all poll_targets
        for poll_target in self.__poll_targets:
            #get the list of oids to query
            oids = poll_target['oids']
            #for each target in the poll_target's 'targets'
            for target in poll_target['targets']:
                #query the target for the specified oids
                self.__process_command( self.__snmpEngine, target['name'], target['auth'], target['transport'], oids )

    def stop(self, wait_on_join=True, join_timeout=5):

        #stop the main server
        ScalyrMonitor.stop( self, wait_on_join=wait_on_join, join_timeout=join_timeout )

