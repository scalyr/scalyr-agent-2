# Copyright 2017-2023 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
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
# author: scalyr@sentinelone.com

from __future__ import unicode_literals
from __future__ import absolute_import

from __future__ import print_function
from scalyr_agent import compat

__author__ = "scalyr@sentinelone.com"

import errno
from fnmatch import fnmatch
import glob
import json
import logging
import logging.handlers
import os
import os.path
import re
from socket import error as socket_error
import socket
import threading
import time
import traceback
import functools
import sys
from string import Template
from io import open

import six
from six.moves import range
import six.moves.socketserver

try:
    # Only available for python >= 3.6
    import syslogmp
except ImportError:
    syslogmp = None

from scalyr_agent import (
    ScalyrMonitor,
    define_config_option,
    AutoFlushingRotatingFileHandler,
)
from scalyr_agent.monitor_utils.server_processors import RequestSizeExceeded
from scalyr_agent.monitor_utils.auto_flushing_rotating_file import (
    AutoFlushingRotatingFile,
)
from scalyr_agent.util import (
    StoppableThread,
    get_parser_from_config,
)
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration

docker_module_available = True

try:
    from scalyr_agent.builtin_monitors.docker_monitor import (
        get_attributes_and_config_from_labels,
        DockerOptions,
    )
except ImportError:
    # Should typically not happen when using the docker mode because the Docker images we publish have this module
    # installed
    docker_module_available = False

import scalyr_agent.scalyr_logging as scalyr_logging

global_log = scalyr_logging.getLogger(__name__)

__monitor__ = __name__

RUN_EXPIRE_COUNT = 100

define_config_option(
    __monitor__,
    "module",
    "Always `scalyr_agent.builtin_monitors.syslog_monitor`",
    convert_to=six.text_type,
    required_option=True,
)
define_config_option(
    __monitor__,
    "protocols",
    'Optional (defaults to `"tcp:601, udp:514"`). A string of `protocol:port`s, separated '
    "by commas. Sets the ports on which the Scalyr Agent will accept messages. We recommend "
    "TCP for reliability and performance, whenever possible.",
    convert_to=six.text_type,
    default="tcp",
)

define_config_option(
    __monitor__,
    "accept_remote_connections",
    "Optional (defaults to `false`). If `true`, this plugin accepts network connections "
    "from any host. If `false`, only connections from localhost are accepted.",
    default=False,
    convert_to=bool,
)

define_config_option(
    __monitor__,
    "message_log",
    "Optional (defaults to `agent_syslog.log`). File name to store syslog messages. "
    "The file is put in the default Scalyr log directory, unless it is an absolute path. "
    "This is especially useful when running multiple instances of this plugin, to send "
    "dissimilar log types to different files. Add and set a separate `{...}` stanza for "
    "each instance.",
    convert_to=six.text_type,
    default="agent_syslog.log",
)

define_config_option(
    __monitor__,
    "message_log_template",
    "Optional (defaults to `None`, overrides `message_log` when set). Template used to create log "
    "file paths to store syslog messages.  The variables $PROTO, $SRCIP, $DESTPORT, $HOSTNAME, "
    "$APPNAME will be substituted appropriately.  If the path is not absolute, then it is assumed "
    "to be relative to the main Scalyr Agent log directory.  Note that this option is currently "
    "only available via a Dockerized Scalyr Agent due to an external dependency.",
    convert_to=six.text_type,
    default=None,
)

# TODO Retire the use of message_log in lieu of message_log_template

define_config_option(
    __monitor__,
    "parser",
    "Optional (defaults to `agentSyslog`). Parser name for the log file. We recommend using "
    "a single parser for each distinct log type, as this improves maintainability and "
    "scalability. More information on configuring parsers can be found "
    "[here](https://app.scalyr.com/parsers).",
    convert_to=six.text_type,
    default="agentSyslog",
)

define_config_option(
    __monitor__,
    "tcp_buffer_size",
    "Optional (defaults to `8192`). Maximum buffer size for a single TCP syslog message. "
    "Per [RFC 5425](https://datatracker.ietf.org/doc/html/rfc5425#section-4.3.1) "
    "(syslog over TCP/TLS), syslog receivers MUST be able to support messages at least "
    "2048 bytes long, and SHOULD support messages up to 8192 bytes long.",
    default=8192,
    max_value=65536 * 1024,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "message_size_can_exceed_tcp_buffer",
    "Optional (defaults to `false`). If `true`, syslog messages larger than the configured "
    "`tcp_buffer_size` are supported. We use `tcp_buffer_size` as the bytes we try to read "
    "from the socket in a single recv() call. A single message can span multiple TCP packets, "
    "or reads from the socket.",
    default=False,
    convert_to=bool,
)

define_config_option(
    __monitor__,
    "max_log_size",
    "Optional (defaults to `none`). Maximum size of the log file, before rotation. If `none`, "
    "the default value is set from the global `log_rotation_max_bytes` "
    r"[Agent configuration option](https://app.scalyr.com/help/scalyr-agent-env-aware), which defaults to `20*1024*1024`. "
    "Set to `0` for infinite size. Rotation does not show in Scalyr; this property is only "
    "relevant for managing disk space on the host running the Agent. A very small limit could "
    "cause dropped logs if there is a temporary network outage, and the log overflows before "
    "it can be sent.",
    convert_to=int,
    default=None,
)

define_config_option(
    __monitor__,
    "max_log_rotations",
    "Optional (defaults to `none`). Maximum number of log rotations, before older log files are "
    "deleted. If `none`, the value is set from the global level `log_rotation_backup_count` "
    "[Agent configuration option](https://app.scalyr.com/help/scalyr-agent-env-aware), which defaults to `2`. "
    "Set to `0` for infinite rotations.",
    convert_to=int,
    default=None,
)

define_config_option(
    __monitor__,
    "log_flush_delay",
    "Optional (defaults to `1.0`). Time in seconds to wait between flushing the log file "
    "containing the syslog messages.",
    convert_to=float,
    default=1.0,
)
define_config_option(
    __monitor__,
    "tcp_request_parser",
    'Optional (defaults to `"default"`). Sets the TCP packet data request parser. Most '
    'users should leave this as is. The `"default"` setting supports framed and line-delimited '
    'syslog messages. When set to "batch", all lines are written in a single batch, at the end '
    "of processing a packet. This offers better performance at the expense of increased buffer "
    'memory. When set to "raw", received data is written as-is: this plugin will not handle '
    "framed messages, and received lines are not always written as an atomic unit, but as part "
    "of multiple write calls. We recommend this setting when you wish to avoid expensive framed "
    "message parsing, and only want to write received data as-is.",
    default="default",
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "tcp_incomplete_frame_timeout",
    "How long to wait (in seconds) for a complete frame / syslog message, when running in TCP "
    "mode with batch request parser, before giving up and flushing what has accumulated in the buffer.",
    default=5,
    min_value=0,
    max_value=600,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "tcp_message_delimiter",
    "Which character sequence to use for a message delimiter or suffix. Defaults to `\\ n`. "
    "Some implementations, such as the Python syslog handler, use the null character `\\ 000`; "
    "messages can have new lines without the use of framing.",
    default="\n",
    convert_to=six.text_type,
)
define_config_option(
    __monitor__,
    "mode",
    "Optional (defaults to `syslog`). If set to `docker`, this plugin imports log lines sent from "
    "the `docker_monitor`. In particular, the plugin will check for container ids in the tags of "
    "incoming lines, and create log files based on their container names.",
    default="syslog",
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "docker_regex",
    "Regular expression to parse docker logs from a syslog message, when the tag sent to syslog "
    r'has the container id. Defaults to `"^.*([a-z0-9]{12})\[\d+\]: ?"`. If a message matches '
    "this regex, then everything *after* the full matching expression is logged to a file named "
    "`docker-<container-name>.log`.",
    convert_to=six.text_type,
    default=r"^.*([a-z0-9]{12})\[\d+\]: ?",
)

define_config_option(
    __monitor__,
    "docker_regex_full",
    "Regular expression for parsing docker logs from a syslog message, when the tag sent to syslog "
    r'has the container name and id. Defaults to `"^.*([^/]+)/([^[]+)\[\d+\]: ?"`. If a message '
    "matches this regex, then everything *after* the full matching expression is logged to a file "
    "named `docker-<container-name>.log`.",
    convert_to=six.text_type,
    default=r"^.*([^/]+)/([^[]+)\[\d+\]: ?",
)

define_config_option(
    __monitor__,
    "docker_expire_log",
    "Optional (defaults to `300`). The number of seconds of inactivity from a specific container "
    "before the log file is removed. The log will be created again if a new message is received "
    "from the container.",
    default=300,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "docker_accept_ips",
    "Optional. A list of ip addresses to accept connections from, if run in a docker container. "
    "Defaults to a list with the ip address of the default docker bridge gateway. "
    "If `accept_remote_connections` is `true`, this option does nothing.",
)

define_config_option(
    __monitor__,
    "docker_api_socket",
    "Optional (defaults to `/var/scalyr/docker.sock`). Sets the Unix socket to communicate with the "
    "docker API. Only relevant when `mode` is set to `docker`, to look up container names by their "
    "ids. You must set the `api_socket` configuration option in the docker monitor to the "
    "same value. You must also map the host's `/run/docker.sock` to the same value as specified here, "
    "with the -v parameter, for example `docker run -v /run/docker.sock:/var/scalyr/docker.sock ...`.",
    convert_to=six.text_type,
    default="/var/scalyr/docker.sock",
)

define_config_option(
    __monitor__,
    "docker_api_version",
    "Optional (defaults to `auto`). Version of the Docker API to use when communicating. "
    "WARNING: you must set the `docker_api_version` configuration option in the docker monitor "
    "to the same value.",
    convert_to=six.text_type,
    default="auto",
)

define_config_option(
    __monitor__,
    "docker_logfile_template",
    "Optional (defaults to `containers/${CNAME}.log`). Template used to create log file paths "
    "to save docker logs sent by other containers with syslog. The variables $CNAME and $CID will "
    "be substituted with the name and id of the container that is emitting the logs. If the path "
    "is not absolute, then it is assumed to be relative to the main Scalyr Agent log directory.",
    convert_to=six.text_type,
    default="containers/${CNAME}.log",
)

define_config_option(
    __monitor__,
    "docker_cid_cache_lifetime_secs",
    "Optional (defaults to `300`). Controls the docker id to container name cache expiration. "
    "After this number of seconds of inactivity, the cache entry is evicted.",
    convert_to=float,
    default=300.0,
)

define_config_option(
    __monitor__,
    "docker_cid_clean_time_secs",
    "Optional (defaults to `5.0`). Number of seconds to wait between cleaning the docker id "
    "to container name cache. Fractional values are supported.",
    convert_to=float,
    default=5.0,
)

define_config_option(
    __monitor__,
    "docker_use_daemon_to_resolve",
    "Optional (defaults to `true`). When `true`, the Docker daemon resolves container ids to "
    "container names, with the `docker_api_socket`.  When `false`, you must add the "
    '`--log-opt tag="/{{.Name}}/{{.ID}}"` to your running containers, to include the container '
    "name in log messages.",
    convert_to=bool,
    default=True,
)

define_config_option(
    __monitor__,
    "check_for_unused_logs_mins",
    "Optional (defaults to `60`). Number of minutes to wait between checks for log files matching "
    "the `message_log_template` that haven't been written to for a while, and can be deleted.",
    convert_to=int,
    default=60,
)

define_config_option(
    __monitor__,
    "delete_unused_logs_hours",
    "Optional (defaults to `24`). Number of hours to wait before deleting log files matching the "
    "`message_log_template`.",
    convert_to=int,
    default=24,
)

define_config_option(
    __monitor__,
    "check_rotated_timestamps",
    "Optional (defaults to `true`). When `true` the timestamps of all file rotations are checked "
    "for deletion, based on the log deletion configuration options. When `false`, only the file "
    "modification time of the main log file is checked, and rotated files are deleted when the "
    "main log file is deleted.",
    convert_to=bool,
    default=True,
)

define_config_option(
    __monitor__,
    "expire_log",
    "Optional (defaults to `300`). The number of seconds of inactivity from a specific log source "
    "before the log file is removed. The log will be created again if a new message is received "
    "from its source.",
    default=300,
    convert_to=int,
)

# TODO Merge the *{check_for_unused_logs_mins,delete_unused_logs_hours,check_rotated_timestamps,expire_log} options

define_config_option(
    __monitor__,
    "max_log_files",
    "Optional (defaults to `1000`). The maximum number of log files to support simultaneously, "
    "as the use of `message_log_template` may generate many log files depending on its input.",
    default=1000,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "docker_check_for_unused_logs_mins",
    "Optional (defaults to `60`). Number of minutes to wait between checks for log files matching "
    "the `docker_logfile_template` that haven't been written to for a while, and can be deleted.",
    convert_to=int,
    default=60,
)

define_config_option(
    __monitor__,
    "docker_delete_unused_logs_hours",
    "Optional (defaults to `24`). Number of hours to wait before deleting log files matching the "
    "`docker_logfile_template`.",
    convert_to=int,
    default=24,
)

define_config_option(
    __monitor__,
    "docker_check_rotated_timestamps",
    "Optional (defaults to `true`). When `true` the timestamps of all file rotations are checked "
    "for deletion, based on the log deletion configuration options. When `false`, only the file "
    "modification time of the main log file is checked, and rotated files are deleted when the main "
    "log file is deleted.",
    convert_to=bool,
    default=True,
)

# NOTE: On Windows on newer Python 3 versions, BlockingIOError is thrown instead of
# socket.error with EAGAIN when there is no data to be read yet on non blocking socket. And this
# error is not instanceof socket.error!
# https://docs.python.org/3/library/exceptions.html#BlockingIOError
if sys.version_info >= (3, 4, 0):
    NON_BLOCKING_SOCKET_DATA_NOT_READY_EXCEPTIONS = (BlockingIOError,)
else:
    NON_BLOCKING_SOCKET_DATA_NOT_READY_EXCEPTIONS = ()


def _get_default_gateway():
    """Read the default gateway directly from /proc."""
    result = "localhost"
    fh = None
    try:
        fh = open("/proc/net/route")
        for line in fh:
            fields = line.strip().split()
            if fields[1] != "00000000" or not int(fields[3], 16) & 2:
                continue
            # 2->TODO struct.pack|unpack in python < 2.7.7 does not allow unicode format string.
            result = socket.inet_ntoa(
                compat.struct_pack_unicode("<L", int(fields[2], 16))
            )
    except IOError as e:
        global_log.error(
            "Error while getting the default gateway: %s",
            six.text_type(e),
            limit_once_per_x_secs=300,
            limit_key="_get_default_gateway_error",
        )
    finally:
        if fh:
            fh.close()

    return result


class SyslogFrameParser(object):
    """Simple abstraction that implements a 'parse_request' that can be used to parse incoming syslog
    messages.  These will either be terminated by a newline (or crlf) sequence, or begin with an
    integer specifying the number of octects in the message.  The parser performs detection of
    which type the message is and handles it appropriately.
    """

    def __init__(self, max_request_size):
        """Creates a new instance.

        @param max_request_size: The maximum number of bytes that can be contained in an individual request.
        """
        self.__max_request_size = max_request_size

    def parse_request(self, input_buffer, _):
        """Returns the next complete request from 'input_buffer'.

        If the message is framed, then if the number of bytes in the buffer is >= the number of bytes in
        the frame, then return the entire frame, otherwise return None and no bytes are consumed.

        If the message is unframed, then if there is a complete line at the start of 'input_buffer' (where complete line is determined by it
        ending in a newline character), then consumes those bytes from 'input_buffer' and returns the string
        including the newline.  Otherwise None is returned and no bytes are consumed from 'input_buffer'

        @param input_buffer: The bytes to read.
        @param _: The number of bytes available in 'input_buffer'. (not used)

        @return: A string containing the next complete request read from 'input_buffer' or None if there is none.

            RequestSizeExceeded if a line is found to exceed the maximum request size.
            ValueError if the message starts with a digit (e.g. is framed) but the frame size is not delimited by a space
        """
        new_position = None
        try:
            new_position = input_buffer.tell()
            buf = input_buffer.read(self.__max_request_size + 1)

            bytes_received = len(buf)

            if bytes_received > self.__max_request_size:
                # We just consume these bytes if the line did exceeded the maximum.  To some degree, this
                # typically does not matter since once we see any error on a connection, we close it down.
                global_log.warning(
                    "SyslogFrameParser - bytes received exceed buffer size.  Some logs may be lost."
                )
                new_position = None
                raise RequestSizeExceeded(bytes_received, self.__max_request_size)

            framed = False
            if bytes_received > 0:
                c = buf[0]
                framed = c >= "0" and c <= "9"
            else:
                return None

            # offsets contains the start and end offsets of the message within the buffer.
            # an end offset of 0 indicates there is not a valid message in the buffer yet
            offsets = (0, 0)
            if framed:
                offsets = self._framed_offsets(buf, bytes_received)
            else:
                offsets = self._unframed_offsets(buf, bytes_received)

            if offsets[1] != 0:
                # our new position is going to be the previous position plus the end offset
                new_position += offsets[1]

                # return a slice containing the full message
                return buf[offsets[0] : offsets[1]]

            return None
        finally:
            if new_position is not None:
                input_buffer.seek(new_position)

    def _framed_offsets(self, frame_buffer, length):
        result = (0, 0)
        pos = frame_buffer.find(" ")
        if pos != -1:
            frame_size = int(frame_buffer[0:pos])
            message_offset = pos + 1
            if length - message_offset >= frame_size:
                result = (message_offset, message_offset + frame_size)

        return result

    def _unframed_offsets(self, frame_buffer, length):
        result = (0, 0)
        pos = frame_buffer.find("\n")
        if pos != -1:
            result = (0, pos + 1)

        return result


class SyslogUDPHandler(six.moves.socketserver.BaseRequestHandler):
    """Class that reads data from a UDP request and passes it to
    a protocol neutral handler
    """

    def handle(self):
        data = six.ensure_text(self.request[0].strip(), "utf-8", errors="ignore")
        extra = {
            "proto": "udp",
            "srcip": self.client_address[0],
            "destport": self.server.server_address[1],
        }
        self.server.syslog_handler.handle(data, extra)


class SyslogRequestParser(object):
    """
    Syslog TCP request data parser which supports framed and line delimited syslog messages.

    It output line / frame data to disk (aka calls scalyr logger method which does that) as soon
    as it's processed.

    This approach of calling scalyr logger for each frame / line is very inefficient and only allows
    syslog monitors to achieve a throughput of 1.5-3 MB/s or so.
    """

    def __init__(
        self,
        socket,
        socket_client_address,
        socket_server_address,
        max_buffer_size,
        message_size_can_exceed_tcp_buffer=False,
    ):
        self._socket = socket
        self._client_address = socket_client_address
        self._server_address = socket_server_address

        if socket:
            self._socket.setblocking(False)

        self._remaining = None
        self._max_buffer_size = max_buffer_size
        self._message_size_can_exceed_tcp_buffer = message_size_can_exceed_tcp_buffer

        self.is_closed = False

    def read(self):
        """Reads self._max_buffer_size bytes from the buffer"""

        data = None
        try:
            data = self._socket.recv(self._max_buffer_size)
            if not data:
                self.is_closed = True
        except socket.timeout:
            self._socket_error = True
            return None
        except NON_BLOCKING_SOCKET_DATA_NOT_READY_EXCEPTIONS:
            return None
        except socket.error as e:
            if e.errno == errno.EAGAIN:
                return None
            else:
                global_log.warning(
                    "Network error while reading from syslog: %s",
                    six.text_type(e),
                    limit_once_per_x_secs=300,
                    limit_key="syslog-network-error",
                )
                self._socket_error = True
                raise e

        return data

    def process(self, data, handle_frame):
        """Processes data returned from a previous call to read
        :type data: six.binary_type
        """
        if not data:
            global_log.warning(
                "Syslog has seen an empty request, could be an indication of missing data",
                limit_once_per_x_secs=600,
                limit_key="syslog-empty-request",
            )
            return

        # append data to what we had remaining from the previous call
        if self._remaining:
            self._remaining += data
        else:
            self._remaining = data
            self._offset = 0

        size = len(self._remaining)

        # process the buffer until we are out of bytes
        frames_handled = 0

        extra = {
            "proto": "tcp",
            "srcip": self._client_address[0],
            "destport": self._server_address[1],
        }

        while self._offset < size:
            # get the first byte to determine if framed or not
            # 2->TODO use slicing to get bytes in both python versions.
            c = self._remaining[self._offset : self._offset + 1]
            framed = b"0" <= c <= b"9"

            skip = 0  # do we need to skip any bytes at the end of the frame (e.g. newlines)

            # if framed, read the frame size
            if framed:
                frame_end = -1
                pos = self._remaining.find(b" ", self._offset)
                if pos != -1:
                    frame_size = int(self._remaining[self._offset : pos])
                    message_offset = pos + 1
                    if size - message_offset >= frame_size:
                        self._offset = message_offset
                        frame_end = self._offset + frame_size
            else:
                # not framed, find the first newline
                frame_end = self._remaining.find(b"\n", self._offset)
                skip = 1

            # if we couldn't find the end of a frame, then it's time
            # to exit the loop and wait for more data
            if frame_end == -1:
                if not self._message_size_can_exceed_tcp_buffer and (
                    size - self._offset >= self._max_buffer_size
                ):
                    global_log.warning(
                        "Syslog frame exceeded maximum buffer size of %s bytes. You should either "
                        'increase the value of "tcp_buffer_size" monitor config option or set '
                        '"message_size_can_exceed_tcp_buffer" monitor config option to True.'
                        % (self._max_buffer_size),
                        limit_once_per_x_secs=300,
                        limit_key="syslog-max-buffer-exceeded",
                    )

                    # skip invalid bytes which can appear because of the buffer overflow.
                    frame_data = six.ensure_text(
                        self._remaining, "utf-8", errors="ignore"
                    )
                    handle_frame(frame_data, extra)

                    frames_handled += 1
                    # add a space to ensure the next frame won't start with a number
                    # and be incorrectly interpreted as a framed message
                    self._remaining = b" "
                    self._offset = 0

                break

            # output the frame
            frame_length = frame_end - self._offset

            frame_data = six.ensure_text(
                self._remaining[self._offset : frame_end].strip(), "utf-8", "ignore"
            )
            handle_frame(frame_data, extra)
            frames_handled += 1

            self._offset += frame_length + skip

        if frames_handled == 0:
            global_log.info(
                "No frames ready to be handled in syslog.. advisory notice",
                limit_once_per_x_secs=600,
                limit_key="syslog-no-frames",
            )

        self._remaining = self._remaining[self._offset :]
        self._offset = 0


class SyslogRawRequestParser(SyslogRequestParser):
    """
    Special request parser which doesn't perform any handling of the received data, but writes it
    as-is to a file on disk (aka sends it to Scalyr logger class).

    It means it doesn't handle framed messages and received lines won't always be written as a
    complete atomic unit to a file on disk at once, but as part of multiple write calls.

    This handler is to be used when we want to avoid expensive framed message parsing and just want
    to write received data as-is. It's much more efficient and offers much better throughput than
    the default parser which handles framed data, etc.
    """

    def process(self, data, handle_frame):
        extra = {
            "proto": "tcp",
            "srcip": self._client_address[0],
            "destport": self._server_address[1],
        }
        handle_frame(data, extra)


class SyslogBatchedRequestParser(SyslogRequestParser):
    """
    This parser works in exactly the same manner as the default request parser (it supports framed
    and line delimited data), but instead of calling scalyr logger class and writing each frame /
    line as it's processed, it writes all the processed lines in a single batch at the end of
    processing of a specific TCP packet.

    This offers much less overhead and much better performance / throughput vs writing each line /
    frame as it's processed.

    Downside is that it requires us to buffer more data in memory thus increasing memory usage a bit.
    """

    # TODO: Refactor duplicated code and re-use common code between this and base class
    def __init__(
        self,
        socket,
        socket_client_address,
        socket_server_address,
        max_buffer_size,
        incomplete_frame_timeout=None,
        message_delimiter="\n",
    ):
        self._socket = socket
        self._client_address = socket_client_address
        self._server_address = socket_server_address

        if socket:
            self._socket.setblocking(False)

        self._max_buffer_size = max_buffer_size
        self._incomplete_frame_timeout = incomplete_frame_timeout
        self._message_delimiter = six.ensure_binary(message_delimiter)

        # Internal buffer of bytes remained to be processes
        self._remaining = bytearray()
        # Current offset into the internal remaining buffer
        self._offset = 0

        # Stores the timestamp of when we last called "handle_frame()"
        self._last_handle_frame_call_time = int(time.time())

        self.is_closed = False

    def process(self, data, handle_frame):
        """Processes data returned from a previous call to read
        :type data: six.binary_type
        """
        if not data:
            global_log.warning(
                "Syslog has seen an empty request, could be an indication of missing data",
                limit_once_per_x_secs=600,
                limit_key="syslog-empty-request",
            )
            return

        # Append data to what we had remaining from the previous call (if any)
        self._remaining += data

        size = len(self._remaining)

        # Process the buffer until we are out of bytes. Once we are out of bytes, flush processed
        # data to file.
        frames_handled = 0
        data_to_write = bytearray()

        extra = {
            "proto": "tcp",
            "srcip": self._client_address[0],
            "destport": self._server_address[1],
        }

        while self._offset < size:
            # 2->TODO use slicing to get bytes in both python versions.
            # TODO: This is not really robust, we should make it an explicit config option if
            # we should try to parse messages as framed or new line delimited one.
            c = self._remaining[self._offset : self._offset + 1]
            framed = b"0" <= c <= b"9"

            skip = 0  # do we need to skip any bytes at the end of the frame (e.g. newlines)

            # if framed, read the frame size
            if framed:
                frame_end = -1
                pos = self._remaining.find(b" ", self._offset)
                if pos != -1:
                    # NOTE: This could throw in case data was corrupted and we flushed incomplete
                    # message early as part of the previous call so we should handle this scenario
                    # better.
                    frame_size = int(self._remaining[self._offset : pos])
                    message_offset = pos + 1
                    if size - message_offset >= frame_size:
                        self._offset = message_offset
                        frame_end = self._offset + frame_size
            else:
                # not framed, find the first newline
                frame_end = self._remaining.find(self._message_delimiter, self._offset)
                skip = 1

            if frame_end == -1:
                now_ts = int(time.time())
                if (
                    self._incomplete_frame_timeout
                    and (now_ts - self._incomplete_frame_timeout)
                    > self._last_handle_frame_call_time
                ):
                    # If we haven't seen a complete frame / line in this amount of seconds, this likely
                    # indicates there we received bad / corrupted data so we just flush what we have
                    # accumulated so far and start from the beginning.
                    global_log.warning(
                        "Have not seen a complete syslog message / frame in %s seconds. This "
                        "likely indicates we have received bad or corrupted data. Flushing what "
                        "we have accumulated in internal buffer so far."
                        % (self._incomplete_frame_timeout),
                        limit_once_per_x_secs=300,
                        limit_key="syslog-incomplete-message-flush",
                    )

                    handle_frame(
                        self._remaining.decode("utf-8", "ignore").strip(), extra
                    )
                    frames_handled += 1

                    self._last_handle_frame_call_time = int(time.time())
                    self._remaining = bytearray()
                    self._offset = 0

                break

            # Instead of outputting each frame / line once we process it, we output it in batches at
            # the end.
            frame_length = frame_end - self._offset

            frame_data = self._remaining[self._offset : frame_end]

            # We add \n which is stripped to ensure line data is correctly written to a file on disk
            # (aka each syslog message is on a separate line)
            if not frame_data.endswith(b"\n"):
                frame_data += b"\n"

            data_to_write += frame_data

            frames_handled += 1
            self._offset += frame_length + skip

        if frames_handled == 0:
            global_log.info(
                "No frames ready to be handled in syslog... Advisory notice.",
                limit_once_per_x_secs=600,
                limit_key="syslog-no-frames",
            )

        # All the currently available data has been processed, output it and reset the buffer
        if data_to_write:
            handle_frame(data_to_write.decode("utf-8", "ignore").strip(), extra)
            data_to_write = bytearray()

            self._last_handle_frame_call_time = int(time.time())
            self._remaining = self._remaining[self._offset :]
            self._offset = 0


class SyslogTCPHandler(six.moves.socketserver.BaseRequestHandler):
    """Class that reads data from a TCP request and passes it to
    a protocol neutral handler
    """

    # NOTE: Thole whole handler abstraction is not great since it means a new class instance for
    # each new connection.

    def __init__(self, *args, **kwargs):
        self.request_parser = kwargs.pop("request_parser", "default")
        self.incomplete_frame_timeout = kwargs.pop("incomplete_frame_timeout", None)
        self.message_delimiter = kwargs.pop("message_delimiter", "\n")

        if six.PY3:
            super(SyslogTCPHandler, self).__init__(*args, **kwargs)
        else:
            six.moves.socketserver.BaseRequestHandler.__init__(self, *args, **kwargs)

    def handle(self):
        if self.request_parser == "default":
            request_stream = SyslogRequestParser(
                socket=self.request,
                socket_client_address=self.client_address,
                socket_server_address=self.server.server_address,
                max_buffer_size=self.server.tcp_buffer_size,
                message_size_can_exceed_tcp_buffer=self.server.message_size_can_exceed_tcp_buffer,
            )
        elif self.request_parser == "batch":
            request_stream = SyslogBatchedRequestParser(
                socket=self.request,
                socket_client_address=self.client_address,
                socket_server_address=self.server.server_address,
                max_buffer_size=self.server.tcp_buffer_size,
                incomplete_frame_timeout=self.incomplete_frame_timeout,
                message_delimiter=self.message_delimiter,
            )
        elif self.request_parser == "raw":
            request_stream = SyslogRawRequestParser(
                socket=self.request,
                socket_client_address=self.client_address,
                socket_server_address=self.server.server_address,
                max_buffer_size=self.server.tcp_buffer_size,
            )
        else:
            raise ValueError("Invalid request parser: %s" % (self.request_parser))

        global_log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "SyslogTCPHandler.handle - created request_stream. Thread: %d",
            threading.current_thread().ident,
        )

        try:
            count = 0
            while not request_stream.is_closed:
                check_running = False

                data = request_stream.read()
                if data is not None:
                    request_stream.process(data, self.server.syslog_handler.handle)
                    count += 1
                    if count > 1000:
                        check_running = True
                        count = 0
                else:
                    # don't hog the CPU
                    time.sleep(0.01)
                    check_running = True

                # limit the amount of times we check if the server is still running
                # as this is a time consuming operation due to locking
                if check_running and not self.server.is_running():
                    break

        except Exception as e:
            global_log.warning(
                "Error handling request: %s\n\t%s",
                six.text_type(e),
                traceback.format_exc(),
            )

        global_log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "SyslogTCPHandler.handle - closing request_stream. Thread: %d",
            threading.current_thread().ident,
        )


class SyslogUDPServer(
    six.moves.socketserver.ThreadingMixIn, six.moves.socketserver.UDPServer
):
    """Class that creates a UDP SocketServer on a specified port"""

    def __init__(self, port, bind_address, verifier):

        self.__verifier = verifier
        address = (bind_address, port)
        global_log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "UDP Server: binding socket to %s" % six.text_type(address),
        )

        self.allow_reuse_address = True
        six.moves.socketserver.UDPServer.__init__(self, address, SyslogUDPHandler)

    def verify_request(self, request, client_address):
        return self.__verifier.verify_request(client_address)

    def set_run_state(self, run_state):
        """Do Nothing only TCP connections need the runstate"""
        pass


class SyslogTCPServer(
    six.moves.socketserver.ThreadingMixIn, six.moves.socketserver.TCPServer
):
    """Class that creates a TCP SocketServer on a specified port"""

    def __init__(
        self,
        port,
        tcp_buffer_size,
        bind_address,
        verifier,
        message_size_can_exceed_tcp_buffer=False,
        request_parser="default",
        incomplete_frame_timeout=None,
        message_delimiter="\n",
    ):
        self.__verifier = verifier
        address = (bind_address, port)
        global_log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "TCP Server: binding socket to %s" % six.text_type(address),
        )

        self.allow_reuse_address = True
        self.__run_state = None
        self.tcp_buffer_size = tcp_buffer_size
        self.message_size_can_exceed_tcp_buffer = message_size_can_exceed_tcp_buffer
        self.request_parser = request_parser
        self.message_delimiter = message_delimiter

        handler_cls = functools.partial(
            SyslogTCPHandler,
            request_parser=request_parser,
            incomplete_frame_timeout=incomplete_frame_timeout,
            message_delimiter=message_delimiter,
        )
        six.moves.socketserver.TCPServer.__init__(self, address, handler_cls)

    def verify_request(self, request, client_address):
        return self.__verifier.verify_request(client_address)

    def set_run_state(self, run_state):
        self.__run_state = run_state

    def is_running(self):
        if self.__run_state:
            return self.__run_state.is_running()

        return False


class LogDeleter(object):
    """Deletes unused log files that match a log_file_template"""

    def __init__(
        self,
        check_interval_mins,
        delete_interval_hours,
        check_rotated_timestamps,
        max_log_rotations,
        log_path,
        log_file_template,
        substitutions=["CID", "CNAME"],
    ):
        self._check_interval = check_interval_mins * 60
        self._delete_interval = delete_interval_hours * 60 * 60
        self._check_rotated_timestamps = check_rotated_timestamps
        self._max_log_rotations = max_log_rotations
        self._log_glob = os.path.join(
            log_path,
            log_file_template.safe_substitute(**{s: "*" for s in substitutions}),
        )

        self._last_check = time.time()

    def _get_old_logs_for_glob(
        self, current_time, glob_pattern, existing_logs, check_rotated, max_rotations
    ):

        result = []

        for matching_file in glob.glob(glob_pattern):
            try:
                added = False
                mtime = os.path.getmtime(matching_file)
                if (
                    current_time - mtime > self._delete_interval
                    and matching_file not in existing_logs
                ):
                    result.append(matching_file)
                    added = True

                for i in range(max_rotations, 0, -1):
                    rotated_file = matching_file + (".%d" % i)
                    try:
                        if not os.path.isfile(rotated_file):
                            continue

                        if check_rotated:
                            mtime = os.path.getmtime(rotated_file)
                            if current_time - mtime > self._delete_interval:
                                result.append(rotated_file)
                        else:
                            if added:
                                result.append(rotated_file)

                    except OSError as e:
                        global_log.warn(
                            "Unable to read modification time for file '%s', %s"
                            % (rotated_file, six.text_type(e)),
                            limit_once_per_x_secs=300,
                            limit_key="mtime-%s" % rotated_file,
                        )

            except OSError as e:
                global_log.warn(
                    "Unable to read modification time for file '%s', %s"
                    % (matching_file, six.text_type(e)),
                    limit_once_per_x_secs=300,
                    limit_key="mtime-%s" % matching_file,
                )
        return result

    def check_for_old_logs(self, existing_logs):

        old_logs = []
        current_time = time.time()
        if current_time - self._last_check > self._check_interval:

            old_logs = self._get_old_logs_for_glob(
                current_time,
                self._log_glob,
                existing_logs,
                self._check_rotated_timestamps,
                self._max_log_rotations,
            )
            self._last_check = current_time

        for filename in old_logs:
            try:
                os.remove(filename)
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_1, "Deleted old log file '%s'" % filename
                )
            except OSError as e:
                global_log.warn(
                    "Error deleting old log file '%s', %s"
                    % (filename, six.text_type(e)),
                    limit_once_per_x_secs=300,
                    limit_key="delete-%s" % filename,
                )


class SyslogHandler(object):
    """Protocol neutral class for handling messages that come in from a syslog server

    @param line_reporter A function to invoke whenever the server handles lines.  The number of lines
        must be supplied as the first argument.
    """

    def __init__(
        self,
        logger,
        line_reporter,
        config,
        global_config,
        server_host,
        log_path,
        get_log_watcher,
        rotate_options,
        docker_options,
    ):

        docker_logging = config.get("mode") == "docker"
        self.__docker_regex = None
        self.__docker_regex_full = None
        self.__docker_id_resolver = None
        self.__docker_file_template = None
        self.__docker_log_deleter = None

        self._docker_options = None

        if rotate_options is None:
            rotate_options = (2, 20 * 1024 * 1024)

        default_rotation_count, default_max_bytes = rotate_options

        rotation_count = config.get("max_log_rotations")
        if rotation_count is None:
            rotation_count = default_rotation_count

        max_log_size = config.get("max_log_size")
        if max_log_size is None:
            max_log_size = default_max_bytes

        self.__syslog_file_template = None
        self.__syslog_log_deleter = None
        if config.get("message_log_template"):
            self.__syslog_file_template = Template(config.get("message_log_template"))
            global_log.info(
                "Using message_log_template of %s", self.__syslog_file_template.template
            )
            self.__syslog_log_deleter = LogDeleter(
                config.get("check_for_unused_logs_mins"),
                config.get("delete_unused_logs_hours"),
                config.get("check_rotated_timestamps"),
                rotation_count,
                log_path,
                self.__syslog_file_template,
                substitutions=["PROTO", "SRCIP", "DESTPORT", "HOSTNAME", "APPNAME"],
            )
        self.__syslog_expire_log = config.get("expire_log")
        self.__syslog_max_log_files = config.get("max_log_files")
        self.__syslog_loggers = {}
        self.__syslog_default_parser = config.get("parser")
        self.__global_log_configs = global_config.log_configs if global_config else []
        self.__syslog_attributes = JsonObject(config.get("attributes") or {})

        if docker_logging:
            self._docker_options = docker_options
            if self._docker_options is None:
                self._docker_options = DockerOptions()

            self.__docker_regex_full = self.__get_regex(config, "docker_regex_full")
            self.__docker_regex = self.__get_regex(config, "docker_regex")
            self.__docker_file_template = Template(
                config.get("docker_logfile_template")
            )
            self.__docker_log_deleter = LogDeleter(
                config.get("docker_check_for_unused_logs_mins"),
                config.get("docker_delete_unused_logs_hours"),
                config.get("docker_check_rotated_timestamps"),
                rotation_count,
                log_path,
                self.__docker_file_template,
                substitutions=["CID", "CNAME"],
            )

            if config.get("docker_use_daemon_to_resolve"):
                from scalyr_agent.builtin_monitors.docker_monitor import (
                    ContainerIdResolver,
                )

                self.__docker_id_resolver = ContainerIdResolver(
                    config.get("docker_api_socket"),
                    config.get("docker_api_version"),
                    global_log,
                    cache_expiration_secs=config.get("docker_cid_cache_lifetime_secs"),
                    cache_clean_secs=config.get("docker_cid_clean_time_secs"),
                )

        self.__log_path = log_path
        self.__server_host = server_host

        self.__get_log_watcher = get_log_watcher

        self.__logger = logger
        self.__line_reporter = line_reporter
        self.__docker_logging = docker_logging
        self.__docker_loggers = {}
        self.__container_info = {}
        self.__expire_count = 0
        self.__logger_lock = threading.Lock()

        self.__docker_expire_log = config.get("docker_expire_log")

        self.__max_log_rotations = rotation_count
        self.__max_log_size = max_log_size
        self.__flush_delay = config.get("log_flush_delay")

    def __get_regex(self, config, field_name):
        value = config.get(field_name)
        if len(value) > 0:
            return re.compile(value)
        else:
            return None

    def __create_log_config(self, cname, cid, base_config, attributes):

        # Set the parser the log_config['parser'] level
        # otherwise it will be overwritten by a default value due to the way
        # log_config verification works
        base_config["parser"] = get_parser_from_config(
            base_config, attributes, "agentSyslogDocker"
        )

        # config attributes override passed in attributes
        attributes.update(base_config.get("attributes", {}))

        # extra attributes override passed in attributes and config attributes
        extra_attributes = self.__extra_attributes(cname, cid)
        if extra_attributes:
            attributes.update(extra_attributes)

        base_config["attributes"] = JsonObject(attributes)

        full_path = os.path.join(
            self.__log_path,
            self.__docker_file_template.safe_substitute({"CID": cid, "CNAME": cname}),
        )
        base_config["path"] = full_path

        return base_config

    def __extra_attributes(self, cname, cid):

        attributes = None
        try:
            attributes = JsonObject(
                {"monitor": "agentSyslog", "containerName": cname, "containerId": cid}
            )

            if self.__server_host:
                attributes["serverHost"] = self.__server_host

        except Exception:
            global_log.error("Error setting docker logger attribute in SyslogMonitor")
            raise

        return attributes

    def __create_log_file(self, cname, cid, log_config):
        """create our own rotating logger which will log raw messages out to disk."""
        result = None
        try:
            result = AutoFlushingRotatingFile(
                filename=log_config["path"],
                max_bytes=self.__max_log_size,
                backup_count=self.__max_log_rotations,
                flush_delay=self.__flush_delay,
            )

        except Exception as e:
            global_log.error(
                "Unable to open SyslogMonitor log file: %s" % six.text_type(e)
            )
            result = None

        return result

    def __extract_container_info(self, data):
        """Attempts to extract the container id, container name and container labels from the log line received from Docker via
        syslog.

        First, attempts to extract container id using `__docker_regex` and look up the container name and labels via Docker.
        If that fails, attempts to extract the container id and container name using the `__docker_regex_full`.

        @param data: The incoming line
        @type data: six.text_type
        @return: The container name, container id, container labels (or an empty dict) and the rest of the line if extract was successful.  Otherwise,
            None, None, None, None.
        @rtype: six.text_type, six.text_type, dict, six.text_type
        """
        # The reason flags contains some information about the code path used when a container id is not found.
        # We emit this to the log to help us debug customer issues.
        reason_flags = ""
        if self.__docker_regex is not None and self.__docker_id_resolver is not None:
            reason_flags += "1"
            m = self.__docker_regex.match(data)
            if m is not None:
                reason_flags += "2"
                # global_log.log(scalyr_logging.DEBUG_LEVEL_3, 'Matched cid-only syslog format')
                cid = m.group(1)
                cname = None
                clabels = None
                self.__logger_lock.acquire()
                try:
                    if cid not in self.__container_info:
                        reason_flags += "3"
                        self.__container_info[cid] = self.__docker_id_resolver.lookup(
                            cid
                        )
                    cname, clabels = self.__container_info[cid]
                finally:
                    self.__logger_lock.release()

                if cid is not None and cname is not None and clabels is not None:
                    # global_log.log(scalyr_logging.DEBUG_LEVEL_3, 'Resolved container name')
                    return (
                        six.ensure_text(cname),
                        six.ensure_text(cid),
                        clabels,
                        six.ensure_text(data[m.end() :]),
                    )

        if self.__docker_regex_full is not None:
            reason_flags += "4"
            m = self.__docker_regex_full.match(data)
            if m is not None:
                reason_flags += "5"

            if m is not None and m.lastindex == 2:
                # global_log.log(scalyr_logging.DEBUG_LEVEL_3, 'Matched cid/cname syslog format')
                return (
                    six.ensure_text(m.group(1)),
                    six.ensure_text(m.group(2)),
                    {},
                    six.ensure_text(data[m.end() :]),
                )

        regex_str = self.__get_pattern_str(self.__docker_regex)
        regex_full_str = self.__get_pattern_str(self.__docker_regex_full)

        global_log.warn(
            "Could not determine container from following incoming data.  Container logs may be "
            'missing, performance could be impacted.  Data(%s): "%s" Did not match either single '
            'regex: "%s" or full regex: "%s"'
            % (reason_flags, data[:70], regex_str, regex_full_str),
            limit_once_per_x_secs=300,
            limit_key="syslog_docker_cid_not_extracted",
        )
        # global_log.log(scalyr_logging.DEBUG_LEVEL_3, 'Could not extract cid/cname for "%s"', data)

        return None, None, None, None

    def __get_pattern_str(self, regex_value):
        """Helper method for getting the string version of a compiled regular expression.  Also handles if the regex
        is None.
        """
        result = None
        if regex_value is not None:
            result = regex_value.pattern
        return six.text_type(result)

    def __handle_docker_logs(self, data):

        watcher = None
        module = None
        # log watcher for adding/removing logs from the agent
        if self.__get_log_watcher:
            watcher, module = self.__get_log_watcher()

        (cname, cid, labels, line_content) = self.__extract_container_info(data)

        if cname is None:
            return

        current_time = time.time()
        current_log_files = []
        self.__logger_lock.acquire()
        try:
            logger = None
            if cname is not None and cid is not None:
                # check if we already have a logger for this container
                # and if not, then create it
                if cname not in self.__docker_loggers:
                    info = dict()

                    attrs, base_config = get_attributes_and_config_from_labels(
                        labels, self._docker_options
                    )

                    # get the config and set the attributes
                    info["log_config"] = self.__create_log_config(
                        cname, cid, base_config, attrs
                    )
                    info["cid"] = cid

                    # create the physical log files
                    info["logger"] = self.__create_log_file(
                        cname, cid, info["log_config"]
                    )
                    info["last_seen"] = current_time

                    # if we created the log file
                    if info["logger"]:
                        # add it to the main scalyr log watcher
                        if watcher and module:
                            info["log_config"] = watcher.add_log_config(
                                module.module_name, info["log_config"]
                            )

                        # and keep a record for ourselves
                        self.__docker_loggers[cname] = info
                    else:
                        global_log.warn("Unable to create logger for %s." % cname)
                        return

                # at this point __docker_loggers will always contain
                # a logger for this container name, so log the message
                # and mark the time
                logger = self.__docker_loggers[cname]
                logger["last_seen"] = current_time

            if self.__expire_count >= RUN_EXPIRE_COUNT:
                # TODO (Tomaz): We run this function on every single log line so running this check
                # every 100 iterations / log lines seems excesive. We should likely do it less
                # often.
                self.__expire_count = 0

                # find out which if any of the loggers in __docker_loggers have
                # expired
                expired = []

                for key, info in six.iteritems(self.__docker_loggers):
                    if current_time - info["last_seen"] > self.__docker_expire_log:
                        expired.append(key)

                # remove all the expired loggers
                for key in expired:
                    info = self.__docker_loggers.pop(key, None)
                    if info:
                        info["logger"].close()
                        if watcher and module:
                            watcher.remove_log_path(
                                module.module_name, info["log_config"]["path"]
                            )
            self.__expire_count += 1

            for key, info in six.iteritems(self.__docker_loggers):
                current_log_files.append(info["log_config"]["path"])
        finally:
            self.__logger_lock.release()

        if logger:
            logger["logger"].write(line_content)
        else:
            global_log.warning(
                "Syslog writing docker logs to syslog file instead of container log",
                limit_once_per_x_secs=600,
                limit_key="syslog-docker-not-container-log",
            )
            self.__logger.info(data)

        if self.__docker_log_deleter:
            self.__docker_log_deleter.check_for_old_logs(current_log_files)

    def __handle_syslog_logs(self, data, extra):
        extra.update(SyslogHandler._parse_syslog(data))
        extra = {k.upper(): v for k, v in extra.items()}

        watcher = None
        module = None
        if self.__get_log_watcher:
            watcher, module = self.__get_log_watcher()

        logger = None
        logfiles = []

        self.__logger_lock.acquire()
        try:
            path = os.path.join(
                self.__log_path,
                self.__syslog_file_template.safe_substitute(**extra),
            )
            if path not in self.__syslog_loggers:
                if len(self.__syslog_loggers) >= self.__syslog_max_log_files:
                    global_log.warning(
                        "Adding another log file would exceed max_log_files limit "
                        "(will instead write to the base syslog file)",
                        limit_once_per_x_secs=600,
                        limit_key="syslog-max-log-files",
                    )
                else:
                    # Match the new log path with a global log config (generally globbed).
                    # Note that in log configs, .path is required but .attributes may be empty.
                    # If no match is found then log to the base syslog file.

                    log_config_attribs = None
                    for log_config in self.__global_log_configs:
                        if fnmatch(path, log_config["path"]):
                            log_config_attribs = log_config["attributes"]
                            global_log.log(
                                scalyr_logging.DEBUG_LEVEL_1,
                                "Matched %s to %s" % (path, log_config["path"]),
                            )
                            break

                    if log_config_attribs is None:
                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_1,
                            "No match found for %s" % (path,),
                        )

                    if log_config_attribs is not None:
                        logfile = AutoFlushingRotatingFile(
                            filename=path,
                            max_bytes=self.__max_log_size,
                            backup_count=self.__max_log_rotations,
                            flush_delay=self.__flush_delay,
                        )

                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_1,
                            "__syslog_attributes=%s log_config_attribs=%s extra=%s"
                            % (
                                json.dumps(
                                    self.__syslog_attributes.to_dict(),
                                    separators=(",", ":"),
                                ),
                                json.dumps(
                                    log_config_attribs.to_dict(), separators=(",", ":")
                                ),
                                json.dumps(extra, separators=(",", ":")),
                            ),
                        )

                        attribs = self.__syslog_attributes.copy()
                        attribs.update(
                            {
                                k: v
                                for k, v in log_config_attribs.items()
                                if k not in ["parser"]
                            }
                        )
                        attribs.update(
                            {k.lower(): v for k, v in extra.items() if v is not None}
                        )

                        log_config = {
                            "parser": log_config_attribs.get("parser")
                            or self.__syslog_default_parser,
                            "attributes": attribs,
                            "path": path,
                        }

                        if watcher and module:
                            log_config = watcher.add_log_config(
                                module.module_name, log_config
                            )

                        self.__syslog_loggers[path] = {
                            "log_config": log_config,
                            "logger": logfile,
                        }

            if path in self.__syslog_loggers:
                logger = self.__syslog_loggers[path]
                logger["last_seen"] = time.time()

            if self.__expire_count >= RUN_EXPIRE_COUNT:
                # TODO (Tomaz): We run this function on every single log line so running this check
                # every 100 iterations / log lines seems excesive. We should likely do it less
                # often.
                self.__expire_count = 0

                now = time.time()
                expired = [
                    k
                    for k, v in self.__syslog_loggers.items()
                    if now - v["last_seen"] > self.__syslog_expire_log
                ]
                for k in expired:
                    v = self.__syslog_loggers.pop(k, None)
                    if v:
                        v["logger"].close()
                        if watcher and module:
                            watcher.remove_log_path(
                                module.module_name, v["log_config"]["path"]
                            )

                if self.__syslog_log_deleter:
                    logfiles = list(self.__syslog_loggers.keys())
                    self.__syslog_log_deleter.check_for_old_logs(logfiles)

            self.__expire_count += 1

        finally:
            self.__logger_lock.release()

        if logger:
            logger["logger"].write(data)
        else:
            global_log.warning(
                "Syslog writing logs to base syslog file instead of templated file",
                limit_once_per_x_secs=600,
                limit_key="syslog-not-template-log",
            )
            self.__logger.info(data)

    @staticmethod
    def _parse_syslog(msg):
        # The syslogmp module is based on RFC 3164.
        # For support for RFC 5424 use the syslog_rfc5424_parser module.
        rv = {"hostname": None, "appname": None}
        try:
            parsed = syslogmp.parse(msg.encode("utf-8"))
        except Exception as e:
            # TODO: We should probably also track this as a counter + periodically log a warning in
            # case we see more errors of a specific type or similar
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_4,
                "Unable to parse: %s. Error: %s" % (msg, e),
            )
            return rv

        rv["hostname"] = parsed.hostname

        mat = re.search(r"^(.+?)(\[[0-9]+\])?:? ", parsed.message.decode("utf-8"))
        if mat:
            rv["appname"] = mat.group(1)

        return rv

    def handle(self, data, extra):  # type: (six.text_type, dict) -> None
        """
        Feed syslog messages to the appropriate loggers.
        """
        # one more time ensure that we don't have binary string.
        data = six.ensure_text(data, "utf-8", errors="ignore")

        if self.__docker_logging:
            self.__handle_docker_logs(data)
        elif self.__syslog_file_template:
            self.__handle_syslog_logs(data, extra)
        else:
            self.__logger.info(data)

        # We add plus one because the calling code strips off the trailing new lines.
        self.__line_reporter(data.count("\n") + 1)


class RequestVerifier(object):
    """Determines whether or not a request should be processed
    based on the state of various config options
    """

    def __init__(self, accept_remote, accept_ips, docker_logging):
        self.__accept_remote = accept_remote
        self.__accept_ips = accept_ips
        self.__docker_logging = docker_logging

    def verify_request(self, client_address):
        result = True
        address, port = client_address
        if self.__docker_logging:
            result = self.__accept_remote or address in self.__accept_ips

        if not result:
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_4,
                "Rejecting request from %s" % six.text_type(client_address),
            )

        return result


class SyslogServer(object):
    """Abstraction for a syslog server, that creates either a UDP or a TCP server, and
    configures a handler to process messages.

    This removes the need for users of this class to care about the underlying protocol being used

    @param line_reporter A function to invoke whenever the server handles lines.  The number of lines
        must be supplied as the first argument.
    """

    def __init__(
        self,
        protocol,
        port,
        logger,
        config,
        global_config,
        line_reporter,
        accept_remote=False,
        server_host=None,
        log_path=None,
        get_log_watcher=None,
        rotate_options=None,
        docker_options=None,
    ):
        server = None

        accept_ips = config.get("docker_accept_ips")
        if accept_ips is None:
            accept_ips = []
            gateway_ip = _get_default_gateway()
            if gateway_ip:
                accept_ips = [gateway_ip]

        global_log.log(
            scalyr_logging.DEBUG_LEVEL_2,
            "Accept ips are: %s" % six.text_type(accept_ips),
        )

        docker_logging = config.get("mode") == "docker"

        verifier = RequestVerifier(accept_remote, accept_ips, docker_logging)

        try:
            bind_address = self.__get_bind_address(
                docker_logging=docker_logging, accept_remote=accept_remote
            )
            if protocol == "tcp":
                tcp_buffer_size = config.get("tcp_buffer_size")
                message_size_can_exceed_tcp_buffer = config.get(
                    "message_size_can_exceed_tcp_buffer"
                )
                request_parser = config.get("tcp_request_parser")

                if request_parser not in ["default", "batch", "raw"]:
                    raise ValueError(
                        "Invalid tcp_request_parser value: %s" % (request_parser)
                    )

                incomplete_frame_timeout = config.get("tcp_incomplete_frame_timeout")
                message_delimiter = config.get("tcp_message_delimiter")

                # NOTE: User needs to provide escaped value in the config (e.g. \\000), but we
                # need to unsescape it to use it
                # message_delimiter = message_delimiter.replace("\\", "a")
                message_delimiter = six.ensure_binary(
                    message_delimiter.encode("utf-8").decode("unicode_escape")
                )

                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Starting TCP Server (host=%s, port=%s, tcp_buffer_size=%s, "
                    "message_size_can_exceed_tcp_buffer=%s, tcp_request_parser=%s, "
                    "message_delimiter=%s)"
                    % (
                        bind_address,
                        port,
                        tcp_buffer_size,
                        message_size_can_exceed_tcp_buffer,
                        request_parser,
                        message_delimiter.decode("utf-8")
                        .replace("\n", "\\n")
                        .replace("\000", "\\000"),
                    ),
                )
                server = SyslogTCPServer(
                    port,
                    tcp_buffer_size,
                    bind_address=bind_address,
                    verifier=verifier,
                    message_size_can_exceed_tcp_buffer=message_size_can_exceed_tcp_buffer,
                    request_parser=request_parser,
                    incomplete_frame_timeout=incomplete_frame_timeout,
                    message_delimiter=message_delimiter,
                )
            elif protocol == "udp":
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_0,
                    "Starting UDP Server (host=%s, port=%s)" % (bind_address, port),
                )
                server = SyslogUDPServer(
                    port, bind_address=bind_address, verifier=verifier
                )

        except socket_error as e:
            if e.errno == errno.EACCES and port < 1024:
                raise Exception(
                    "Access denied when trying to create a %s server on a low port (%d). "
                    "Please try again on a higher port, or as root." % (protocol, port)
                )
            else:
                raise

        # don't continue if the config had a protocol we don't recognize
        if server is None:
            raise Exception(
                "Unknown value '%s' specified for SyslogServer 'protocol'." % protocol
            )

        # create the syslog handler, and add to the list of servers
        server.syslog_handler = SyslogHandler(
            logger,
            line_reporter,
            config,
            global_config,
            server_host,
            log_path,
            get_log_watcher,
            rotate_options,
            docker_options,
        )
        server.syslog_transport_protocol = protocol
        server.syslog_port = port

        self.__server = server
        self.__thread = None

    def __get_bind_address(self, docker_logging=False, accept_remote=False):
        result = "localhost"
        if accept_remote:
            result = ""
        else:
            # check if we are running inside a docker container
            if docker_logging and os.path.isfile("/.dockerenv"):
                # need to accept from remote ips
                result = ""
        return result

    def __prepare_run_state(self, run_state):
        if run_state is not None:
            server = self.__server
            server.set_run_state(run_state)
            # shutdown is only available from python 2.6 onwards
            # need to think of what to do for 2.4, which will hang on shutdown when run as standalone
            if hasattr(server, "shutdown"):
                run_state.register_on_stop_callback(server.shutdown)

    def start(self, run_state):
        self.__prepare_run_state(run_state)
        self.__server.serve_forever()
        self.__server.socket.close()

    def start_threaded(self, run_state):
        self.__prepare_run_state(run_state)
        self.__thread = StoppableThread(
            target=self.start,
            name="Syslog monitor thread for %s:%d"
            % (self.__server.syslog_transport_protocol, self.__server.syslog_port),
        )
        self.__thread.start()

    def stop(self, wait_on_join=True, join_timeout=5):
        if self.__thread is not None:
            self.__thread.stop(wait_on_join=wait_on_join, join_timeout=join_timeout)


class SyslogMonitor(ScalyrMonitor):
    # fmt: off
    r"""
# Syslog

Import logs from an application or device that supports syslog.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

TCP and UDP protocols are supported. We recommend TCP for reliability and performance, whenever possible.

**For Docker**: We recommend the `json` logging driver. This plugin imports Docker logs configured for the `syslog` driver. Containers on localhost must run the Scalyr Agent and this plugin. Set the `mode` [configuration option](#options) to `docker`.


## Installation

1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome). We recommend installing the Agent on each server you want to monitor. Your data will automatically be tagged for the server it came from. The Agent can also collect system metrics and log files.

You can install the Agent on a single server and configure this plugin to accept messages from all hosts.

If you are on Linux, running Python 3, this [memory leak](https://bugs.python.org/issue37193) was fixed in versions [3.8.9](https://docs.python.org/3.8/whatsnew/changelog.html), [3.9.3 final](https://docs.python.org/3.9/whatsnew/changelog.html), and [3.10.0 alpha 4](https://docs.python.org/3/whatsnew/changelog.html).


2\. Configure the Scalyr Agent

Open the Scalyr Agent configuration file at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section, and add a `{...}` stanza with the `module` property set for syslog.

    monitors: [
      {
        module:                    "scalyr_agent.builtin_monitors.syslog_monitor",
        protocols:                 "tcp:601, udp:514",
        accept_remote_connections: false
      }
    ]

The `protocols` property is a string of `protocol:port` combinations, separated by commas. In the above example, the Agent accepts syslog messages on TCP port 601, and UDP port 514. Note that on Linux, the Scalyr Agent must run as root to use port numbers 1024 or lower.

To accept syslog connections from devices other than localhost, for example a firewall or router on the network, add and set  `accept_remote_connections: true`. The Agent will accept connections from any host.

If you are using this plugin to upload dissimilar log formats (ex. firewall, system services, and application logs), we recommend using multiple instances (denoted in the example below by the {...} stanzas). This lets you associate a separate parser and log file for each log type.

    monitors: [
        {
          module: "scalyr_agent.builtin_monitors.syslog_monitor",
          protocols: "tcp:601, udp:514",
          accept_remote_connections: true,
          message_log: "firewall.log",
          parser: "firewall"
        },
        {
          module: "scalyr_agent.builtin_monitors.syslog_monitor",
          protocols: "tcp:602, udp:515",
          accept_remote_connections: true,
          message_log: "system.log", //send ntpdate, chrond, and dhcpd logs here
          parser: "system"
        },
        {
          module: "scalyr_agent.builtin_monitors.syslog_monitor",
          protocols: "tcp:603, udp:516",
          accept_remote_connections: true,
          message_log: "sonicwall.log", //send SonicWall logs here
          parser: "sonicwall"
        }
    ]

The `message_log` property sets the file name to store syslog messages. It defaults to `agent_syslog.log`. The file is placed in the default Scalyr log directory, unless it is an absolute path.

The `parser` property defaults to "agentSyslog". As a best practice, we recommend creating one parser per distinct log type, as this improves maintainability and scalability. More information on configuring parsers can be found [here](https://app.scalyr.com/parsers).

See [Configuration Options](#options) below for more properties you can add.

If you expect a throughput in excess of 2.5 MB/s (216 GB per day), contact Support. We can recommend an optimal configuration.


3\. Configure your application or network device

You must configure each device to send logs to the correct port. Consult the documentation for your application, or device.

To send logs from a different Linux host, you may wish to use the popular `rsyslogd` utility, which has a
powerful configuration language. You can forward some or all logs. For example, suppose this plugin listens on TCP port 601, and you wish to use `rsyslogd` on the local host to import `authpriv` system logs. Add these lines to your `rsyslogd` configuration, typically found at `/etc/rsyslogd.conf`:

    # Send all authpriv messasges.
    authpriv.*                                              @@localhost:601

Make sure you place this line before any other filters that match the authpriv messages. The `@@` prefix
specifies TCP.

In Ubuntu, you must edit the file in `/etc/rsyslog.d/50-default.conf` to include the following line:

<pre><code>*.warn                         @&lt;ip of agent&gt;:514</code></pre>

Where, `<ip of agent>` is replaced with the IP address of the host running the Scalyr Agent. This will forward
all messages of `warning` severity level or higher to the Agent. You must execute
`sudo service rsyslog restart` for the changes to take affect.


4\. Save and confirm

Save the `agent.json` file. The Scalyr Agent will detect changes within 30 seconds. Wait a few minutes for the Agent to send data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log in to Scalyr and go to the [Logs](https://app.scalyr.com/logStart) overview page. The log file, which defaults to "agent_syslog.log", should show for each server running this plugin.

From Search view, query [monitor = 'syslog_monitor'](https://app.scalyr.com/events?filter=monitor+%3D+%27syslog_monitor%27). This will show all data collected by this plugin, across all servers.

    """
    # fmt: on

    def _initialize(self):
        if self._config.get("mode") == "docker" and not docker_module_available:
            raise BadMonitorConfiguration(
                "Failing syslog monitor since docker mode was requested but the docker module could not be imported. "
                "This may be due to not including the docker library when building container image.",
                "mode",
            )

        if self._config.get("message_log_template") and syslogmp is None:
            raise BadMonitorConfiguration(
                "Failing syslog monitor because its dependency (syslogmp module) could not be imported. "
                "The syslogmp module requires Python >= 3.6",
                "message_log_template",
            )

        # the main server
        self.__server = None

        # any extra servers if we are listening for multiple protocols
        self.__extra_servers = []

        # build list of protocols and ports from the protocol option
        self.__server_list = self.__build_server_list(self._config.get("protocols"))

        # our disk logger and handler
        self.__disk_logger = None
        self.__log_handler = None

        # whether or not to accept only connections created on this localhost.
        self.__accept_remote_connections = self._config.get("accept_remote_connections")

        self.__server_host = None
        self.__log_path = ""
        if self._global_config:
            self.__log_path = self._global_config.agent_log_path

            if self._global_config.server_attributes:
                if "serverHost" in self._global_config.server_attributes:
                    self.__server_host = self._global_config.server_attributes[
                        "serverHost"
                    ]

        self.__log_watcher = None
        self.__module = None

        # configure the logger and path
        self.__message_log = self._config.get("message_log")

        self.log_config = {
            "parser": self._config.get("parser"),
            "path": self.__message_log,
        }

        self.__flush_delay = self._config.get("log_flush_delay")
        try:
            attributes = JsonObject({"monitor": "agentSyslog"})
            self.log_config["attributes"] = attributes
        except Exception:
            global_log.error("Error setting monitor attribute in SyslogMonitor")

        (
            default_rotation_count,
            default_max_bytes,
        ) = self._get_log_rotation_configuration()

        self.__max_log_size = self._config.get("max_log_size")
        if self.__max_log_size is None:
            self.__max_log_size = default_max_bytes

        self.__max_log_rotations = self._config.get("max_log_rotations")
        if self.__max_log_rotations is None:
            self.__max_log_rotations = default_rotation_count

        self._docker_options = None

    def __build_server_list(self, protocol_string):
        """Builds a list containing (protocol, port) tuples, based on a comma separated list
        of protocols and optional ports e.g. protocol[:port], protocol[:port]
        """

        # split out each protocol[:port]
        protocol_list = [p.strip().lower() for p in protocol_string.split(",")]

        if len(protocol_list) == 0:
            raise Exception(
                "Invalid config state for Syslog Monitor. " "No protocols specified"
            )

        default_ports = {
            "tcp": 601,
            "udp": 514,
        }

        server_list = []

        # regular expression matching protocol:port
        port_re = re.compile(r"^(tcp|udp):(\d+)$")
        for p in protocol_list:

            # protocol defaults to the full p for when match fails
            protocol = p
            port = 0

            m = port_re.match(p)
            if m:
                protocol = m.group(1)
                port = int(m.group(2))

            if protocol in default_ports:
                # get the default port for this protocol if none was specified
                if port == 0:
                    port = default_ports[protocol]
            else:
                raise Exception(
                    "Unknown value '%s' specified for SyslogServer 'protocol'."
                    % protocol
                )

            # only allow ports between 1 and 65535
            if port < 1 or port > 65535:
                raise Exception(
                    "Port values must be in the range 1-65535.  Current value: %d."
                    % port
                )

            server_list.append((protocol, port))

        # return a list with duplicates removed
        return list(set(server_list))

    def open_metric_log(self):
        """Override open_metric_log to prevent a metric log from being created for the Syslog Monitor
        and instead create our own logger which will log raw messages out to disk.
        """
        name = __name__ + "-" + self.__message_log + ".syslog"
        self.__disk_logger = logging.getLogger(name)

        # assume successful for when the logger handler has already been created
        success = True

        # only configure once -- assumes all configuration happens on the same thread
        if len(self.__disk_logger.handlers) == 0:
            # logger handler hasn't been created yet, so assume unsuccssful
            success = False
            try:
                self.__log_handler = AutoFlushingRotatingFileHandler(
                    filename=self.log_config["path"],
                    maxBytes=self.__max_log_size,
                    backupCount=self.__max_log_rotations,
                    flushDelay=self.__flush_delay,
                )

                formatter = logging.Formatter()
                self.__log_handler.setFormatter(formatter)
                self.__disk_logger.addHandler(self.__log_handler)
                self.__disk_logger.setLevel(logging.INFO)
                self.__disk_logger.propagate = False
                success = True
            except Exception as e:
                global_log.error(
                    "Unable to open SyslogMonitor log file: %s" % six.text_type(e)
                )

        return success

    def close_metric_log(self):
        if self.__log_handler:
            self.__disk_logger.removeHandler(self.__log_handler)
            self.__log_handler.close()

    def set_log_watcher(self, log_watcher):
        self.__log_watcher = log_watcher

    def __get_log_watcher(self):
        return (self.__log_watcher, self)

    def config_from_monitors(self, manager):
        """
        Called directly before running the `run` method.
        This method passes in the module manager object to a monitor before
        it runs so that the monitor can query the monitor about other monitors
        that exist.
        In order to prevent circular references, callees should *not* retain a
        reference to the manager object
        """

        # if we are using docker, then see if the docker monitor is also running
        # and if so, read the config options from there
        monitor = None
        if self._config.get("mode") == "docker":
            monitor = manager.find_monitor(
                "scalyr_agent.builtin_monitors.docker_monitor"
            )

        # if the docker monitor doesn't exist don't do anything
        if monitor is None:
            return

        self._docker_options = DockerOptions()
        global_log.info(
            "About to configure options from monitor: %s", monitor.module_name
        )
        self._docker_options.configure_from_monitor(monitor)

    def run(self):
        def line_reporter(num_lines):
            self.increment_counter(reported_lines=num_lines)

        rotate_options = self._get_log_rotation_configuration()
        try:
            if self.__disk_logger is None:
                raise Exception("No disk logger available for Syslog Monitor")

            # create the main server from the first item in the server list
            protocol = self.__server_list[0]
            self.__server = SyslogServer(
                protocol[0],
                protocol[1],
                self.__disk_logger,
                self._config,
                self._global_config,
                line_reporter,
                accept_remote=self.__accept_remote_connections,
                server_host=self.__server_host,
                log_path=self.__log_path,
                get_log_watcher=self.__get_log_watcher,
                rotate_options=rotate_options,
                docker_options=self._docker_options,
            )

            # iterate over the remaining items creating servers for each protocol
            for p in self.__server_list[1:]:
                server = SyslogServer(
                    p[0],
                    p[1],
                    self.__disk_logger,
                    self._config,
                    self._global_config,
                    line_reporter,
                    accept_remote=self.__accept_remote_connections,
                    server_host=self.__server_host,
                    log_path=self.__log_path,
                    get_log_watcher=self.__get_log_watcher,
                    rotate_options=rotate_options,
                    docker_options=self._docker_options,
                )
                self.__extra_servers.append(server)

            # start any extra servers in their own threads
            for server in self.__extra_servers:
                server.start_threaded(self._run_state)

            # start the main server
            self.__server.start(self._run_state)

        except Exception:
            global_log.exception(
                "Monitor died due to exception:", error_code="failedMonitor"
            )
            raise

    def stop(self, wait_on_join=True, join_timeout=5):

        # stop the main server
        ScalyrMonitor.stop(self, wait_on_join=wait_on_join, join_timeout=join_timeout)

        # stop any extra servers
        for server in self.__extra_servers:
            server.stop(wait_on_join, join_timeout)
