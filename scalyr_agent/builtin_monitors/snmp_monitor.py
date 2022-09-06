# Copyright 2016 Scalyr Inc.

from __future__ import unicode_literals
from __future__ import absolute_import

import re

import six
from pysnmp import hlapi  # pylint: disable=import-error
from pysnmp.smi.error import MibNotFoundError  # pylint: disable=import-error

import pysnmp  # pylint: disable=import-error
from pysnmp.hlapi import (  # pylint: disable=import-error
    CommunityData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
)

from scalyr_agent import ScalyrMonitor, define_config_option, define_log_field

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.snmp_monitor`",
    convert_to=six.text_type,
    required_option=True,
)
define_config_option(
    __monitor__,
    "mib_path",
    "Optional (defaults to `none`). An absolute path to ASN1 MIB files",
    default=None,
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "oid_groups",
    'A `{...}` JSON object, mapping a "group" (key name) to a `[...]` list of MIBs and OIDs. '
    "Lets you import device values from multiple devices. For example, `oid_groups: "
    '{ "group1" : [ "IF-MIB::ifInOctets", "1.3.6.1.2.1.2.2.1.16.1" ] }`.',
    default=None,
)
define_config_option(
    __monitor__,
    "poll_targets",
    "See Steps **3** and **4**. An array of `{...}` target objects, each with a `targets` and "
    "`oids` property. `targets` is an array of objects. Each object sets the "
    "`host` and `port` for the device. `port` defaults to `161` if not set. `oids` is a list "
    'of "groups" set in Step **2**. For example, `poll_targets: [ { "targets": [ { "host": '
    '"demo.snmplabs.com" }, { "host": "demo.snmplabs.com", "port": 1161 } ], "oids" : '
    '[ "group1", "group2" ] } ]`. You can also add the `user`, `version`, `timeout`, '
    "and `retries` properties.",
    default=None,
)
define_config_option(
    __monitor__,
    "error_repeat_interval",
    "Optional (defaults to 300). Seconds to wait before repeating an error message.",
    default=300,
    convert_to=int,
)


define_log_field(__monitor__, "monitor", "Always `snmp_monitor`.")
define_log_field(
    __monitor__,
    "poll_target",
    "The device that was queried to retrieve this value, for example `demo.snpmlabs.com`.",
)
define_log_field(
    __monitor__,
    "oid",
    'The OID for the retrieved value, for example `IF-MIB::ifDescr."1"`.',
)
define_log_field(__monitor__, "value", "The value reported by the device.")


class SNMPMonitor(ScalyrMonitor):  # pylint: disable=monitor-not-included-for-win32
    # fmt: off
    r"""
# SNMP

Import values from one or more SNMP-enabled devices.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can use Object Identifiers (OIDs) or Management Information Base (MIB) variable names to get device values. You must provide the MIB files.


## Installation

1\. Install the Scalyr Agent

The [Scalyr Agent](https://app.scalyr.com/help/welcome) must be installed on a host to import device values. We recommend you install the Agent on each server you want to monitor. Your data will automatically be tagged for the server it came from, and the Agent can also collect system metrics and log files.


2\. Set OID objects and MIB variables, and assign them to groups

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for SNMP. An example configuration:

    {
      module: "scalyr_agent.builtin_monitors.snmp_monitor",
      mib_path: "/usr/share/mibs/",
      oid_groups: {
        "group1" : [ "IF-MIB::ifInOctets", "1.3.6.1.2.1.2.2.1.16.1" ],
        "group2" : [ "IF-MIB::ifDescr" ]
      }
    }

For MIB variables, add and set the `mib_path`, and `oid_groups` properties. For OIDs, add and set the `oid_groups` property.

`mib_path` sets the path to the MIB files. In the above example, `/usr/share/mibs` has MIB files describing IF-MIB, and its related MIBs.

`oid_groups` maps a list of OIDs and MIB variables to a "group" (key name). This lets you import a set of values from multiple devices in the next step. In the above example, "group1" imports the `IF-MIB::ifInOctets` value, and the `1.3.6.1.2.1.2.2.1.16.1` value. The `IF-MIB::ifDescr` value is imported by "group2".


3\. Set target devices

Add a `poll_targets: [...]` array to map "groups" to target devices

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

Each `{...}` target object, has a `targets` and `oids` property. `targets` is an array of target `{...}` objects. Each sets the `host` and `port` for the device. If not set, `port` defaults to `161`.

The `oids` property is a list of "groups" (key names) from Step 2. Device values for each "group" will be imported from each target. In the above example, two targets are set. The first imports "group1" and "group2" device values from `demo.snmplabs.com`, on the default port of `161`, and `demo.snmplabs.com`, on port `1161`. The second imports "group2" values from `demo.snmplabs.com`, on port `3161`.


4\. Set user authentication, and other properties for target devices

Each `targets` object can have the properties:

    {
        "host": "mydevice.example.com", // Domain or IP address of the device to query.
        "port": 161,                    // The port to connect to. Defaults to 161.
        "version": "SNMPv2",            // Version of the SNMP protocol.  Valid values are SNMPv1,
                                        // SNMPv2, and SNMPv3. Defaults to SNMPv2. If the
                                        // 'user' field is set, the default is SNMPv3.
        "timeout": 1,                   // Connection timeout in seconds. Defaults to 1.
        "retries": 3,                   // Number of times to retry the connection. Defaults to 3.
        "user" : {                      // User object for authentication, if required.
                                        // See below for more information. If 'user'
                                        // is set, "version" must be SNMPv3.
        }
    }

If authentication is required, add and set the `"user": {...}` property:

    "user" : {
        "username": "myuser",    // Username for authentication. Defaults to ''
        "auth_key": "authkey",   // Key/password for authentication. Defaults to ''
        "auth_protocol": "None", // Hash protocol for the authentication key.
                                 // Valid values are 'None', 'MD5' and 'SHA'.  Defaults
                                 // to 'None' if auth_key is empty, or 'MD5' if auth_key
                                 // is set.
        "priv_key": "privkey",   // Private key to use if the auth_key is encrypted.
                                 // Defaults to ''.
        "priv_protocol": "None"  // The encryption protocol to use, valid values are:
                                 // 'None', 'DES', '3DES', 'AES128', 'AES192', and 'AES256'.
                                 // Defaults to 'None' if 'priv_key' is empty, otherwise defaults
                                 // to 'DES'. The python module PyCrypto must
                                 // be installed for encryption, and is not
                                 // included with the Scalyr Agent.
    }


5\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Agent to send device values.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr. From Search view query [monitor = 'snmp_monitor'](/events?filter=monitor+%3D+%27snmp_monitor%27). This will show all data collected by this plugin, across all servers. See the [Event Reference](#events) below for a description of all fields in the UI generated by this plugin.

For help, contact Support.

    """
    # fmt: on

    def _initialize(self):

        # get the mib path
        self.__mib_path = self._config.get("mib_path")
        if self.__mib_path:
            self.__mib_path = "file://" + self.__mib_path

        # build a list of oid groups
        oid_groups = self._config.get("oid_groups")
        groups = self.__build_oid_groups(oid_groups, self.__mib_path)

        # build a list of poll targets
        poll_targets = self._config.get("poll_targets")
        self.__poll_targets = self.__build_poll_targets(poll_targets, groups)

        # other config options
        self.__error_repeat_interval = self._config.get("error_repeat_interval")

        # for legacy
        self.__use_legacy_format = self._config.get(
            "use_legacy_format", default=False, convert_to=bool
        )

    def __build_poll_targets(self, poll_targets, groups):
        result = []
        if not poll_targets:
            return result

        for poll_target in poll_targets:
            # each poll target needs a 'targets' and a 'oids' list.
            if "targets" not in poll_target:
                raise Exception(
                    'Configuration Error, poll_target does not contain a "targets" list.'
                )

            if "oids" not in poll_target:
                raise Exception(
                    'Configuration Error, poll_target does not contain an "oids" list.'
                )

            targets = []
            # build a list of PySNMP TransportTargets
            for target in poll_target["targets"]:

                # each target needs to have a host
                if "host" not in target:
                    raise Exception(
                        'Configuration Error, each target must specify a "host"'
                    )

                name = target["host"]

                # get the port, and create the targets name (a combination of the host:port).
                port = 161
                if "port" in target:
                    port = target["port"]
                    name += ":%d" % port

                # load timeout and retry values
                timeout = target.get("timeout", 1)
                retries = target.get("retries", 3)

                # create the transport
                transport = UdpTransportTarget(
                    (target["host"], port), timeout=timeout, retries=retries
                )

                # get the version - default to v2, unless the 'user' field is specified, then default
                # to v3
                version = "snmpv2"
                if "user" in target:
                    version = "snmpv3"

                if "version" in target:
                    version = target["version"].lower()

                # Sanity check - if 'user' is provided, version must be 'snmpv3'
                if "user" in target and version != "snmpv3":
                    raise Exception(
                        "Configuration Error, user authentication is only supported for SNMPv3"
                    )

                # depedning on the version, create the appropriate authentication object
                auth = None
                if version == "snmpv1":
                    auth = CommunityData("public", mpModel=0)
                elif version == "snmpv3":
                    auth = self.__build_snmpv3_user(target)
                else:
                    auth = CommunityData("public")

                # add the transport, auth and name to the list of targets
                targets.append({"transport": transport, "auth": auth, "name": name})

            # build a list of oids for the targets
            oids = []
            for oid in poll_target["oids"]:
                # the oid groups need to be in the previous list of oids
                if oid not in groups:
                    raise Exception(
                        "Configuration Error, '%s' is not a valid oid group"
                        % six.text_type(oid)
                    )
                oids += groups[oid]

            if not oids:
                raise Exception(
                    "Configuration Error, no oid groups specified for poll_target"
                )

            # add our target list and oid list to the list of poll_targets
            result.append({"targets": targets, "oids": [oids]})

        return result

    def __build_snmpv3_user(self, target):
        """
        Build a UsmUserData object, based on the 'user' field of the 'target'.  Target should be a
        JSON Object.
        """
        # default object is blank
        user = {}

        if "user" in target:
            user = target["user"]

        # get username
        name = user.get("username", "")

        # get the authentication key
        auth_key = None
        if "auth_key" in user:
            auth_key = user["auth_key"]

        # get the auth_protocol and map it to the appropriate constant
        auth_protocol = None
        if "auth_protocol" in user:
            protocol = user["auth_protocol"].lower()
            if protocol == "none":
                auth_protocol = hlapi.usmNoAuthProtocol
            elif protocol == "md5":
                auth_protocol = hlapi.usmHMACMD5AuthProtocol
            elif protocol == "sha":
                auth_protocol = hlapi.usmHMACSHAAuthProtocol
            else:
                raise Exception(
                    "Configuration Error, invalid Authentication Protocol.  Valid values are 'None', 'MD5' and 'SHA'"
                )

        # get the priv_key
        priv_key = None
        if "priv_key" in user:
            priv_key = user["priv_key"]

        # get the priv_protocol and map it to the appropriate constant
        priv_protocol = hlapi.usmNoPrivProtocol
        if "priv_protocol" in user:
            protocol = user["priv_protocol"].lower()
            if protocol == "none":
                priv_protocol = hlapi.usmNoPrivProtocol
            elif protocol == "des":
                priv_protocol = hlapi.usmDESPrivProtocol
            elif protocol == "aes128":
                priv_protocol = (
                    hlapi.usmAesCfb128PrivProtocol  # pylint: disable=no-member
                )
            elif protocol == "aes192":
                priv_protocol = (
                    hlapi.usmAesCfb192PrivProtocol  # pylint: disable=no-member
                )
            elif protocol == "aes256":
                priv_protocol = (
                    hlapi.usmAesCfb256PrivProtocol  # pylint: disable=no-member
                )
            elif protocol == "3des":
                priv_protocol = hlapi.usm3DESEDEPrivProtocol
            else:
                raise Exception(
                    "Configuration Error, invalid Encryption Protocol.  Valid values are 'None', 'DES', 'AES128, 'AES192', 'AES256' and '3DES'"
                )

        # create the object
        return UsmUserData(
            name,
            authKey=auth_key,
            privKey=priv_key,
            authProtocol=auth_protocol,
            privProtocol=priv_protocol,
        )

    def __build_oid_groups(self, oid_groups, path):
        """
        Build a list of ObjectType( ObjectIdentifier() ) for all the oids specified in 'oid_groups'.
        'oid_groups' is a dict of key -> lists, and each element of the list is a string with an OID/variable name
        'path' is a path on the filesystem that contains MIB definitions.
        """

        groups = {}

        if not oid_groups:
            return groups

        # regex to match MIB::variable
        mib_re = re.compile("^([^:]+)::(.+)$")

        # for each item in oid_groups
        for group, oids in six.iteritems(oid_groups):
            objects = []
            # get the list of oids
            for oid in oids:
                # check to see if it's an oid or a variable name
                match = mib_re.match(oid)
                if match:
                    # it's a variable name, so make sure to add the MIB path to the
                    # ObjectIdentity
                    identity = ObjectIdentity(match.group(1), match.group(2), 1)
                    if path:
                        identity = identity.addAsn1MibSource(path)

                    objects.append(ObjectType(identity))
                else:
                    # just a regular oid
                    objects.append(ObjectType(ObjectIdentity(oid)))

            # if we have values, add to the result
            if objects:
                groups[group] = objects

        return groups

    def __process_command(self, engine, name, auth, transport, queue):
        """
        Queries a SnmpEngine for all OIDS in the queue, using the specified
        authentication and transport objects.
        Name is the host:port of the device being queried
        """

        # create a new 'get' command, and step to the 'next' element to prepare
        # the command for sending queries
        cmd = pysnmp.hlapi.getCmd(engine, auth, transport, pysnmp.hlapi.ContextData())
        next(cmd)

        # for each object in the queue
        for obj in queue:
            try:
                # send the query
                errorIndication, errorStatus, errorIndex, varBinds = cmd.send(obj)

                if errorIndication:
                    # error
                    self._logger.error(errorIndication)
                elif errorStatus:
                    # error
                    self._logger.error(
                        "%s at %s"
                        % (
                            errorStatus.prettyPrint(),
                            errorIndex and varBinds[int(errorIndex) - 1][0] or "?",
                        )
                    )
                else:
                    # success, emit the value to the log
                    for oid, value in varBinds:
                        if self.__use_legacy_format:
                            extra = {
                                "oid": oid.prettyPrint(),
                                "value": value.prettyPrint(),
                            }
                            self._logger.emit_value("poll-target", name, extra)
                        else:
                            extra = {"oid": oid.prettyPrint(), "poll_target": name}
                            self._logger.emit_value(
                                oid.prettyPrint(), value.prettyPrint(), extra
                            )

            except MibNotFoundError as e:
                self._logger.error(
                    "Unable to locate MIBs: '%s'.  Please check that mib_path has been correctly configured in your agent.json file and that the path contains valid MIBs for all the variables and/or devices you are trying to query."
                    % six.text_type(e),
                    limit_once_per_x_secs=self.__error_repeat_interval,
                    limit_key="invalid mibs",
                )
            except Exception as e:
                self._logger.error(
                    "An unexpected error occurred: %s.  If you are querying MIBs, please make sure that mib_path has been set and that the path contains valid MIBs for all the variables and/or devices you are trying to query."
                    % six.text_type(e),
                    limit_once_per_x_secs=self.__error_repeat_interval,
                    limit_key="invalid mibs",
                )

    def run(self):
        # create the SnmpEngine
        self.__snmpEngine = SnmpEngine()
        ScalyrMonitor.run(self)

    def gather_sample(self):

        # for all poll_targets
        for poll_target in self.__poll_targets:
            # get the list of oids to query
            oids = poll_target["oids"]
            # for each target in the poll_target's 'targets'
            for target in poll_target["targets"]:
                # query the target for the specified oids
                self.__process_command(
                    self.__snmpEngine,
                    target["name"],
                    target["auth"],
                    target["transport"],
                    oids,
                )

    def stop(self, wait_on_join=True, join_timeout=5):

        # stop the main server
        ScalyrMonitor.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)
