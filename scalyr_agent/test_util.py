# Copyright 2019 Scalyr Inc.
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
#
#
# author: Edward Chee <echee@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import
from scalyr_agent import compat

__author__ = "echee@scalyr.com"

import re
import atexit
import logging
import os
import shutil
import tempfile
import threading
from io import open

import scalyr_agent.util as scalyr_util

from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import DefaultPaths
from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.scalyr_logging import AgentLogger


class ScalyrTestUtils(object):
    @staticmethod
    def create_configuration(extra_toplevel_config=None):
        """Creates a blank configuration file with default values. Optionally overwrites top-level key/values.
        Sets api_key to 'fake' unless defined in extra_toplevel_config

        @param extra_toplevel_config: Dict of top-level key/value objects to overwrite.
        @return: The configuration object
        @rtype: Configuration
        """
        config_dir = tempfile.mkdtemp()
        config_file = os.path.join(config_dir, "agentConfig.json")
        config_fragments_dir = os.path.join(config_dir, "configs.d")
        os.makedirs(config_fragments_dir)

        toplevel_config = {"api_key": "fake"}
        if extra_toplevel_config:
            toplevel_config.update(extra_toplevel_config)

        fp = open(config_file, "w")
        fp.write(scalyr_util.json_encode(toplevel_config))
        fp.close()

        default_paths = DefaultPaths(
            "/var/log/scalyr-agent-2",
            "/etc/scalyr-agent-2/agent.json",
            "/var/lib/scalyr-agent-2",
        )

        config = Configuration(config_file, default_paths, None)
        config.parse()

        # we need to delete the config dir when done
        atexit.register(shutil.rmtree, config_dir)

        return config

    @staticmethod
    def create_test_monitors_manager(
        config_monitors=None,
        platform_monitors=None,
        extra_toplevel_config=None,
        null_logger=False,
        fake_clock=False,
    ):
        """Create a test MonitorsManager

        @param config_monitors: config monitors
        @param platform_monitors: platform monitors
        @param extra_toplevel_config: dict of extra top-level key value objects
        @param null_logger: If True, set all monitors to log to Nullhandler
        @param fake_clock: If non-null, the manager and all it's monitors' _run_state's will use the provided fake_clock
        """
        monitors_json_array = []
        if config_monitors:
            for entry in config_monitors:
                monitors_json_array.append(entry)

        extras = {"monitors": monitors_json_array}
        if extra_toplevel_config:
            extras.update(extra_toplevel_config)

        config = ScalyrTestUtils.create_configuration(extra_toplevel_config=extras)
        config.parse()

        if not platform_monitors:
            platform_monitors = []
        # noinspection PyTypeChecker
        test_manager = MonitorsManager(config, FakePlatform(platform_monitors))

        if null_logger:
            # Override Agent Logger to prevent writing to disk
            for monitor in test_manager.monitors:
                monitor._logger = FakeAgentLogger("fake_agent_logger")

        if fake_clock:
            for monitor in test_manager.monitors + [test_manager]:
                monitor._run_state = scalyr_util.RunState(fake_clock=fake_clock)

        # AGENT-113 set all monitors and the monitors_manager threads to daemon to eliminate occasionally hanging tests
        test_manager.setDaemon(True)
        for monitor in test_manager.monitors:
            if isinstance(monitor, threading.Thread):
                monitor.setDaemon(True)

        return test_manager, config


class NullHandler(logging.Handler):
    def emit(self, record):
        pass


class FakeAgentLogger(AgentLogger, object):
    def __init__(self, name):
        super(FakeAgentLogger, self).__init__(name)
        if not len(self.handlers):
            self.addHandler(NullHandler())


class FakePlatform(object):
    """Fake implementation of PlatformController.

    Only implements the one method required for testing MonitorsManager.
    """

    def __init__(self, default_monitors):
        self.__monitors = default_monitors

    def get_default_monitors(self, _):
        return self.__monitors


def parse_scalyr_request(payload):
    """Parses a payload encoded with the Scalyr-specific JSON optimizations. The only place these optimizations
    are used are creating `AddEvent` requests.

    NOTE:  This method is very fragile and just does enough conversion to support the tests.  It could lead to
    erroneous results if patterns like "`s" and colons are used in strings content.  It is also not optimized
    for performance.

    :param payload: The request payload
    :type payload: bytes
    :return: The parsed request body
    :rtype: dict
    """
    # Our general strategy is to rewrite the payload to be standard JSON and then use the
    # standard JSON libraries to parse it.  There are two main optimizations we need to undo
    # here: length-prefixed strings and not using quotes around key names in JSON objects.

    # First, look for the length-prefixed strings.  These are marked by "`sXXXX" where XXXX is a four
    # byte integer holding the number of bytes in the string.  This precedes the string.  So we find
    # all of those and replace them with quotes.  We also have to escape the string.
    # NOTE: It is very important all of our regex work against byte strings because our input is in bytes.
    length_prefix_re = re.compile(b"`s(....)", re.DOTALL)

    # Accumulate the rewrite of `payload` here.  We will eventually parse this as standard JSON.
    rewritten_payload = b""
    # The index of `payload` up to which we have processed (copied into `rewritten_payload`).
    last_processed_index = -1

    for x in length_prefix_re.finditer(payload):
        # First add in the bytes between the last processed and the start of this match.
        rewritten_payload += payload[last_processed_index + 1 : x.start(0)]
        # Read the 4 bytes that describe the length, which is stored in regex group 1.
        # 2->TODO struct.pack|unpack in python < 2.7.7 does not allow unicode format string.
        length = compat.struct_unpack_unicode(">i", x.group(1))[0]
        # Grab the string content as raw bytes.
        raw_string = payload[x.end(1) : x.end(1) + length]
        text_string = raw_string.decode("utf-8")
        rewritten_payload += scalyr_util.json_encode(text_string, binary=True)
        last_processed_index = x.end(1) + length - 1
    rewritten_payload += payload[last_processed_index + 1 : len(payload)]

    # Now convert all places where we do not have quotes around key names to have quotes.
    # This is pretty fragile.. we look for anything like
    #      foo:
    #  and convert it to
    #      "foo":
    rewritten_payload = re.sub(b"([\\w\\-]+):", b'"\\1":', rewritten_payload)

    # NOTE: Special case for Windows where path is C:\ which we don't want to convert
    rewritten_payload = rewritten_payload.replace(b'"C":\\', b"C:\\")

    return scalyr_util.json_decode(rewritten_payload.decode("utf-8"))
