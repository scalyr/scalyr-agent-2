# Copyright 2015 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License")
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ------------------------------------------------------------------------
#
# A ScalyrMonitor which monitors the status of PostgreSQL databases.
#
# Note, this can be run in standalone mode by:
#     python -m scalyr_agent.run_monitor scalyr_agent.builtin_monitors.mysql_monitor

from __future__ import unicode_literals
from __future__ import absolute_import

import sys
from datetime import datetime

import pg8000  # pylint: disable=import-error
import six
from six.moves import zip

from scalyr_agent import (
    ScalyrMonitor,
    UnsupportedSystem,
    define_config_option,
    define_metric,
    define_log_field,
)

# We must require 2.5 or greater right now because pg8000 requires it.
if sys.version_info[0] < 2 or (sys.version_info[0] == 2 and sys.version_info[1] < 5):
    raise UnsupportedSystem("postgresql_monitor", "Requires Python 2.5 or greater.")

__monitor__ = __name__


define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.postgres_monitor`",
    required_option=True,
)
define_config_option(
    __monitor__,
    "id",
    "Optional. An id, included with each event. Shows in the UI as a value for the `instance` "
    "field. If you are running multiple instances of this plugin, id lets you distinguish "
    "between them. This is especially useful if you are running multiple PostgreSQL instances "
    "on a single server. Each instance has a separate `{...}` stanza in the configuration "
    "file (`/etc/scalyr-agent-2/agent.json`).",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "database_host",
    "Optional (default to `localhost`). Name of the host on which PostgreSQL is running.",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "database_port",
    "Optional (defaults to `5432`). Port for PostgreSQL.",
    convert_to=int,
)
define_config_option(
    __monitor__,
    "database_name",
    "Name of the PostgreSQL database the Scalyr Agent will connect to.",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "database_username",
    "Username the Scalyr Agent connects with.",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "database_password",
    "Password the Scalyr Agent connects with.",
    convert_to=six.text_type,
)

# Metric definitions.
define_metric(
    __monitor__,
    "postgres.database.connections",
    "Number of active connections.",
    cumulative=False,
    category="Connections",
)
define_metric(
    __monitor__,
    "postgres.database.transactions",
    "Number of committed transactions. The value is cumulative until reset "
    "by `postgres.database.stats_reset`.",
    extra_fields={"result": "committed"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.transactions",
    "Number of rolled back transactions. The value is cumulative until "
    "reset by `postgres.database.stats_reset`.",
    extra_fields={"result": "rolledback"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.disk_blocks",
    "Number of disk blocks read from the database. The value is cumulative "
    "until reset by `postgres.database.stats_reset`.",
    extra_fields={"type": "read"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.disk_blocks",
    "Number of disk blocks read from the buffer cache. "
    "The value is cumulative until reset by `postgres.database.stats_reset`.",
    extra_fields={"type": "hit"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.query_rows",
    "Number of rows returned by all queries. The value is cumulative "
    "until reset by `postgres.database.stats_reset`.",
    extra_fields={"op": "returned"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.query_rows",
    "Number of rows fetched by all queries. The value is cumulative "
    "until reset by `postgres.database.stats_reset`.",
    extra_fields={"op": "fetched"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.query_rows",
    "Number of rows inserted by all queries. The value is cumulative "
    "until reset by `postgres.database.stats_reset`.",
    extra_fields={"op": "inserted"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.query_rows",
    "Number of rows updated by all queries. The value is cumulative "
    "until reset by `postgres.database.stats_reset`.",
    extra_fields={"op": "updated"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.query_rows",
    "Number of rows deleted by all queries. The value is cumulative "
    "until reset by `postgres.database.stats_reset`.",
    extra_fields={"op": "deleted"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.temp_files",
    "Number of temporary files created by queries to the database. "
    "The value is cumulative until reset by `postgres.database.stats_reset`.",
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.temp_bytes",
    "Bytes written to temporary files by queries to the database. "
    "The value is cumulative until reset by `postgres.database.stats_reset`.",
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.deadlocks",
    "Number of deadlocks detected. The value is cumulative "
    "until reset by `postgres.database.stats_reset`.",
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.blocks_op_time",
    "Read time in milliseconds for file blocks read by clients. "
    "The value is cumulative until reset by `postgres.database.stats_reset`.",
    extra_fields={"op": "read"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.blocks_op_time",
    "Write time in milliseconds for file blocks written by clients. "
    "The value is cumulative until reset by `postgres.database.stats_reset`.",
    extra_fields={"op": "write"},
    cumulative=True,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.stats_reset",
    "The time at which database statistics were last reset.",
    cumulative=False,
    category="General",
)
define_metric(
    __monitor__,
    "postgres.database.size",
    "Size in bytes of the database.",
    cumulative=False,
    category="General",
)

define_log_field(__monitor__, "monitor", "Always `postgres_monitor`.")
define_log_field(
    __monitor__, "instance", "The `id` value. See [Configuration Options](#options)."
)
define_log_field(__monitor__, "metric", 'Name of the metric, e.g. "postgres.vars".')
define_log_field(__monitor__, "value", "Value of the metric.")


class PostgreSQLDb(object):
    """Represents a PopstgreSQL database"""

    _database_stats = {
        "pg_stat_database": {
            "numbackends": ["postgres.database.connections"],
            "xact_commit": ["postgres.database.transactions", "result", "committed"],
            "xact_rollback": ["postgres.database.transactions", "result", "rolledback"],
            "blks_read": ["postgres.database.disk_blocks", "type", "read"],
            "blks_hit": ["postgres.database.disk_blocks", "type", "hit"],
            "tup_returned": ["postgres.database.query_rows", "op", "returned"],
            "tup_fetched": ["postgres.database.query_rows", "op", "fetched"],
            "tup_inserted": ["postgres.database.query_rows", "op", "inserted"],
            "tup_updated": ["postgres.database.query_rows", "op", "updated"],
            "tup_deleted": ["postgres.database.query_rows", "op", "deleted"],
            "temp_files": ["postgres.database.temp_files"],
            "temp_bytes": ["postgres.database.temp_bytes"],
            "deadlocks": ["postgres.database.deadlocks"],
            "blk_read_time": ["postgres.database.blocks_op_time", "op", "read"],
            "blk_write_time": ["postgres.database.blocks_op_time", "op", "write"],
            "stats_reset": ["postgres.database.stats_reset"],
        }
    }

    def connect(self):
        try:
            conn = pg8000.connect(
                user=self._user,
                host=self._host,
                port=self._port,
                database=self._database,
                password=self._password,
            )
            self._db = conn
            self._cursor = self._db.cursor()
            self._gather_db_information()
        except pg8000.Error as me:
            self._db = None
            self._cursor = None
            self._logger.error("Database connect failed: %s" % me)
        except Exception as ex:
            self._logger.error("Exception trying to connect occured:  %s" % ex)
            raise Exception("Exception trying to connect:  %s" % ex)

    def is_connected(self):
        """returns True if the database is connected"""
        return self._db is not None

    def close(self):
        """Closes the cursor and connection to this PostgreSQL server."""
        if self._cursor:
            self._cursor.close()
        if self._db:
            self._db.close()
        self._cursor = None
        self._db = None

    def reconnect(self):
        """Reconnects to this PostgreSQL server."""
        self.close()
        self.connect()

    def _get_version(self):
        version = "unknown"
        try:
            self._cursor.execute("select version();")
            r = self._cursor.fetchone()
            # assumes version is in the form of 'PostgreSQL x.y.z on ...'
            s = r[0].split(" ")
            version = s[1]
        except Exception:
            ex = sys.exc_info()[0]
            self._logger.error("Exception getting database version: %s" % ex)
        return version

    def _gather_db_information(self):
        self._version = self._get_version()
        try:
            if self._version == "unknown":
                self._major = self._medium = self._minor = 0
            else:
                version = self._version.split(".")
                self._major = int(version[0])
                self._medium = int(version[1])
        except (ValueError, IndexError):
            self._major = self._medium = 0
            self._version = "unknown"
        except Exception:
            ex = sys.exc_info()[0]
            self._logger.error("Exception getting database version: %s" % ex)
            self._version = "unknown"
            self._major = self._medium = 0

    def _fields_and_data_to_dict(self, fields, data):
        result = {}
        for f, d in zip(fields, data):
            result[f] = d
        return result

    def _retrieve_database_table_stats(self, table):
        try:
            # get the fields and values
            self._cursor.execute(
                "select * from %s where datname = '%s' limit 0;"
                % (table, self._database)
            )
            fields = [desc[0] for desc in self._cursor.description]
            self._cursor.execute(
                "select * from %s where datname = '%s';" % (table, self._database)
            )
            data = self._cursor.fetchone()
        except pg8000.OperationalError as error:
            errcode = error.errcode  # pylint: disable=no-member
            if errcode != 2006:  # "PostgreSQL server has gone away"
                raise Exception("Database error -- " + errcode)
            self.reconnect()
            return None

        # combine the fields and data
        data = self._fields_and_data_to_dict(fields, data)

        # extract the ones we want
        dict = {}
        for i in self._database_stats[table].keys():
            if i in data:
                dict[i] = data[i]
        return dict

    def retrieve_database_stats(self):
        result = {}
        for i in self._database_stats.keys():
            tmp = self._retrieve_database_table_stats(i)
            if tmp is not None:
                result.update(tmp)
        return result

    def retrieve_database_size(self):
        try:
            self._cursor.execute("select pg_database_size('%s');" % self._database)
            size = self._cursor.fetchone()[0]
        except pg8000.OperationalError as error:
            errcode = error.errcode  # pylint: disable=no-member
            if errcode != 2006:  # "PostgreSQL server has gone away"
                raise Exception("Database error -- " + errcode)
            self.reconnect()
            return None
        return size

    def __str__(self):
        return "DB(%r:%r, %r)" % (self._host, self._port, self._version)

    def __repr__(self):
        return self.__str__()

    def __init__(self, host, port, database, username, password, logger=None):
        """Constructor:

        @param database: database we are connecting to
        @param host: database host being connected to
        @param port: database port being connected to
        @param username: username to connect with
        @param password: password to establish connection
        """

        self._host = host
        self._port = port
        self._database = database
        self._user = username
        self._password = password
        self._logger = logger

        self._db = None
        self._cursor = None


class PostgresMonitor(ScalyrMonitor):  # pylint: disable=monitor-not-included-for-win32
    # fmt: off
    r"""
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

"""
    # fmt: on

    def _initialize(self):
        """Performs monitor-specific initialization."""

        # Useful instance variables:
        #   _sample_interval_secs:  The number of seconds between calls to gather_sample.
        #   _config:  The dict containing the configuration for this monitor instance as retrieved from configuration
        #             file.
        #   _logger:  The logger instance to report errors/warnings/etc.

        # determine how we are going to connect
        database = None
        host = "localhost"
        port = 5432
        username = None
        password = None
        if "database_host" in self._config:
            host = self._config["database_host"]
        if "database_port" in self._config:
            port = self._config["database_port"]
        if "database_name" in self._config:
            database = self._config["database_name"]
        if "database_username" in self._config:
            username = self._config["database_username"]
        if "database_password" in self._config:
            password = self._config["database_password"]

        if (
            "database_name" not in self._config
            or "database_username" not in self._config
            or "database_password" not in self._config
        ):
            raise Exception(
                "database_name, database_username and database_password must be specified in the configuration."
            )

        self._db = PostgreSQLDb(
            database=database,
            host=host,
            port=port,
            username=username,
            password=password,
            logger=self._logger,
        )

    def gather_sample(self):
        """Invoked once per sample interval to gather a statistic."""

        def timestamp_ms(dt):
            epoch = datetime(1970, 1, 1, 0, 0, 0, 0)
            dt = dt.replace(tzinfo=None)
            td = dt - epoch
            return (
                td.microseconds + (td.seconds + td.days * 24 * 3600) * 1000000
            ) / 1000

        try:
            self._db.reconnect()
        except Exception as e:
            self._logger.warning(
                "Unable to gather stats for postgres database - %s" % six.text_type(e)
            )
            return

        if not self._db.is_connected():
            self._logger.warning(
                "Unable to gather stats for postgres database - unable to connect to database"
            )
            return

        dbsize = self._db.retrieve_database_size()
        if dbsize is not None:
            self._logger.emit_value("postgres.database.size", dbsize)
        dbstats = self._db.retrieve_database_stats()
        if dbstats is not None:
            for table in self._db._database_stats.keys():
                for key in self._db._database_stats[table].keys():
                    if key in list(dbstats.keys()):
                        if key != "stats_reset":
                            extra = None
                            if len(self._db._database_stats[table][key]) == 3:
                                extra = {}
                                extra[
                                    self._db._database_stats[table][key][1]
                                ] = self._db._database_stats[table][key][2]
                            self._logger.emit_value(
                                self._db._database_stats[table][key][0],
                                dbstats[key],
                                extra,
                            )
                        else:
                            self._logger.emit_value(
                                self._db._database_stats[table][key][0],
                                timestamp_ms(dbstats[key]),
                            )
        # Database statistics are constant for the duration of a transaction, and by default, the
        # database runs all queries for a connection under a single transaction.  If we don't close
        # the connection then next gather sample we will still hold the same connection, which is
        # still the same transaction, and no statistics will have been updated.
        # Closing the connection also means that we are not needlessly holding an idle connection
        # for the duration of the gather sample interval.
        self._db.close()
