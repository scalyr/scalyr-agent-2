/// DECLARE path=/help/monitors/mysql
/// DECLARE title=MySQL Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# MySQL

Import performance and usage data from a MySQL server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation


1\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome), typically on the host running MySQL.

The Agent requires Python 2.7 or higher as of version 2.0.52 (2019). You can install the Agent on a host other than the one running MySQL. If you must to run this plugin on an older version of Python, contact us at [support@scalyr.com](mailto:support@scalyr.com).


2\. Check requirements

You must have a MySQL user and password with administrative privileges. This plugin runs the queries:

* `SHOW ENGINE INNODB STATUS;`
* `SHOW PROCESSLIST;`
* `SHOW SLAVE STATUS;`
* `SHOW /*!50000 GLOBAL */ STATUS;`
* `SHOW /*!50000 GLOBAL */ VARIABLES;`

You are strongly encouraged to create a dedicated user, for example `scalyr-agent-monitor`, with a limited set of permissions. See the Data Definition Language (DDL) example below. If you install this plugin on a MySQL replica or slave, and configure it to connect to a primary or master, only the `PROCESS` grant is necessary. See the [collect_replica_metrics](#options) configuration option, and set it to `false` in step **4** below.

Keep in mind there are different versions and implementations of MySQL, such as MariaDB. You may have to consult your version's documentation, in particular for the correct name of the `SHOW SLAVE STATUS;` grant.

    -- Create a user for this plugin.
    -- Allow remote login from any host (@'%'), and from localhost (@'localhost').
    -- If the Agent and MySQL server are running on the same machine, and you only want to
    -- connect from localhost, you can remove the line for any host (@'%').
    CREATE USER IF NOT EXISTS 'scalyr-agent-monitor'@'localhost' IDENTIFIED BY 'your super secret and long password';
    CREATE USER IF NOT EXISTS 'scalyr-agent-monitor'@'%' IDENTIFIED BY 'your super secret and long password';

    -- Revoke all permissions
    REVOKE ALL PRIVILEGES, GRANT OPTION  FROM 'scalyr-agent-monitor'@'localhost';
    REVOKE ALL PRIVILEGES, GRANT OPTION  FROM 'scalyr-agent-monitor'@'%';

    -- Grant necessary permissions
    -- Required for SHOW PROCESSLIST;
    -- Required for ENGINE INNODB STATUS;
    -- Required for SELECT VERSION();
    -- Required for SHOW /*!50000 GLOBAL */ STATUS;
    -- Required for SHOW /*!50000 GLOBAL */ VARIABLES;
    GRANT PROCESS on *.* to 'scalyr-agent-monitor'@'localhost';
    GRANT PROCESS on *.* to 'scalyr-agent-monitor'@'%';

    -- The grants below are only required if the collect_replica_metrics config option is True,
    -- and the plugin is configured to connect to a replica or salve, not a primary or master.

    -- Required for SHOW SLAVE STATUS;
    GRANT REPLICATION CLIENT ON *.* TO 'scalyr-agent-monitor'@'localhost';
    GRANT REPLICATION CLIENT ON *.* TO 'scalyr-agent-monitor'@'%';

    -- Or in some versions of MySQL
    -- GRANT REPLICATION SLAVE, SLAVE MONITOR ON `%`.* TO 'scalyr-agent-monitor'@'localhost';
    -- GRANT REPLICATION SLAVE, SLAVE MONITOR ON `%`.* TO 'scalyr-agent-monitor'@'%';

    -- Or:
    -- GRANT BINLOG MONITOR *.* TO 'scalyr-agent-monitor'@'localhost';
    -- GRANT BINLOG MONITOR *.* TO 'scalyr-agent-monitor'@'%';

    -- Or in MariaDB:
    -- GRANT REPLICA MONITOR ON *.* TO 'scalyr-agent-monitor'@'localhost';
    -- GRANT REPLICA MONITOR ON *.* TO 'scalyr-agent-monitor'@'%';
    -- GRANT SUPER, REPLICATION CLIENT ON *.* TO 'scalyr-agent-monitor'@'localhost';
    -- GRANT SUPER, REPLICATION CLIENT ON *.* TO 'scalyr-agent-monitor'@'%';

    -- Flush privileges
    FLUSH PRIVILEGES;

    -- Show permissions
    SHOW GRANTS FOR 'scalyr-agent-monitor'@'localhost';
    SHOW GRANTS FOR 'scalyr-agent-monitor'@'%';


3\. If you grant the above permissions after the Agent has started, restart:

      sudo scalyr-agent-2 restart


4\. Configure the Scalyr Agent to import MySQL data

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for mysql:

    monitors: [
      {
         module:            "scalyr_agent.builtin_monitors.mysql_monitor",
         database_socket:   "default",
         database_username: "USERNAME",
         database_password: "PASSWORD"
      }
    ]


The `database_socket` property sets the location of the socket file. For example, `/var/run/mysqld_instance2/mysqld.sock`. If MySQL is running on the same server as the Scalyr Agent, you can usually set this to `default`, and this plugin will look for the file location.

The values for  `database_username` and `database_password` are from step **2** above.

See [Configuration Options](#options) below for more properties you can add. You can set a hostname or IP address, and a port number, instead of a socket file. You can also enable a Secure Socket Layer (SSL), and configure the plugin when connecting directly to a replica or slave.


5\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Scalyr Agent to begin sending MySQL data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr and click Dashboards > MySQL. You will see an overview of MySQL performance statistics across all
servers running this plugin. The dashboard only shows some of the data collected by this plugin. To view all data, go to Search view and search for [monitor = 'mysql_monitor'](https://app.scalyr.com/events?filter=monitor+%3D+%27mysql_monitor%27).

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).

<a name="options"></a>
## Configuration Options

| Property                  | Description | 
| ---                       | --- | 
| `module`                  | Always `scalyr_agent.builtin_monitors.mysql_monitor` | 
| `id`                      | Optional. An id, included with each event. Shows in the UI as a value for the `instance` field. If you are running multiple instances of this plugin, id lets you distinguish between them. This is especially useful if you are running multiple MySQL instances on a single server. Each instance has a separate `{...}` stanza in the configuration file (`/etc/scalyr-agent-2/agent.json`). | 
| `database_username`       | Username to connect to MySQL. | 
| `database_password`       | Password to connect to MySQL. | 
| `database_socket`         | Location of the socket file, e.g. `/var/run/mysqld_instance2/mysqld.sock`. If MySQL is running on the same server as the Scalyr Agent, you can usually set this to "default", and this plugin will look for the location. | 
| `database_hostport`       | Hostname (or IP address) and port number of the MySQL server, e.g. `dbserver:3306`, or simply `3306` to connect to the local machine. Set `database_socket` or `database_hostport`, but not both. | 
| `use_ssl`                 | Optional (defaults to `false`). Set to `true` to enable a Secure Socket Layer (SSL) for the connection. | 
| `ca_file`                 | Optional (defaults to `None`). Location of the Certificate Authority (CA) ca file for the SSL connection. Defaults to `None` (no verification of the root certificate). | 
| `key_file`                | Optional (defaults to `None`). Location of the key file to use for the SSL connection. | 
| `cert_file`               | Optional (defaults to `None`). Location of the cert file to use for the SSL connection. | 
| `collect_replica_metrics` | Optional (defaults to `true`). If `false`, this plugin will not collect replica or slave metrics. If `false`, the user privileges in step **2** only require the `PROCESS` grant. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field      | Description | 
| ---        | --- | 
| `monitor`  | Always `mysql_monitor`. | 
| `instance` | The `id` value. See [Configuration Options](#options). | 
| `metric`   | Name of the metric, e.g. "mysql.vars". | 
| `value`    | Value of the metric. | 

<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:


### Connections Metrics

| Metric                                 | Description | 
| ---                                    | --- | 
| `mysql.global.aborted_clients`         | Number of aborted connections. Either the client died, or did not close the connection properly. The value is cumulative for the uptime of the server. | 
| `mysql.global.aborted_connects`        | Number of failed connection attempts. The value is cumulative for the uptime of the server. | 
| `mysql.global.bytes_received`          | Bytes sent to the database from all clients. The value is cumulative for the uptime of the server. | 
| `mysql.global.bytes_sent`              | Bytes sent from the database to all clients. The value is cumulative for the uptime of the server. | 
| `mysql.global.connections`             | Number of connection attempts (successful and failed). The value is cumulative for the uptime of the server. | 
| `mysql.global.max_used_connections`    | High-water mark: the maximum number of connections at any point in time since the server was started. | 
| `mysql.max_connections`                | Maximum number of allowed open connections. | 

### Commands Metrics

| Metric                        | Description | 
| ---                           | --- | 
| `mysql.global.com_insert`     | Number of `insert` commands run against the server. The value is cumulative for the uptime of the server. | 
| `mysql.global.com_delete`     | Number of `delete` commands run against the server. The value is cumulative for the uptime of the server. | 
| `mysql.global.com_replace`    | Number of `replace` commands run against the server. The value is cumulative for the uptime of the server. | 
| `mysql.global.com_select`     | Number of `select` commands run against the server. The value is cumulative for the uptime of the server. | 

### General Metrics

| Metric                              | Description | 
| ---                                 | --- | 
| `mysql.global.key_blocks_unused`    | Number of unused key blocks. A high number indicates a large key cache. | 
| `mysql.global.key_blocks_used`      | High-water mark: the maximum number of key blocks used since the start of the server. | 
| `mysql.open_files_limit`            | Maximum number of allowed open files. | 
| `mysql.global.slow_queries`         | Number of queries exceeding the "long_query_time" configuration. The value is cumulative for the uptime of the server. | 

### InnoDB Metrics

| Metric                                           | Description | 
| ---                                              | --- | 
| `mysql.innodb.oswait_array.reservation_count`    | Number of slots allocated to the internal sync array. Used as a measure of the context switch rate, or the rate at which Innodb falls back to OS Wait, which is relatively slow. | 
| `mysql.innodb.oswait_array.signal_count`         | Number of threads signaled using the sync array. As above, can be used as a measure of activity of the internal sync array. | 
| `mysql.innodb.locks.spin_waits`                  | Number of times a thread tried to get an unavailable mutex, and entered the spin-wait cycle. The value is cumulative for the uptime of the server. | 
| `mysql.innodb.locks.rounds`                      | Number of times a thread looped through the spin-wait cycle. The value is cumulative for the uptime of the server. | 
| `mysql.innodb.locks.os_waits`                    | Number of times a thread gave up on spin-wait, and entered the sleep cycle. The value is cumulative for the uptime of the server. | 
| `mysql.innodb.history_list_length`               | Number of unflushed changes in the internal undo buffer. Typically increases when update transactions are run, and decreases when the internal flush runs. | 
| `mysql.innodb.opened_read_views`                 | Number of opened read views. These are "started transactions", with no current statement actively operating. | 
| `mysql.innodb.queries_queued`                    | Number of queries waiting for execution. | 

### InnoDB Insert Buffer Metrics

| Metric                                      | Description | 
| ---                                         | --- | 
| `mysql.innodb.innodb.ibuf.size`             | Size in bytes of the insert buffer. | 
| `mysql.innodb.innodb.ibuf.free_list_len`    | Number of pages of the free list for the insert buffer. | 
| `mysql.innodb.innodb.ibuf.seg_size`         | The segment size in bytes of the insert buffer. | 
| `mysql.innodb.innodb.ibuf.inserts`          | Number of inserts into the insert buffer. The value is cumulative for the uptime of the server. | 
| `mysql.innodb.innodb.ibuf.merged_recs`      | Number of records merged in the insert buffer. The value is cumulative for the uptime of the server. | 
| `mysql.innodb.innodb.ibuf.merges`           | Number of merges for the insert buffer. The value is cumulative for the uptime of the server. | 

### Threads Metrics

| Metric                   | Description | 
| ---                      | --- | 
| `mysql.process.query`    | Number of threads performing a query. | 
| `mysql.process.sleep`    | Number of threads sleeping. | 
| `mysql.process.xxx`      | Number of threads in state `xxx`. | 
