/// DECLARE path=/help/monitors/mysql
/// DECLARE title=MySQL Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# MySQL Monitor

This agent monitor plugin records performance and usage data from a MySQL server.

NOTE: The MySQL monitor requires Python 2.7 or higher as of agent release 2.0.52. (This applies to the server on which the Scalyr Agent
is running, which needn't necessarily be the same machine where the MySQL server is running.). If you need
to monitor MySQL from a machine running an older version of Python, [let us know](mailto:support@scalyr.com).

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

## Sample Configuration

To configure the MySQL monitor plugin, you will need the following information:

- A MySQL user with administrative privileges. The user needs to be able to query the information_schema table,
  as well as assorted global status information. See more information on which permissionsa are needed in the
  section below.
- The password for that user.

Here is a sample configuration fragment:

    monitors: [
      {
         module:            "scalyr_agent.builtin_monitors.mysql_monitor",
         database_socket:   "default",
         database_username: "USERNAME",
         database_password: "PASSWORD"
      }
    ]

This configuration assumes that MySQL is running on the same server as the Scalyr Agent, and is using the default
MySQL socket. If not, you will need to specify the server's socket file, or hostname (or IP address) and port number;
see Configuration Reference.

## MySQL User Permissions

As part of the metric gathering process, monitor executes the following queries:

* ``SHOW ENGINE INNODB STATUS;``
* ``SHOW PROCESSLIST;``
* ``SHOW SLAVE STATUS;``
* ``SHOW /*!50000 GLOBAL */ STATUS;``
* ``SHOW /*!50000 GLOBAL */ VARIABLES;``

To be able to execute those queries, the user you use to authenticate needs a subset of administrative
permissions which are documented below.

You are strongly encouraged to create a dedicated user with a limited set of permissions for this purpose
(e.g. user named ``scalyr-agent-monitor``).

Example below shows DDL you can use to create a new user with the needed permissions.

    -- Create user used for monitoring by the scalyr agent
    -- In this case we allow that user to log in remotely from any host (@'%') and localhost
    -- (@'localhost'), but depending on where the agent and MySQL server is running, you want only want
    -- to grant permissions to connect from localhost. In this case, you should remove the lines
    -- which allow user to connect from any host (@'%').
    CREATE USER IF NOT EXISTS 'scalyr-agent-monitor'@'localhost' IDENTIFIED BY 'your super secret and long password';
    CREATE USER IF NOT EXISTS 'scalyr-agent-monitor'@'%' IDENTIFIED BY 'your super secret and long password';

    -- Revoke all permissions
    REVOKE ALL PRIVILEGES, GRANT OPTION  FROM 'scalyr-agent-monitor'@'localhost';
    REVOKE ALL PRIVILEGES, GRANT OPTION  FROM 'scalyr-agent-monitor'@'%';

    -- Grant necessary permissions
    -- Needed for SHOW PROCESSLIST;
    -- Needed for ENGINE INNODB STATUS;
    -- Needed for SELECT VERSION();
    -- Needed for SHOW /*!50000 GLOBAL */ STATUS;
    -- Needed for SHOW /*!50000 GLOBAL */ VARIABLES;
    GRANT PROCESS on *.* to 'scalyr-agent-monitor'@'localhost';
    GRANT PROCESS on *.* to 'scalyr-agent-monitor'@'%';

    -- Permission grants below are only needed if collect_replica_metrics config option is True
    -- and monitor is configured to connect to a replica and not a primary.

    -- Needed for SHOW SLAVE STATUS;
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

Keep in mind that there are some differences between different MySQL versions and implementations
such as MariaDB so you may need to refer to the documentation for the version you are using to obtain
the correct name of the grant which grants a permission for running ``SHOW SLAVE STATUS;`` command.

If ``collect_replica_metrics`` monitor config option (available since scalyr agent v2.1.26) is set
to ``False`` and monitor is configured to connect to a primary (master), user which is used to run
the queries only needs the ``PROCESS`` permission and nothing else.

If you grant those permissions after the agent has already been started and established connection
to the MySQL server, you will need to restart the agent (which in turn will restart the monitor and
re-establish the connection) for the permission changes to take an affect.

## Viewing Data

After adding this plugin to the agent configuration file, wait one minute for data to begin recording. Then
click the {{menuRef:Dashboards}} menu and select {{menuRef:MySQL}}. (The dashboard may not be listed until
the agent begins sending MySQL data.) You will see an overview of MySQL performance statistics across all
servers where you are running the MySQL plugin. Use the {{menuRef:ServerHost}} dropdown to show data for a
specific server.

The dashboard shows only some of the data collected by the MySQL monitor plugin. To explore the full range
of data collected, go to the Search page and search for [$monitor = 'mysql_monitor'](/events?filter=$monitor%20%3D%20%27mysql_monitor%27).
This will show all data collected by this plugin, across all servers. You can use the {{menuRef:Refine search by}}
dropdown to narrow your search to specific servers and monitors.

The [View Logs](/help/view) page describes the tools you can use to view and analyze log data.
[Query Language](/help/query-language) lists the operators you can use to select specific metrics and values.
You can also use this data in [Dashboards](/help/dashboards) and [Alerts](/help/alerts).

<a name="options"></a>
## Configuration Options

| Property                  | Description | 
| ---                       | --- | 
| `module`                  | Always ``scalyr_agent.builtin_monitors.mysql_monitor `` | 
| `id`                      | Optional. Included in each log message generated by this monitor, as a field named ``instance``. Allows you to distinguish between values recorded by different monitors. This is especially useful if you are running multiple MySQL instances on a single server; you can monitor each instance with a separate mysql_monitor record in the Scalyr Agent configuration. | 
| `database_username`       | Username which the agent uses to connect to MySQL to retrieve monitoring data. | 
| `database_password`       | Password for connecting to MySQL. | 
| `database_socket`         | Location of the socket file for connecting to MySQL, e.g. ``/var/run/mysqld_instance2/mysqld.sock``. If MySQL is running on the same server as the Scalyr Agent, you can usually set this to "default". | 
| `database_hostport`       | Hostname (or IP address) and port number of the MySQL server, e.g. ``dbserver:3306``, or simply ``3306`` when connecting to the local machine. You should specify one of ``database_socket`` or ``database_hostport``, but not both. | 
| `use_ssl`                 | Whether or not to use SSL when connecting to the MySQL server. Defaults to False. | 
| `ca_file`                 | Location of the ca file to use for the SSL connection. Defaults to None, which means serve certificate verification won't be performed.will not be verified. | 
| `key_file`                | Location of the key file to use for the SSL connection. Defaults to None. | 
| `cert_file`               | Location of the cert file to use for the SSL connection. Defaults to None | 
| `collect_replica_metrics` | Set this value to true if the monitor is configured to connect to a MySQL replica / slave. Setting it to false will cause monitor not to collect any replica / slave related metrics. This means that when connecting to a primary / master, user which is used to authenticate only needs "PROCESS" permission grant and nothing else. Keep in mind that you can also leave this set to true when connecting to a master - in such case, the monitor will still try to query for replica metrics and as such, require permissions to execute "SHOW SLAVE STATUS;" query. For backward compatibility reasons, this value defaults to true. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field      | Description | 
| ---        | --- | 
| `monitor`  | Always ``mysql_monitor``. | 
| `instance` | The ``id`` value from the monitor configuration. | 
| `metric`   | The name of a metric being measured, e.g. "mysql.vars". | 
| `value`    | The metric value. | 

<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:


### Connections Metrics

| Metric                                 | Description | 
| ---                                    | --- | 
| `mysql.global.aborted_clients`         | The number of connections aborted because the client died or didn't close the connection properly.  The value is relative to the uptime of the server. | 
| `mysql.global.aborted_connects`        | The number of failed connection attempts.  The value is relative to the uptime of the server. | 
| `mysql.global.bytes_received`          | How much data has been sent to the database from all clients.  The value is relative to the uptime of the server. | 
| `mysql.global.bytes_sent`              | How much data has been sent from the database to all clients.  The value is relative to the uptime of the server. | 
| `mysql.global.connections`             | Total number of connection attempts (successful and failed).  The value is relative to the uptime of the server. | 
| `mysql.global.max_used_connections`    | High water mark for the total number of connections used at any one time since the server was started. | 
| `mysql.max_connections`                | The maximum number of allowed open connections to server. | 

### Commands Metrics

| Metric                        | Description | 
| ---                           | --- | 
| `mysql.global.com_insert`     | The number of ``insert`` commands run against the server | 
| `mysql.global.com_delete`     | The number of ``delete`` commands run against the server | 
| `mysql.global.com_replace`    | The number of ``replace`` commands run against the server | 
| `mysql.global.com_select`     | The number of ``select`` commands run against the server | 

### General Metrics

| Metric                              | Description | 
| ---                                 | --- | 
| `mysql.global.key_blocks_unused`    | The total number of keyblocks unused at the time of the monitor check.  A high number indicates that the key cache might be large. | 
| `mysql.global.key_blocks_used`      | Maximum number of key blocks used at any one point.  Indicates a high water mark of the number used.  The value is relative to the uptime of the server. | 
| `mysql.open_files_limit`            | The maximum number of allowed open files. | 
| `mysql.global.slow_queries`         | The total number of queries over the uptime of the server that exceeded the "long_query_time" configuration. | 

### InnoDB Metrics

| Metric                                           | Description | 
| ---                                              | --- | 
| `mysql.innodb.oswait_array.reservation_count`    | A measure of how actively innodb uses it's internal sync array. Specifically, how frequently slots are allocated. | 
| `mysql.innodb.oswait_array.signal_count`         | As above, part of the measure of activity of the internal sync array, in this case how frequently threads are signaled using the sync array. | 
| `mysql.innodb.locks.spin_waits`                  | The number of times since server start that a thread tried to a mutex that wasn't available. | 
| `mysql.innodb.locks.rounds`                      | The number of times since server start that a thread looped through the spin-wait cycle. | 
| `mysql.innodb.locks.os_waits`                    | The number of times since server start that a thread gave up spin-waiting and went to sleep. | 
| `mysql.innodb.history_list_length`               | The number of unpurged transactions in the internal undo buffer It typically increases while transactions with updates are run and will decrease once the internal purge runs. | 
| `mysql.innodb.opened_read_views`                 | The number of views into the db, this is "started transactions" which have no current statement actively operating. | 
| `mysql.innodb.queries_queued`                    | The number of queries waiting to be processed.  The value is based on the time the monitor sample is run. | 

### InnoDB Insert Buffer Metrics

| Metric                                      | Description | 
| ---                                         | --- | 
| `mysql.innodb.innodb.ibuf.size`             | The size of the insert buffer. | 
| `mysql.innodb.innodb.ibuf.free_list_len`    | The size free list for the insert buffer. | 
| `mysql.innodb.innodb.ibuf.seg_size`         | The segment size of the insert buffer. | 
| `mysql.innodb.innodb.ibuf.inserts`          | The total number of inserts since server start into the insert buffer. | 
| `mysql.innodb.innodb.ibuf.merged_recs`      | The total number of records merged in the insert buffer since server start. | 
| `mysql.innodb.innodb.ibuf.merges`           | The total number of merges for the insert buffer since server start. | 

### Threads Metrics

| Metric                   | Description | 
| ---                      | --- | 
| `mysql.process.query`    | The number of threads performing a query. | 
| `mysql.process.sleep`    | The number of threads sleeping. | 
| `mysql.process.xxx`      | The number of threads in state ``xxx`` | 
