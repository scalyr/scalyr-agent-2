<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# SNMP Monitor
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

## Configuration Reference

|||# Option                   ||| Usage
|||# ``module``               ||| Always ``scalyr_agent.builtin_monitors.snmp_monitor``
|||# ``error_repeat_interval``||| Optional (defaults to 300). The number of seconds to wait before repeating an error \
                                  message.
|||# ``mib_path``             ||| Optional (defaults to None).  An absolute path to a location on disk that contains \
                                  ASN1 MIB files
|||# ``oid_groups``           ||| A JSON object that maps custom names to a list of OIDs/variables defined as strings \
                                  such "group1" : ["IF-MIB::ifDescr",  "1.3.6.1.2.1.2.2.1.16.1"].
|||# ``poll_targets``         ||| A JSON array contain a list of target devices to poll.  Each element of the array is \
                                  a JSON object that containsa list of target devices, and a list of "oid_groups" to \
                                  query.  Each "target device" in the list is a JSON object containingvariables that \
                                  define the target (host, port, authentication details) and each "oid_group" is a \
                                  string key from thepreviously defined "oid_groups" configuration option.

## Log reference

Each event recorded by this plugin will have the following fields:

|||# Field          ||| Meaning
|||# ``monitor``    ||| Always ``snmp_monitor``.
|||# ``poll_target``||| The device that was queried to retrieve this value, e.g. ``demo.snpmlabs.com``
|||# ``oid``        ||| The OID for the retrieved value, e.g. ``IF-MIB::ifDescr."1"``
|||# ``value``      ||| The value reported by the device.
