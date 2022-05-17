<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# PostgreSQL

Import performance and usage data from a PostgreSQL server.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).


## Installation

1\. Install the Scalyr Agent

If you haven't already done so, install the [Scalyr Agent](https://app.scalyr.com/help/welcome), typically on the host running PostgreSQL.

The Agent requires Python 2.7 or higher as of version 2.0.52 (2019). You can install the Agent on a host other than the one running PostgreSQL. If you must run this plugin on an older version of Python, contact us at [support@scalyr.com](mailto:support@scalyr.com).


2\. Check requirements

You must have a PostgreSQL user account with password login. See the [CREATE ROLE](www.postgresql.org/docs/current/sql-createrole.html) documentation.

You must also configure PostgreSQL for TCP/IP connections from the Scalyr Agent. Add a line similar to the following in your [pg_hba.conf](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html) file:

    host    all             all             127.0.0.1/32            md5

You can verify your configuration. An example for user "statusmon", with password "getstatus":

    $ psql -U statusmon -W postgres -h localhost
    Password for user statusmon: <enter password>
    psql (9.3.5)
    SSL connection (cipher: DHE-RSA-AES256-SHA, bits: 256)
    Type "help" for help.

    postgres=#

If the configuration is incorrect, or you entered an invalid password, you will see something like this:

    $ psql -U statusmon -W postgres -h localhost
    psql: FATAL:  password authentication failed for user "statusmon"
    FATAL:  password authentication failed for user "statusmon"


3\. If you grant the above permissions after the Scalyr Agent has started, restart:

      sudo scalyr-agent-2 restart


4\. Configure the Scalyr Agent to import PostgreSQL data

Open the Scalyr Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for PostgreSQL:

    monitors: [
      {
        module:              "scalyr_agent.builtin_monitors.postgres_monitor",
        database_name:       "<database>",
        database_username:   "<username>",
        database_password:   "<password>"
      }
    ]


Enter values from step **2** for the `database_name`, `database_username`, and `database_password` properties.

This configuration assumes PostgreSQL is running on the same server as the Scalyr Agent (localhost), on port 5432. If not, set the server's socket file, or hostname (or IP address) and port number. See the `database_host` and `database_port` properties in [Configuration Options](#options) below. You can also add the `id` property, which is especially useful to distinguish multiple PostgreSQL instances running on the same host.


5\. Save and confirm

Save the `agent.json` file. The Scalyr Agent will detect changes within 30 seconds. Wait a few minutes for the Agent to begin sending PostgreSQL data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr and click Dashboards > Postgres. You will see an overview of performance statistics, across all hosts running this plugin. The dashboard only shows some of the data collected. Go to Search view and query [monitor = 'postgres_monitor'](/events?filter=monitor%20%3D%20%27postgres_monitor%27) to view all data.

For help, contact us at [support@scalyr.com](mailto:support@scalyr.com).

<a name="options"></a>
## Configuration Options

| Property            | Description | 
| ---                 | --- | 
| `module`            | Always `scalyr_agent.builtin_monitors.postgres_monitor` | 
| `id`                | Optional. An id, included with each event. Shows in the UI as a value for the `instance` field. If you are running multiple instances of this plugin, id lets you distinguish between them. This is especially useful if you are running multiple PostgreSQL instances on a single server. Each instance has a separate `{...}` stanza in the configuration file (`/etc/scalyr-agent-2/agent.json`). | 
| `database_host`     | Optional (default to `localhost`). Name of the host on which PostgreSQL is running. | 
| `database_port`     | Optional (defaults to `5432`). Port for PostgreSQL. | 
| `database_name`     | Name of the PostgreSQL database the Scalyr Agent will connect to. | 
| `database_username` | Username the Scalyr Agent connects with. | 
| `database_password` | Password the Scalyr Agent connects with. | 

<a name="events"></a>
## Event Reference

In the UI, each event has the fields:

| Field      | Description | 
| ---        | --- | 
| `monitor`  | Always `postgres_monitor`. | 
| `instance` | The `id` value. See [Configuration Options](#options). | 
| `metric`   | Name of the metric, e.g. "postgres.vars". | 
| `value`    | Value of the metric. | 

<a name="metrics"></a>
## Metrics Reference

Metrics recorded by this plugin:


### Connections Metrics

| Metric                             | Description | 
| ---                                | --- | 
| `postgres.database.connections`    | Number of active connections. | 

### General Metrics

| Metric                                | Fields              | Description | 
| ---                                   | ---                 | --- | 
| `postgres.database.transactions`      | `result=committed`  | Number of committed transactions. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.transactions`      | `result=rolledback` | Number of rolled back transactions. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.disk_blocks`       | `type=read`         | Number of disk blocks read from the database. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.disk_blocks`       | `type=hit`          | Number of disk blocks read from the buffer cache. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.query_rows`        | `op=returned`       | Number of rows returned by all queries. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.query_rows`        | `op=fetched`        | Number of rows fetched by all queries. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.query_rows`        | `op=inserted`       | Number of rows inserted by all queries. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.query_rows`        | `op=updated`        | Number of rows updated by all queries. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.query_rows`        | `op=deleted`        | Number of rows deleted by all queries. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.temp_files`        |                     | Number of temporary files created by queries to the database. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.temp_bytes`        |                     | Bytes written to temporary files by queries to the database. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.deadlocks`         |                     | Number of deadlocks detected. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.blocks_op_time`    | `op=read`           | Read time in milliseconds for file blocks read by clients. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.blocks_op_time`    | `op=write`          | Write time in milliseconds for file blocks written by clients. The value is cumulative until reset by `postgres.database.stats_reset`. | 
| `postgres.database.stats_reset`       |                     | The time at which database statistics were last reset. | 
| `postgres.database.size`              |                     | Size in bytes of the database. | 
