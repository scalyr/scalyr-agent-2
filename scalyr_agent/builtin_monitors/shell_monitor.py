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
#
# A ScalyrMonitor which executes a specified shell command and records the output.

from __future__ import absolute_import

import re
import sys
import time

from subprocess import PIPE, Popen

import six

from scalyr_agent import ScalyrMonitor, define_config_option, define_log_field

__monitor__ = __name__

define_config_option(
    __monitor__, "module", "Always `scalyr_agent.builtin_monitors.shell_monitor`"
)
define_config_option(
    __monitor__,
    "id",
    "An id, included with each event. Shows in the UI as a value for the `instance` field. "
    "Lets you distinguish between values recorded by multiple instances of this plugin "
    "(to run multiple shell commands). Each instance has a separate `{...}` stanza "
    "in the configuration file (`/etc/scalyr-agent-2/agent.json`).",
)
define_config_option(
    __monitor__, "command", "The shell command to execute.", required_option=True
)
define_config_option(
    __monitor__,
    "extract",
    'Optional (defaults to ""). '
    "A regular expression, applied to the command output. Lets you extract "
    "data of interest. Must include a matching group (i.e. a subexpression enclosed "
    "in parentheses). Only the content of the matching group is imported.",
    default="",
)
define_config_option(
    __monitor__,
    "log_all_lines",
    "Optional (defaults to `false`). If `true`, this plugin imports the full output of the "
    "command. If `false`, only the first line is imported.",
    default=False,
)
define_config_option(
    __monitor__,
    "max_characters",
    "Optional (defaults to 200). Maximum number of characters to import from the command's "
    "output. A value up to 10000 may be set, but we currently truncate all fields to "
    "3500 characters.",
    default=200,
    convert_to=int,
    min_value=0,
    max_value=10000,
)

define_log_field(__monitor__, "monitor", "Always `shell_monitor`.")
define_log_field(__monitor__, "metric", "Always `output`.")
define_log_field(
    __monitor__,
    "instance",
    "The `id` value from the configuration, for example `kernel-version`.",
)
define_log_field(
    __monitor__,
    "command",
    "The shell command, for example `uname -r`.",
)
define_log_field(
    __monitor__,
    "value",
    "The output of the shell command, for example `3.4.73-64.112.amzn1.x86_64`.",
)
define_log_field(
    __monitor__,
    "length",
    "Length of the output, for example `26`.",
)
define_log_field(
    __monitor__,
    "duration",
    "Seconds spent executing the command.",
)
define_log_field(
    __monitor__,
    "exit_code",
    "Exit status of the command. Zero is success. Non-zero is failure.",
)


# Pattern that matches the first line of a string
__first_line_pattern__ = re.compile("[^\r\n]+")


# ShellMonitor implementation
class ShellMonitor(ScalyrMonitor):
    # fmt: off
    r"""
# Shell Agent Plugin

Execute a shell command and import the output.

An [Agent Plugin](https://app.scalyr.com/help/scalyr-agent#plugins) is a component of the Scalyr Agent, enabling the collection of more data. The source code for each plugin is available on [Github](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/builtin_monitors).

You can import any information retrieved from a shell command. Commands execute as the same user as the Scalyr Agent.


## Installation

1\. Install the Scalyr Agent

If you haven't already, install the [Scalyr Agent](https://app.scalyr.com/help/welcome) on the host that will execute the shell command.


2\. Configure the Scalyr Agent

Open the Agent configuration file, located at `/etc/scalyr-agent-2/agent.json`.

Find the `monitors: [ ... ]` section and add a `{...}` stanza with the `module` property set for shell command:

    monitors: [
     {
       module:  "scalyr_agent.builtin_monitors.shell_monitor",
       id:      "kernel-version",
       command: "uname -r"
     }
    ]

The `command` property is the shell command you wish to execute. The `id` property lets you identify the command, and shows in the UI as a value for the `instance` field. This is especially useful if you are running multiple instances of this plugin, to import output from multiple shell commands. Add a separate `{...}` stanza for each command.

By default, only the first line of the command output is imported. Add and set `log_all_lines: true` to import all lines.

See [Configuration Options](#options) below for more properties you can add. You can set the number of characters to import, and you can apply a regular expression with a matching group, to extract data of interest from the output.


3\. Save and confirm

Save the `agent.json` file. The Agent will detect changes within 30 seconds. Wait a few minutes for the Agent to begin sending data.

You can check the [Agent Status](https://app.scalyr.com/help/scalyr-agent#agentStatus), which includes information about all running monitors.

Log into Scalyr. From Search view query [monitor = 'shell_monitor'](/events?filter=monitor%3D%27shell_monitor%27). This will show all data collected by this plugin, across all servers.

For help, contact Support.

    """
    # fmt: on

    def _initialize(self):
        # Fetch and validate our configuration options.
        self.command = self._config.get("command")
        self.max_characters = self._config.get("max_characters")
        self.log_all_lines = self._config.get("log_all_lines")

        extract_expression = self._config.get("extract")
        if extract_expression:
            self.extractor = re.compile(extract_expression)

            # Verify that the extract expression contains a matching group, i.e. a parenthesized clause.
            # We perform a quick-and-dirty test here, which will work for most regular expressions.
            # If we miss a bad expression, it will result in a stack trace being logged when the monitor
            # executes.
            if extract_expression.find("(") < 0:
                raise Exception(
                    "extract expression [%s] must contain a matching group"
                    % extract_expression
                )
        else:
            self.extractor = None

    def gather_sample(self):

        close_fds = True
        if sys.platform == "win32":
            # on windows we can't both redirect stdin, stdout and stderr AND close_fds
            # therefore we don't close fds for windows.
            close_fds = False

        # Run the command
        # NOTE: We intentionally use shell=True to allow users to define commands which are executed
        # under a shell.
        # There is no possibility for 3rd part a shell injection here since the command is
        # controlled by the end user.
        start_ts = int(time.time())

        command = self.command
        p = Popen(  # nosec
            command,
            shell=True,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            close_fds=close_fds,
        )
        (stdout_text, stderr_text) = p.communicate()
        end_ts = int(time.time())
        duration = end_ts - start_ts

        output = stderr_text
        if len(stderr_text) > 0 and len(stdout_text) > 0:
            output += b"\n"
        output += stdout_text

        output = six.ensure_text(output)

        # Apply any extraction pattern
        if self.extractor is not None:
            match = self.extractor.search(output)
            if match is not None:
                output = match.group(1)

        # Apply log_all_lines and max_characters, and record the result.
        if self.log_all_lines:
            s = output
        else:
            first_line = __first_line_pattern__.search(output)
            s = ""
            if first_line is not None:
                s = first_line.group().strip()

        if len(s) > self.max_characters:
            s = s[: self.max_characters] + "..."

        exit_code = p.returncode
        self._logger.emit_value(
            "output",
            s,
            extra_fields={
                "command": self.command,
                "length": len(output),
                "duration": duration,
                "exit_code": exit_code,
            },
        )
