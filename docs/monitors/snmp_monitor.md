<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

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

<a name="options"></a>
## Configuration Options

| Property                | Description | 
| ---                     | --- | 
| `module`                | Always `scalyr_agent.builtin_monitors.snmp_monitor` | 
| `mib_path`              | Optional (defaults to `none`). An absolute path to ASN1 MIB files | 
| `oid_groups`            | A `{...}` JSON object, mapping a "group" (key name) to a `[...]` list of MIBs and OIDs. Lets you import device values from multiple devices. For example, `oid_groups: { "group1" : [ "IF-MIB::ifInOctets", "1.3.6.1.2.1.2.2.1.16.1" ] }`. | 
| `poll_targets`          | See Steps **3** and **4**. An array of `{...}` target objects, each with a `targets` and `oids` property. `targets` is an array of objects. Each object sets the `host` and `port` for the device. `port` defaults to `161` if not set. `oids` is a list of "groups" set in Step **2**. For example, `poll_targets: [ { "targets": [ { "host": "demo.snmplabs.com" }, { "host": "demo.snmplabs.com", "port": 1161 } ], "oids" : [ "group1", "group2" ] } ]`. You can also add the `user`, `version`, `timeout`, and `retries` properties. | 
| `error_repeat_interval` | Optional (defaults to 300). Seconds to wait before repeating an error message. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field         | Description | 
| ---           | --- | 
| `monitor`     | Always `snmp_monitor`. | 
| `poll_target` | The device that was queried to retrieve this value, for example `demo.snpmlabs.com`. | 
| `oid`         | The OID for the retrieved value, for example `IF-MIB::ifDescr."1"`. | 
| `value`       | The value reported by the device. | 
