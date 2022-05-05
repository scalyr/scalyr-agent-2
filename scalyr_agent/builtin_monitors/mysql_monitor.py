# Copyright 2014 Scalyr Inc and the tcollector authors.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser
# General Public License for more details.  You should have received a copy
# of the GNU Lesser General Public License along with this program.  If not,
# see <http://www.gnu.org/licenses/>.
#
# Note, this file draws heavily on the mysql collector distributed as part of
# the tcollector project (https://github.com/OpenTSDB/tcollector).  As such,
# this file is being distributed under GPLv3.
#
# Note, this can be run in standalone mode by:
#     python -m scalyr_agent.run_monitor scalyr_agent.builtin_monitors.mysql_monitor
from __future__ import unicode_literals
from __future__ import absolute_import

import sys
import re
import os
import stat
import errno

import six

from scalyr_agent import (
    ScalyrMonitor,
    define_config_option,
    define_metric,
    define_log_field,
)

import scalyr_agent.scalyr_logging as scalyr_logging

global_log = scalyr_logging.getLogger(__name__)

# We import pymysql from the third_party directory.  This
# relies on PYTHONPATH being set up correctly, which is done
# in both agent_main.py and config_main.py
#
# noinspection PyUnresolvedReferences,PyPackageRequirements
import pymysql  # pylint: disable=import-error

ACCESS_DENIED_ERROR_MSG = """
Received access denied error which indicates that the user which is used to connect to the database
doesn't have sufficient permissions. For information on which permissions are needed by that user,
please refer to the docs - https://app.scalyr.com/help/monitors/mysql. Original error: %s
""".strip()

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.mysql_monitor`",
    required_option=True,
)
define_config_option(
    __monitor__,
    "id",
    "Optional. An id, included with each event. Shows in the UI as a value for the `instance` field. "
    "If you are running multiple instances of this plugin, id lets you distinguish between them. "
    "This is especially useful if you are running multiple MySQL instances on a single server. "
    "Each instance has a separate `{...}` stanza in the configuration file (`/etc/scalyr-agent-2/agent.json`).",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "database_username",
    "Username to connect to MySQL.",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "database_password",
    "Password to connect to MySQL.",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "database_socket",
    "Location of the socket file, e.g. `/var/run/mysqld_instance2/mysqld.sock`. "
    "If MySQL is running on the same server as the Scalyr Agent, you can usually "
    'set this to "default", and this plugin will look for the location.',
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "database_hostport",
    "Hostname (or IP address) and port number of the MySQL server, e.g. "
    "`dbserver:3306`, or simply `3306` to connect to the local machine. Set "
    "`database_socket` or `database_hostport`, but not both.",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "use_ssl",
    "Optional (defaults to `false`). Set to `true` to enable a Secure Socket Layer "
    "(SSL) for the connection.",
    convert_to=bool,
)
define_config_option(
    __monitor__,
    "ca_file",
    "Optional (defaults to `None`). Location of the Certificate Authority (CA) ca file "
    "for the SSL connection. Defaults to `None` (no verification of the root certificate).",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "key_file",
    "Optional (defaults to `None`). Location of the key file to use for the SSL connection.",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "cert_file",
    "Optional (defaults to `None`). Location of the cert file to use for the SSL connection.",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "collect_replica_metrics",
    (
        "Optional (defaults to `true`). If `false`, this plugin will not collect replica "
        "or slave metrics. If `false`, the user privileges in step **2** only require the `PROCESS` grant.",
    ),
    convert_to=bool,
    default=True,
)

# Metric definitions.
define_metric(
    __monitor__,
    "mysql.global.aborted_clients",
    "Number of aborted connections. Either the client died, or did not close the "
    "connection properly. The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="Connections",
)
define_metric(
    __monitor__,
    "mysql.global.aborted_connects",
    "Number of failed connection attempts. The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="Connections",
)
define_metric(
    __monitor__,
    "mysql.global.bytes_received",
    "Bytes sent to the database from all clients. The value is cumulative for the uptime of the server.",
    unit="bytes",
    cumulative=True,
    category="Connections",
)
define_metric(
    __monitor__,
    "mysql.global.bytes_sent",
    "Bytes sent from the database to all clients. The value is cumulative for the uptime of the server.",
    unit="bytes",
    cumulative=True,
    category="Connections",
)
define_metric(
    __monitor__,
    "mysql.global.connections",
    "Number of connection attempts (successful and failed). "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="Connections",
)
define_metric(
    __monitor__,
    "mysql.global.max_used_connections",
    "High-water mark: the maximum number of connections at any point in time since the server was started.",
    category="Connections",
)
define_metric(
    __monitor__,
    "mysql.max_connections",
    "Maximum number of allowed open connections.",
    category="Connections",
)

define_metric(
    __monitor__,
    "mysql.global.com_insert",
    "Number of `insert` commands run against the server. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="Commands",
)
define_metric(
    __monitor__,
    "mysql.global.com_delete",
    "Number of `delete` commands run against the server. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="Commands",
)
define_metric(
    __monitor__,
    "mysql.global.com_replace",
    "Number of `replace` commands run against the server. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="Commands",
)
define_metric(
    __monitor__,
    "mysql.global.com_select",
    "Number of `select` commands run against the server. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="Commands",
)

define_metric(
    __monitor__,
    "mysql.global.key_blocks_unused",
    "Number of unused key blocks. A high number indicates a large key cache.",
    category="General",
)
define_metric(
    __monitor__,
    "mysql.global.key_blocks_used",
    "High-water mark: the maximum number of key blocks used since the start of the server.",
    category="General",
)
define_metric(
    __monitor__,
    "mysql.open_files_limit",
    "Maximum number of allowed open files.",
    category="General",
)

define_metric(
    __monitor__,
    "mysql.global.slow_queries",
    'Number of queries exceeding the "long_query_time" configuration. '
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="General",
)

define_metric(
    __monitor__,
    "mysql.innodb.oswait_array.reservation_count",
    "Number of slots allocated to the internal sync array. Used as a measure of the "
    "context switch rate, or the rate at which Innodb falls back to OS Wait, "
    "which is relatively slow.",
    category="InnoDB",
)
define_metric(
    __monitor__,
    "mysql.innodb.oswait_array.signal_count",
    "Number of threads signaled using the sync array. As above, can be used as a measure "
    "of activity of the internal sync array.",
    category="InnoDB",
)
define_metric(
    __monitor__,
    "mysql.innodb.locks.spin_waits",
    "Number of times a thread tried to get an unavailable mutex, and entered the "
    "spin-wait cycle. The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="InnoDB",
)
define_metric(
    __monitor__,
    "mysql.innodb.locks.rounds",
    "Number of times a thread looped through the spin-wait cycle. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="InnoDB",
)
define_metric(
    __monitor__,
    "mysql.innodb.locks.os_waits",
    "Number of times a thread gave up on spin-wait, and entered the sleep cycle. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="InnoDB",
)
define_metric(
    __monitor__,
    "mysql.innodb.history_list_length",
    "Number of unflushed changes in the internal undo buffer. Typically increases "
    "when update transactions are run, and decreases when the internal flush runs.",
    category="InnoDB",
)
define_metric(
    __monitor__,
    "mysql.innodb.opened_read_views",
    'Number of opened read views. These are "started transactions", with no current statement '
    "actively operating.",
    category="InnoDB",
)
define_metric(
    __monitor__,
    "mysql.innodb.queries_queued",
    "Number of queries waiting for execution.",
    category="InnoDB",
)

define_metric(
    __monitor__,
    "mysql.innodb.innodb.ibuf.size",
    "Size in bytes of the insert buffer.",
    category="InnoDB Insert Buffer",
)
define_metric(
    __monitor__,
    "mysql.innodb.innodb.ibuf.free_list_len",
    "Number of pages of the free list for the insert buffer.",
    category="InnoDB Insert Buffer",
)
define_metric(
    __monitor__,
    "mysql.innodb.innodb.ibuf.seg_size",
    "The segment size in bytes of the insert buffer.",
    category="InnoDB Insert Buffer",
)
define_metric(
    __monitor__,
    "mysql.innodb.innodb.ibuf.inserts",
    "Number of inserts into the insert buffer. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="InnoDB Insert Buffer",
)
define_metric(
    __monitor__,
    "mysql.innodb.innodb.ibuf.merged_recs",
    "Number of records merged in the insert buffer. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="InnoDB Insert Buffer",
)
define_metric(
    __monitor__,
    "mysql.innodb.innodb.ibuf.merges",
    "Number of merges for the insert buffer. "
    "The value is cumulative for the uptime of the server.",
    cumulative=True,
    category="InnoDB Insert Buffer",
)

define_metric(
    __monitor__,
    "mysql.process.query",
    "Number of threads performing a query.",
    category="Threads",
)
define_metric(
    __monitor__,
    "mysql.process.sleep",
    "Number of threads sleeping.",
    category="Threads",
)
define_metric(
    __monitor__,
    "mysql.process.xxx",
    "Number of threads in state `xxx`.",
    category="Threads",
)

define_log_field(__monitor__, "monitor", "Always `mysql_monitor`.")
define_log_field(
    __monitor__, "instance", "The `id` value. See [Configuration Options](#options)."
)
define_log_field(__monitor__, "metric", 'Name of the metric, e.g. "mysql.vars".')
define_log_field(__monitor__, "value", "Value of the metric.")


def file_exists(path):
    if path is None:
        return False
    return os.path.exists(path)


def isyes(s):
    if s.lower() == "yes":
        return 1
    return 0


# We do not report any global status metrics that begin with 'com_' unless it is listed here.
__coms_to_report__ = (
    "com_select",
    "com_update",
    "com_delete",
    "com_replace",
    "com_insert",
)


class MysqlDB(object):
    """Represents a MySQL database"""

    def _connect(self):
        try:
            if self._use_ssl and not self._path_to_ca_file:
                global_log.warning(
                    "Connecting to MySql with the `ssl` option but no CA file configured. The server certificate "
                    "will not be validated.",
                    limit_once_per_x_secs=86400,
                    limit_key="mysql_connect_ssl_no_verification",
                )
            ssl = {}
            if self._use_ssl:
                ssl = {"ssl": {}}
                if self._path_to_ca_file:
                    ssl["ca"] = self._path_to_ca_file
                if self._path_to_key_file:
                    ssl["key"] = self._path_to_key_file
                if self._path_to_cert_file:
                    ssl["cert"] = self._path_to_cert_file

            if self._type == "socket":
                if self._use_ssl:
                    conn = pymysql.connect(
                        unix_socket=self._sockfile,
                        user=self._username,
                        passwd=self._password,
                        ssl=ssl,
                    )
                else:
                    conn = pymysql.connect(
                        unix_socket=self._sockfile,
                        user=self._username,
                        passwd=self._password,
                    )
            else:
                if self._use_ssl:
                    conn = pymysql.connect(
                        host=self._host,
                        port=self._port,
                        user=self._username,
                        passwd=self._password,
                        ssl=ssl,
                    )
                else:
                    conn = pymysql.connect(
                        host=self._host,
                        port=self._port,
                        user=self._username,
                        passwd=self._password,
                    )
            self._db = conn
            self._cursor = self._db.cursor()
            self._gather_db_information()
        except pymysql.Error as me:
            self._db = None
            self._cursor = None
            self._logger.error("Database connect failed: %s" % me)
        except Exception as ex:
            self._logger.error("Exception trying to connect occured:  %s" % ex)
            raise Exception("Exception trying to connect:  %s" % ex)

    def _close(self):
        """Closes the cursor and connection to this MySQL server."""
        if self._cursor:
            self._cursor.close()
        if self._db:
            self._db.close()

    def _reconnect(self):
        """Reconnects to this MySQL server."""
        self._close()
        self._connect()

    def _isShowGlobalStatusSafe(self):
        """Returns whether or not SHOW GLOBAL STATUS is safe to run."""
        # We can't run SHOW GLOBAL STATUS on versions prior to 5.1 because it
        # locks the entire database for too long and severely impacts traffic.
        return self._major > 5 or (self._major == 5 and self._medium >= 1)

    def _query(self, sql):
        """Executes the given SQL statement and returns a sequence of rows."""

        # Check to see if we have a cursor - if not, try to reconnect to the db
        if not self._cursor:
            self._reconnect()

        # If we still don't have a valid connection, then return
        if not self._cursor:
            return None

        try:
            self._cursor.execute(sql)
        except pymysql.OperationalError as error:
            (errcode, msg) = error.args
            if errcode != 2006:  # "MySQL server has gone away"
                self._logger.exception(
                    "Exception trying to execute query: %d '%s'"  # pylint: disable=bad-string-format-type
                    % (errcode, msg)
                )
                raise Exception(
                    "Database error -- "
                    + six.text_type(errcode)
                    + ": "
                    + six.text_type(msg)
                )
            self._reconnect()
            return None
        except pymysql.err.InternalError as error:
            (errcode, msg) = error.args
            if errcode == 1227 or "access denied" in str(error):
                # Access denied
                raise Exception(ACCESS_DENIED_ERROR_MSG % (str(error)))
            raise error

        return self._cursor.fetchall()

    def _gather_db_information(self):
        try:
            r = self._query("SELECT VERSION()")
            if r is None or len(r) == 0:
                self._version = "unknown"
            else:
                self._version = r[0][0]
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

    def gather_global_status(self):
        if not self._isShowGlobalStatusSafe():
            return None
        result = []

        query_str = "SHOW /*!50000 GLOBAL */ STATUS"
        query = self._query(query_str)
        if not query:
            self._logger.warn("Query failed: %s" % query_str)
            return None

        for metric, value in query:
            value = self._parse_value(value)
            metric_name = metric.lower()
            # Do not include com_ counters except for com_select, com_delete, com_replace, com_insert, com_update
            if not metric_name.startswith("com_") or metric_name in __coms_to_report__:
                result.append({"field": "global.%s" % metric_name, "value": value})

        return result

    def gather_global_variables(self):
        result = []
        query_str = "SHOW /*!50000 GLOBAL */ VARIABLES"
        query = self._query(query_str)
        if not query:
            self._logger.warn("Query failed: %s" % query_str)
            return None

        for metric, value in query:
            value = self._parse_value(value)
            metric_name = metric.lower()
            # To reduce the amount of metrics we write, we only include the variables that
            # we actually need.
            if metric_name == "max_connections" or metric_name == "open_files_limit":
                result.append({"field": "vars.%s" % metric_name, "value": value})

        return result

    def _has_innodb(self, globalStatus):
        if globalStatus is None:
            return False
        for k in globalStatus:
            if k["field"].startswith("global.innodb"):
                return True
        return False

    def _parse_value(self, value):
        try:
            if "." in value:
                value = float(value)
            else:
                value = int(value)
        except ValueError:
            value = six.text_type(value)  # string values are possible
        return value

    def _parse_data(self, data, fields):
        result = []

        def match(regexp, line):
            return re.match(regexp, line)

        for line in data.split("\n"):
            for search in fields:
                m = match(search["regex"], line)
                if m:
                    for field in search["fields"]:
                        r = {
                            "field": field["label"],
                            "value": self._parse_value(m.group(field["group"])),
                        }
                        if "extra fields" in field:
                            r["extra fields"] = field["extra fields"]
                        result.append(r)
                    continue
        return result

    def gather_innodb_status(self, globalStatus):
        if not self._has_innodb(globalStatus):
            return None

        innodb_status = self._query("SHOW ENGINE INNODB STATUS")[0][2]
        if innodb_status is None:
            return None

        innodb_queries = [
            {
                "regex": r"OS WAIT ARRAY INFO: reservation count (\d+), signal count (\d+)",
                "fields": [
                    {"label": "innodb.oswait_array.reservation_count", "group": 1},
                    {"label": "innodb.oswait_array.signal_count", "group": 2},
                ],
            },
            {
                "regex": r"Mutex spin waits (\d+), rounds (\d+), OS waits (\d+)",
                "fields": [
                    {
                        "label": "innodb.locks.spin_waits",
                        "group": 1,
                        "extra fields": {"type": "mutex"},
                    },
                    {
                        "label": "innodb.locks.rounds",
                        "group": 2,
                        "extra fields": {"type": "mutex"},
                    },
                    {
                        "label": "innodb.locks.os_waits",
                        "group": 3,
                        "extra fields": {"type": "mutex"},
                    },
                ],
            },
            {
                "regex": r"RW-shared spins (\d+), OS waits (\d+); RW-excl spins (\d+), OS waits (\d+)",
                "fields": [
                    {
                        "label": "innodb.locks.spin_waits",
                        "group": 1,
                        "extra fields": {"type": "rw-shared"},
                    },
                    {
                        "label": "innodb.locks.os_waits",
                        "group": 2,
                        "extra fields": {"type": "rw-shared"},
                    },
                    {
                        "label": "innodb.locks.spin_waits",
                        "group": 3,
                        "extra fields": {"type": "rw-exclusive"},
                    },
                    {
                        "label": "innodb.locks.os_waits",
                        "group": 4,
                        "extra fields": {"type": "rw-exclusive"},
                    },
                ],
            },
            {
                "regex": r"Ibuf: size (\d+), free list len (\d+), seg size (\d+),",
                "fields": [
                    {"label": "innodb.ibuf.size", "group": 1},
                    {"label": "innodb.ibuf.free_list_len", "group": 2},
                    {"label": "innodb.ibuf.seg_size", "group": 3},
                ],
            },
            {
                "regex": r"(\d+) inserts, (\d+) merged recs, (\d+) merges",
                "fields": [
                    {"label": "innodb.ibuf.inserts", "group": 1},
                    {"label": "innodb.ibuf.merged_recs", "group": 2},
                    {"label": "innodb.ibuf.merges", "group": 3},
                ],
            },
            {
                "regex": r"\d+ queries inside InnoDB, (\d+) queries in queue",
                "fields": [{"label": "innodb.queries_queued", "group": 1}],
            },
            {
                "regex": r"(\d+) read views open inside InnoDB",
                "fields": [{"label": "innodb.opened_read_views", "group": 1}],
            },
            {
                "regex": r"History list length (\d+)",
                "fields": [{"label": "innodb.history_list_length", "group": 1}],
            },
        ]

        return self._parse_data(innodb_status, innodb_queries)

    def _row_to_dict(self, row):
        """Transforms a row (returned by DB.query) into a dict keyed by column names.

        db: The DB instance from which this row was obtained.
        row: A row as returned by DB.query
        """
        d = {}
        for i, field in enumerate(self._cursor.description):
            column = field[0].lower()  # Lower-case to normalize field names.
            d[column] = row[i]
        return d

    def gather_cluster_status(self):
        if not self._collect_replica_metrics:
            self._logger.debug(
                '"collect_replica_metrics" configuration option is set to False '
                "so replica / slave metrics won't be collected."
            )
            return None

        slave_status = self._query("SHOW SLAVE STATUS")
        if not slave_status:
            self._logger.debug(
                "SHOW SLAVE STATUS returned no result which indicates we are "
                "running on a master. Slave metrics won't be collected."
            )
            return None
        result = None
        slave_status = self._row_to_dict(slave_status[0])
        if "master_host" in slave_status:
            master_host = slave_status["master_host"]
        else:
            master_host = None
        if master_host and master_host != "None":
            result = []
            sbm = slave_status.get("seconds_behind_master")
            if isinstance(sbm, six.integer_types):
                result.append({"field": "slave.seconds_behind_master", "value": sbm})
            result.append(
                {
                    "field": "slave.bytes_executed",
                    "value": slave_status["exec_master_log_pos"],
                }
            )
            result.append(
                {
                    "field": "slave.bytes_relayed",
                    "value": slave_status["read_master_log_pos"],
                }
            )
            result.append(
                {
                    "field": "slave.thread_io_running",
                    "value": isyes(slave_status["slave_io_running"]),
                }
            )
            result.append(
                {
                    "field": "slave.thread_sql_running",
                    "value": isyes(slave_status["slave_sql_running"]),
                }
            )
        return result

    def gather_process_information(self):
        result = []
        states = {}
        process_status = self._query("SHOW PROCESSLIST")
        if not process_status:
            self._logger.warn("Error gathering process list")
            return None

        for row in process_status:
            id, user, host, db_, cmd, time, state = row[:7]
            states[cmd] = states.get(cmd, 0) + 1
        for state, count in six.iteritems(states):
            state = state.lower().replace(" ", "_")
            result.append({"field": "process.%s" % state, "value": count})
        if len(result) == 0:
            result = None
        return result

    def _derived_stat_slow_query_percentage(self, globalVars, globalStatusMap):
        """Calculate the percentage of queries that are slow."""
        pct = 0.0
        if globalStatusMap["global.questions"] > 0:
            pct = 100.0 * (
                float(globalStatusMap["global.slow_queries"])
                / float(globalStatusMap["global.questions"])
            )
        return pct

    def _derived_stat_connections_used_percentage(self, globalVars, globalStatusMap):
        """Calculate what percentage of the configured connections are used.  A high percentage can
        indicate a an app is using more than the expected number / configured number of connections.
        """
        pct = 100.0 * (
            float(globalStatusMap["global.max_used_connections"])
            / float(globalVars["vars.max_connections"])
        )
        if pct > 100:
            pct = 100.0
        return pct

    def _derived_stat_aborted_clients_percentage(self, globalVars, globalStatusMap):
        """Calculate the percentage of client connection attempts that are aborted."""
        pct = 0.0
        if globalStatusMap["global.connections"] > 0:
            pct = 100.0 * (
                float(globalStatusMap["global.aborted_clients"])
                / float(globalStatusMap["global.connections"])
            )
        return pct

    def _derived_stat_aborted_connections_percentage(self, globalVars, globalStatusMap):
        """Calculate the percentage of client connection attempts that fail."""
        pct = 0.0
        if globalStatusMap["global.connections"] > 0:
            pct = 100.0 * (
                float(globalStatusMap["global.aborted_connects"])
                / float(globalStatusMap["global.connections"])
            )
        return pct

    def _derived_stat_read_write_percentage(self, globalVars, globalStatusMap, doRead):
        reads = globalStatusMap["global.com_select"]
        writes = (
            globalStatusMap["global.com_delete"]
            + globalStatusMap["global.com_insert"]
            + globalStatusMap["global.com_update"]
            + globalStatusMap["global.com_replace"]
        )
        pct = 0.0
        top = writes
        if doRead:
            top = reads
        if reads + writes > 0:
            pct = 100.0 * (float(top) / float(writes + reads))
        return pct

    def _derived_stat_write_percentage(self, globalVars, globalStatusMap):
        """Calculate the percentage of queries that are writes."""
        return self._derived_stat_read_write_percentage(
            globalVars, globalStatusMap, False
        )

    def _derived_stat_read_percentage(self, globalVars, globalStatusMap):
        """Calculate the percentate of queries that are reads."""
        return self._derived_stat_read_write_percentage(
            globalVars, globalStatusMap, True
        )

    def _derived_stat_query_cache_efficiency(self, globalVars, globalStatusMap):
        """How efficiently is the query cache being used?"""
        pct = 0.0
        if "global.qcache_hits" in globalStatusMap and (
            globalStatusMap["global.com_select"] + globalStatusMap["global.qcache_hits"]
            > 0
        ):
            pct = 100.0 * (
                float(globalStatusMap["global.qcache_hits"])
                / float(
                    globalStatusMap["global.com_select"]
                    + globalStatusMap["global.qcache_hits"]
                )
            )
        return pct

    def _derived_stat_joins_without_indexes(self, globalVars, globalStatusMap):
        """Calculate the percentage of joins being done without indexes"""
        return (
            globalStatusMap["global.select_range_check"]
            + globalStatusMap["global.select_full_join"]
        )

    def _derived_stat_table_cache_hit_rate(self, globalVars, globalStatusMap):
        """Calculate the percentage of table requests that are cached."""
        pct = 100.0
        if globalStatusMap["global.opened_tables"] > 0:
            pct = 100.0 * (
                float(globalStatusMap["global.open_tables"])
                / float(globalStatusMap["global.opened_tables"])
            )
        return pct

    def _derived_stat_open_file_percentage(self, globalVars, globalStatusMap):
        """Calculate the percentage of files that are open compared to the allowed limit.
        If no open file limit is configured, the value will be 0.
        """
        pct = 0.0
        if globalVars["vars.open_files_limit"] > 0:
            pct = 100.0 * (
                float(globalStatusMap["global.open_files"])
                / float(globalVars["vars.open_files_limit"])
            )
        return pct

    def _derived_stat_immediate_table_lock_percentage(
        self, globalVars, globalStatusMap
    ):
        """Calculate how often a request to lock a table succeeds immediately."""
        pct = 100.0
        if globalStatusMap["global.table_locks_waited"] > 0:
            pct = 100.0 * (
                float(globalStatusMap["global.table_locks_immediate"])
                / float(
                    globalStatusMap["global.table_locks_waited"]
                    + globalStatusMap["global.table_locks_immediate"]
                )
            )
        return pct

    def _derived_stat_thread_cache_hit_rate(self, globalVars, globalStatusMap):
        """Calculate how regularly a connection comes in and a thread is available."""
        pct = 100.0
        if globalStatusMap["global.connections"] > 0:
            pct = 100.0 - (
                float(globalStatusMap["global.threads_created"])
                / float(globalStatusMap["global.connections"])
            )
        return pct

    def _derived_stat_tmp_disk_table_percentage(self, globalVars, globalStatusMap):
        """Calculate the percentage of internal temporary tables were created on disk."""
        pct = 0.0
        if globalStatusMap["global.created_tmp_tables"] > 0:
            pct = (
                100.0
                * float(globalStatusMap["global.created_tmp_disk_tables"])
                / float(globalStatusMap["global.created_tmp_tables"])
            )
        return pct

    def gather_derived_stats(self, globalVars, globalStatusMap):
        """Gather derived stats based on global variables and global status."""
        if not globalVars or not globalStatusMap:
            return None
        stats = [
            "slow_query_percentage",
            "connections_used_percentage",
            "aborted_connections_percentage",
            "aborted_clients_percentage",
            "read_percentage",
            "write_percentage",
            "query_cache_efficiency",
            "joins_without_indexes",
            "table_cache_hit_rate",
            "open_file_percentage",
            "immediate_table_lock_percentage",
            "thread_cache_hit_rate",
            "tmp_disk_table_percentage",
        ]
        result = []
        for s in stats:
            method = "_derived_stat_%s" % s
            if hasattr(self, method) and callable(getattr(self, method)):
                func = getattr(self, method)
                val = func(globalVars, globalStatusMap)
                result.append({"field": "derived.%s" % s, "value": val})
        return result

    def is_sockfile(self, path):
        """Returns whether or not the given path is a socket file."""
        try:
            s = os.stat(path)
        except OSError as error:
            (no, e) = error.args
            if no == errno.ENOENT:
                return False
            self._logger.error("warning: couldn't stat(%r): %s" % (path, e))
            return None
        return s.st_mode & stat.S_IFSOCK == stat.S_IFSOCK

    def __str__(self):
        if self._type == "socket":
            return "DB(%r, %r)" % (self._sockfile, self._version)
        else:
            return "DB(%r:%r, %r)" % (self._host, self._port, self._version)

    def __repr__(self):
        return self.__str__()

    def __init__(
        self,
        type="sockfile",
        sockfile=None,
        host=None,
        port=None,
        username=None,
        password=None,
        logger=None,
        use_ssl=False,
        path_to_ca_file=None,
        path_to_key_file=None,
        path_to_cert_file=None,
        collect_replica_metrics=True,
    ):
        """Constructor: handles both socket files as well as host/port connectivity.

        @param type: is the connection a "socket" or "host:port"
        @param sockfile: if socket connection, the location of the sockfile
        @param host: if host:port connection, the name of the host
        @param port: if host:port connection, the port to connect to
        @param username: username to connect with
        @param password: password to establish connection
        @param path_to_ca_file: optional path to a ca file to use when connecting to mysql over ssl
        @param path_to_key_file: optional path to a key file to use when connecting to mysql over ssl
        @param path_to_cert_file: optional path to a cert file to use when connecting to mysql over ssl
        @param collect_replica_metrics: set to true to try to collect replica (slave) related metrics.
                                        Only applicable when connected to a replica.
        """
        self._default_socket_locations = [
            "/tmp/mysql.sock",  # MySQL's own default.
            "/var/lib/mysql/mysql.sock",  # RH-type / RPM systems.
            "/var/run/mysqld/mysqld.sock",  # Debian-type systems.
        ]

        self._type = type
        self._username = username
        self._password = password
        self._logger = logger
        if self._logger is None:
            raise Exception("Logger required.")
        self._use_ssl = use_ssl
        self._path_to_ca_file = path_to_ca_file
        self._path_to_key_file = path_to_key_file
        self._path_to_cert_file = path_to_cert_file
        self._collect_replica_metrics = collect_replica_metrics

        if type == "socket":
            # if no socket file specified, attempt to find one locally
            if sockfile is None:
                for sock in self._default_socket_locations:
                    if file_exists(sock):
                        if self.is_sockfile(sock):
                            sockfile = sock
                            break
            else:
                if not self.is_sockfile(sockfile):
                    raise Exception(
                        "Specified socket file is not a socket: %s" % sockfile
                    )
            if sockfile is None:
                raise Exception(
                    "Socket file required.  Either one was not specified or the default can not be found."
                )
            self._sockfile = sockfile
        elif type == "host:port":
            self._host = host
            self._port = port
        else:
            raise Exception("Unsupported database connection type.")

        self._connect()
        if self._db is None:
            raise Exception("Unable to connect to db")


class MysqlMonitor(ScalyrMonitor):
    # fmt: off
    r"""
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
        if "database_socket" in self._config and "database_hostport" in self._config:
            raise Exception(
                "Either 'database_socket' or 'database_hostport' can be specified.  Not both."
            )
        elif "database_socket" in self._config:
            self._database_connect_type = "socket"
            if type(self._config["database_socket"]) is six.text_type:
                self._database_socket = self._config["database_socket"]
                if len(self._database_socket) == 0:
                    raise Exception(
                        "A value for 'database_socket' must be specified.  To use default value, use the string 'default'"
                    )
                elif self._database_socket.lower() == "default":
                    self._database_socket = None  # this triggers the default case where we try and determine socket location
            else:
                raise Exception(
                    "database_socket specified must be either an empty string or the location of the socket file to use."
                )
        elif "database_hostport" in self._config:
            self._database_connect_type = "host:port"
            if type(self._config["database_hostport"]) is six.text_type:
                hostport = self._config["database_hostport"]
                if len(hostport) == 0:
                    raise Exception(
                        "A value for 'database_hostport' must be specified.  To use default value, use the string 'default'"
                    )
                elif hostport.lower() == "default":
                    self._database_host = "localhost"
                    self._database_port = 3306
                else:
                    hostPortParts = hostport.split(":")
                    self._database_host = hostPortParts[0]
                    if len(hostPortParts) == 1:
                        self._database_port = 3306
                    elif len(hostPortParts) == 2:
                        try:
                            self._database_port = int(hostPortParts[1])
                        except Exception:
                            raise Exception(
                                "database_hostport specified is incorrect.  The format show be host:port, where port is an integer."
                            )
                    else:
                        raise Exception(
                            "database_hostport specified is incorrect.  The format show be host:port, where port is an integer."
                        )
            else:
                raise Exception(
                    "database_hostport specified must either be an emptry string or the host or host:port to connect to."
                )
        else:
            raise Exception(
                "Must specify either 'database_socket' for 'database_hostport' for connection type."
            )

        if "database_username" in self._config and "database_password" in self._config:
            self._database_user = self._config["database_username"]
            self._database_password = self._config["database_password"]
        else:
            raise Exception(
                "database_username and database_password must be specified in the configuration."
            )
        self._use_ssl = self._config.get("use_ssl", False)
        self._path_to_ca_file = self._config.get("ca_file", None)
        self._path_to_key_file = self._config.get("key_file", None)
        self._path_to_cert_file = self._config.get("cert_file", None)
        self._collect_replica_metrics = self._config.get(
            "collect_replica_metrics", True
        )

        self._db = None

    def _connect_to_db(self):
        """
        Connect to the database if the database isn't already connected
        """
        # if we are already connected, don't do anything
        if self._db is not None:
            return

        try:
            if self._database_connect_type == "socket":
                self._db = MysqlDB(
                    type=self._database_connect_type,
                    sockfile=self._database_socket,
                    host=None,
                    port=None,
                    username=self._database_user,
                    password=self._database_password,
                    logger=self._logger,
                    use_ssl=self._use_ssl,
                    path_to_ca_file=self._path_to_ca_file,
                    path_to_key_file=self._path_to_key_file,
                    path_to_cert_file=self._path_to_cert_file,
                    collect_replica_metrics=self._collect_replica_metrics,
                )
            else:
                self._db = MysqlDB(
                    type=self._database_connect_type,
                    sockfile=None,
                    host=self._database_host,
                    port=self._database_port,
                    username=self._database_user,
                    password=self._database_password,
                    logger=self._logger,
                    use_ssl=self._use_ssl,
                    path_to_ca_file=self._path_to_ca_file,
                    path_to_key_file=self._path_to_key_file,
                    path_to_cert_file=self._path_to_cert_file,
                    collect_replica_metrics=self._collect_replica_metrics,
                )
        except Exception as e:
            self._db = None
            global_log.warning(
                "Error establishing database connection: %s" % (six.text_type(e)),
                limit_once_per_x_secs=300,
                limit_key="mysql_connect_to_db",
            )

    def gather_sample(self):
        """Invoked once per sample interval to gather a statistic."""

        # make sure we have a database connection
        if self._db is None:
            self._connect_to_db()

        # if we still don't have one wait until the next gather sample
        # to try again
        if self._db is None:
            return

        def print_status_line(key, value, extra_fields):
            """Emit a status line."""
            self._logger.emit_value("mysql.%s" % key, value, extra_fields=extra_fields)

        def print_status(status):
            """print a status object, assumed to be a dictionary of key/values (and possibly extra fields)."""
            if status is not None:
                for entry in status:
                    field = entry["field"]
                    value = entry["value"]
                    if "extra_fields" in entry:
                        extra_fields = entry["extra_fields"]
                    else:
                        extra_fields = None
                    print_status_line(field, value, extra_fields)

        globalVars = self._db.gather_global_variables()
        globalStatus = self._db.gather_global_status()
        innodbStatus = self._db.gather_innodb_status(globalStatus)
        clusterStatus = self._db.gather_cluster_status()
        processInfo = self._db.gather_process_information()
        if globalVars is not None:
            print_status(globalVars)
        if globalStatus is not None:
            print_status(globalStatus)
        if innodbStatus is not None:
            print_status(innodbStatus)
        if clusterStatus is not None:
            print_status(clusterStatus)
        if processInfo is not None:
            print_status(processInfo)

        # calculate some derived stats
        if globalVars and globalStatus is not None:
            globalStatusMap = {}
            for f in globalStatus:
                globalStatusMap[f["field"]] = f["value"]
            globalVarsMap = {}
            for f in globalVars:
                globalVarsMap[f["field"]] = f["value"]
            calculatedStats = self._db.gather_derived_stats(
                globalVarsMap, globalStatusMap
            )
            if calculatedStats:
                print_status(calculatedStats)
