# Copyright 2014 Scalyr Inc.
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
# author:  Imron Alston <imron@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

from scalyr_agent import compat

__author__ = "imron@scalyr.com"

import errno
import glob
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
from string import Template
from io import open

import six
from six.moves import range
import six.moves.socketserver

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
    "Always ``scalyr_agent.builtin_monitors.syslog_monitor``",
    convert_to=six.text_type,
    required_option=True,
)
define_config_option(
    __monitor__,
    "protocols",
    "Optional (defaults to ``tcp:601``). Lists the protocols and ports on which the agent will accept "
    "messages. You can include one or more entries, separated by commas. Each entry must be of the "
    "form ``tcp:NNN`` or ``udp:NNN``. Port numbers are optional, defaulting to 601 for TCP and 514 "
    "for UDP",
    convert_to=six.text_type,
    default="tcp",
)

define_config_option(
    __monitor__,
    "accept_remote_connections",
    "Optional (defaults to false). If true, the plugin will accept network connections from any host; "
    "otherwise, it will only accept connections from localhost.",
    default=False,
    convert_to=bool,
)

define_config_option(
    __monitor__,
    "message_log",
    "Optional (defaults to ``agent_syslog.log``). Specifies the file name under which syslog messages "
    "are stored. The file will be placed in the default Scalyr log directory, unless it is an "
    "absolute path",
    convert_to=six.text_type,
    default="agent_syslog.log",
)

define_config_option(
    __monitor__,
    "parser",
    "Optional (defaults to ``agentSyslog``). Defines the parser name associated with the log file",
    convert_to=six.text_type,
    default="agentSyslog",
)

define_config_option(
    __monitor__,
    "tcp_buffer_size",
    "Optional (defaults to 8K).  The maximum buffer size for a single TCP syslog message.  "
    "Note: RFC 5425 (syslog over TCP/TLS) says syslog receivers MUST be able to support messages at least 2048 bytes long, and recommends they SHOULD "
    "support messages up to 8192 bytes long.",
    default=8192,
    min_value=2048,
    max_value=65536 * 1024,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "max_log_size",
    "Optional (defaults to None). How large the log file will grow before it is rotated. If None, then the "
    "default value will be taken from the monitor level or the global level log_rotation_max_bytes config option.  Set to zero "
    "for infinite size. Note that rotation is not visible in Scalyr; it is only relevant for managing "
    "disk space on the host running the agent. However, a very small limit could cause logs to be "
    "dropped if there is a temporary network outage and the log overflows before it can be sent to "
    "Scalyr",
    convert_to=int,
    default=None,
)

define_config_option(
    __monitor__,
    "max_log_rotations",
    "Optional (defaults to None). The maximum number of log rotations before older log files are "
    "deleted. If None, then the value is taken from the monitor level or the global level log_rotation_backup_count option. "
    "Set to zero for infinite rotations.",
    convert_to=int,
    default=None,
)

define_config_option(
    __monitor__,
    "log_flush_delay",
    "Optional (defaults to 1.0). The time to wait in seconds between flushing the log file containing "
    "the syslog messages.",
    convert_to=float,
    default=1.0,
)

define_config_option(
    __monitor__,
    "mode",
    'Optional (defaults to "syslog"). If set to "docker", the plugin will enable extra functionality '
    "to properly receive log lines sent via the `docker_monitor`.  In particular, the plugin will "
    "check for container ids in the tags of the incoming lines and create log files based on their "
    "container names.",
    default="syslog",
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "docker_regex",
    "Regular expression for parsing out docker logs from a syslog message when the tag sent to syslog "
    "only has the container id.  If a message matches this regex then everything *after* "
    "the full matching expression will be logged to a file called docker-<container-name>.log",
    convert_to=six.text_type,
    default=r"^.*([a-z0-9]{12})\[\d+\]: ?",
)

define_config_option(
    __monitor__,
    "docker_regex_full",
    "Regular expression for parsing out docker logs from a syslog message when the tag sent to syslog "
    "included both the container name and id.  If a message matches this regex then everything *after* "
    "the full matching expression will be logged to a file called docker-<container-name>.log",
    convert_to=six.text_type,
    default=r"^.*([^/]+)/([^[]+)\[\d+\]: ?",
)

define_config_option(
    __monitor__,
    "docker_expire_log",
    "Optional (defaults to 300).  The number of seconds of inactivity from a specific container before "
    "the log file is removed.  The log will be created again if a new message comes in from the container",
    default=300,
    convert_to=int,
)

define_config_option(
    __monitor__,
    "docker_accept_ips",
    "Optional.  A list of ip addresses to accept connections from if being run in a docker container. "
    "Defaults to a list with the ip address of the default docker bridge gateway. "
    "If accept_remote_connections is true, this option does nothing.",
)

define_config_option(
    __monitor__,
    "docker_api_socket",
    "Optional (defaults to /var/scalyr/docker.sock). Defines the unix socket used to communicate with "
    "the docker API. This is only used when `mode` is set to `docker` to look up container "
    "names by their ids.  WARNING, you must also set the `api_socket` configuration option in the "
    "docker monitor to this same value.\n"
    "Note:  You need to map the host's /run/docker.sock to the same value as specified here, using "
    "the -v parameter, e.g.\n"
    "\tdocker run -v /run/docker.sock:/var/scalyr/docker.sock ...",
    convert_to=six.text_type,
    default="/var/scalyr/docker.sock",
)

define_config_option(
    __monitor__,
    "docker_api_version",
    "Optional (defaults to 'auto'). The version of the Docker API to use when communicating to "
    "docker.  WARNING, you must also set the `docker_api_version` configuration option in the docker "
    "monitor to this same value.",
    convert_to=six.text_type,
    default="auto",
)

define_config_option(
    __monitor__,
    "docker_logfile_template",
    "Optional (defaults to 'containers/${CNAME}.log'). The template used to create the log "
    "file paths for save docker logs sent by other containers via syslog.  The variables $CNAME and "
    "$CID will be substituted with the name and id of the container that is emitting the logs.  If "
    "the path is not absolute, then it is assumed to be relative to the main Scalyr Agent log "
    "directory.",
    convert_to=six.text_type,
    default="containers/${CNAME}.log",
)

define_config_option(
    __monitor__,
    "docker_cid_cache_lifetime_secs",
    "Optional (defaults to 300). Controls the docker id to container name cache expiration.  After "
    "this number of seconds of inactivity, the cache entry will be evicted.",
    convert_to=float,
    default=300.0,
)

define_config_option(
    __monitor__,
    "docker_cid_clean_time_secs",
    "Optional (defaults to 5.0). The number seconds to wait between cleaning the docker id to "
    "container name cache.",
    convert_to=float,
    default=5.0,
)

define_config_option(
    __monitor__,
    "docker_use_daemon_to_resolve",
    "Optional (defaults to True). If True, will use the Docker daemon (via the docker_api_socket to "
    "resolve container ids to container names.  If you set this to False, you must be sure to add the "
    '--log-opt tag="/{{.Name}}/{{.ID}}" to your running containers to pass the container name in the '
    "log messages.",
    convert_to=bool,
    default=True,
)

define_config_option(
    __monitor__,
    "docker_check_for_unused_logs_mins",
    "Optional (defaults to 60). The number of minutes to wait between checking to see if there are any "
    "log files matchings the docker_logfile_template that haven't been written to for a while and can "
    "be deleted",
    convert_to=int,
    default=60,
)

define_config_option(
    __monitor__,
    "docker_delete_unused_logs_hours",
    "Optional (defaults to 24). The number of hours to wait before deleting any "
    "log files matchings the docker_logfile_template",
    convert_to=int,
    default=24,
)

define_config_option(
    __monitor__,
    "docker_check_rotated_timestamps",
    "Optional (defaults to True). If True, will check timestamps of all file rotations to see if they "
    "should be individually deleted based on the the log deletion configuration options. "
    "If False, only the file modification time of the main log file is checked, and the rotated files "
    "will only be deleted when the main log file is deleted.",
    convert_to=bool,
    default=True,
)


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
        data = six.ensure_text(self.request[0].strip())
        self.server.syslog_handler.handle(data)


class SyslogRequestParser(object):
    def __init__(self, socket, max_buffer_size):
        self._socket = socket
        if socket:
            self._socket.setblocking(False)
        self._remaining = None
        self._max_buffer_size = max_buffer_size
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

                # if the remaining bytes exceed the maximum buffer size, issue a warning
                # and dump existing contents to the handler
                if size - self._offset >= self._max_buffer_size:
                    global_log.warning(
                        "Syslog frame exceeded maximum buffer size",
                        limit_once_per_x_secs=300,
                        limit_key="syslog-max-buffer-exceeded",
                    )
                    # skip invalid bytes which can appear because of the buffer overflow.
                    frame_data = six.ensure_text(self._remaining, errors="ignore")

                    handle_frame(frame_data)
                    frames_handled += 1
                    # add a space to ensure the next frame won't start with a number
                    # and be incorrectly interpreted as a framed message
                    self._remaining = b" "
                    self._offset = 0

                break

            # output the frame
            frame_length = frame_end - self._offset

            frame_data = six.ensure_text(
                self._remaining[self._offset : frame_end].strip()
            )
            handle_frame(frame_data)
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


class SyslogTCPHandler(six.moves.socketserver.BaseRequestHandler):
    """Class that reads data from a TCP request and passes it to
    a protocol neutral handler
    """

    def handle(self):
        try:
            request_stream = SyslogRequestParser(
                self.request, self.server.tcp_buffer_size
            )
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "SyslogTCPHandler.handle - created request_stream. Thread: %d",
                threading.current_thread().ident,
            )
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
    """Class that creates a UDP SocketServer on a specified port
    """

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
    """Class that creates a TCP SocketServer on a specified port
    """

    def __init__(self, port, tcp_buffer_size, bind_address, verifier):

        self.__verifier = verifier
        address = (bind_address, port)
        global_log.log(
            scalyr_logging.DEBUG_LEVEL_1,
            "TCP Server: binding socket to %s" % six.text_type(address),
        )

        self.allow_reuse_address = True
        self.__run_state = None
        self.tcp_buffer_size = tcp_buffer_size
        six.moves.socketserver.TCPServer.__init__(self, address, SyslogTCPHandler)

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
    ):
        self._check_interval = check_interval_mins * 60
        self._delete_interval = delete_interval_hours * 60 * 60
        self._check_rotated_timestamps = check_rotated_timestamps
        self._max_log_rotations = max_log_rotations
        self._log_glob = os.path.join(
            log_path, log_file_template.safe_substitute(CID="*", CNAME="*")
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
        """create our own rotating logger which will log raw messages out to disk.
        """
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

    def handle(self, data):  # type: (six.text_type) -> None
        """
        Feed syslog messages to the appropriate loggers.
        """

        # one more time ensure that we don't have binary string.
        data = six.ensure_text(data)

        if self.__docker_logging:
            self.__handle_docker_logs(data)
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
                global_log.log(scalyr_logging.DEBUG_LEVEL_2, "Starting TCP Server")
                server = SyslogTCPServer(
                    port,
                    config.get("tcp_buffer_size"),
                    bind_address=bind_address,
                    verifier=verifier,
                )
            elif protocol == "udp":
                global_log.log(scalyr_logging.DEBUG_LEVEL_2, "Starting UDP Server")
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
    """
# Syslog Monitor

The Syslog monitor allows the Scalyr Agent to act as a syslog server, proxying logs from any application or device
that supports syslog. It can recieve log messages via the syslog TCP or syslog UDP protocols.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

## Sample Configuration

This sample will configure the agent to accept syslog messages on TCP port 601 and UDP port 514, from localhost
only:

    monitors: [
      {
        module:                    "scalyr_agent.builtin_monitors.syslog_monitor",
        protocols:                 "tcp:601, udp:514",
        accept_remote_connections: false
      }
    ]

You can specify any number of protocol/port combinations. Note that on Linux, to use port numbers 1024 or lower,
the agent must be running as root.

You may wish to accept syslog connections from other devices on the network, such as a firewall or router which
exports logs via syslog. Set ``accept_remote_connections`` to true to allow this.

Additional options are documented in the Configuration Reference section, below.

## Log files and parsers

By default, all syslog messages are written to a single log file, named ``agentSyslog.log``. You can use the
``message_log`` option to specify a different file name (see Configuration Reference).

If you'd like to send messages from different devices to different log files, you can include multiple syslog_monitor
stanzas in your configuration file. Specify a different ``message_log`` for each monitor, and have each listen on a
different port number. Then configure each device to send to the appropriate port.

syslog_monitor logs use a parser named ``agentSyslog``. To set up parsing for your syslog messages, go to the
[Parser Setup Page](/parsers?parser=agentSyslog) and click {{menuRef:Leave it to Us}} or
{{menuRef:Build Parser By Hand}}. If you are using multiple syslog_monitor stanzas, you can specify a different
parser for each one, using the ``parser`` option.

## Sending messages via syslog

To send messages to the Scalyr Agent using the syslog protocol, you must configure your application or network
device. The documentation for your application or device should include instructions. We'll be happy to help out;
please drop us a line at [support@scalyr.com](mailto:support@scalyr.com).

### Rsyslogd

To send messages from another Linux host, you may wish to use the popular ``rsyslogd`` utility. rsyslogd has a
powerful configuration language, and can be used to forward all logs or only a selected set of logs.

Here is a simple example. Suppose you have configured Scalyr's Syslog Monitor to listen on TCP port 601, and you
wish to use rsyslogd on the local host to upload system log messages of type ``authpriv``. You would add the following
lines to your rsyslogd configuration, which is typically in ``/etc/rsyslogd.conf``:

    # Send all authpriv messasges to Scalyr.
    authpriv.*                                              @@localhost:601

Make sure that this line comes before any other filters that could match the authpriv messages. The ``@@`` prefix
specifies TCP.

## Viewing Data

Messages uploaded by the Syslog Monitor will appear as an independent log file on the host where the agent is
running. You can find this log file in the [Overview](/logStart) page. By default, the file is named "agentSyslog.log".
    """

    def _initialize(self):
        if self._config.get("mode") == "docker" and not docker_module_available:
            raise BadMonitorConfiguration(
                "Failing syslog monitor since docker mode was requested but the docker module could not be imported. "
                "This may be due to not including the docker library when building container image.",
                "mode",
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
