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

from subprocess import PIPE, Popen

from scalyr_agent import ScalyrMonitor, define_config_option, define_log_field

__monitor__ = __name__

define_config_option(
    __monitor__, "module", "Always ``scalyr_agent.builtin_monitors.shell_monitor``"
)
define_config_option(
    __monitor__,
    "id",
    "Included in each log message generated by this monitor, as a field named ``instance``. Allows "
    "you to distinguish between values recorded by different monitors.",
)
define_config_option(
    __monitor__, "command", "The shell command to execute.", required_option=True
)
define_config_option(
    __monitor__,
    "extract",
    "Optional: a regular expression to apply to the command output. If defined, this expression must "
    "contain a matching group (i.e. a subexpression enclosed in parentheses). The monitor will record "
    "only the content of that matching group. This allows you to discard unnecessary portions of the "
    "command output and extract the information you need.",
    default="",
)
define_config_option(
    __monitor__,
    "log_all_lines",
    "Optional (defaults to false). If true, the monitor will record the entire command output; "
    "otherwise, it only records the first line.",
    default=False,
)
define_config_option(
    __monitor__,
    "max_characters",
    "Optional (defaults to 200). At most this many characters of output are recorded. You may specify "
    "a value up to 10000, but the Scalyr server currently truncates all fields to 3500 characters.",
    default=200,
    convert_to=int,
    min_value=0,
    max_value=10000,
)

define_log_field(__monitor__, "monitor", "Always ``shell_monitor``.")
define_log_field(
    __monitor__,
    "instance",
    "The ``id`` value from the monitor configuration, e.g. ``kernel-version``.",
)
define_log_field(
    __monitor__,
    "command",
    "The shell command for this plugin instance, e.g. ``uname -r``.",
)
define_log_field(__monitor__, "metric", "Always ``output``.")
define_log_field(
    __monitor__,
    "value",
    "The output of the shell command, e.g. ``3.4.73-64.112.amzn1.x86_64``.",
)


# Pattern that matches the first line of a string
__first_line_pattern__ = re.compile("[^\r\n]+")


# ShellMonitor implementation
class ShellMonitor(ScalyrMonitor):
    """A Scalyr agent monitor which executes a specified shell command, and records the output.
    """

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
        command = self.command
        p = Popen(
            command,
            shell=True,
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            close_fds=close_fds,
        )
        (stdout_text, stderr_text) = p.communicate()

        output = stderr_text
        if len(stderr_text) > 0 and len(stdout_text) > 0:
            output += "\n"
        output += stdout_text

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
        self._logger.emit_value(
            "output", s, extra_fields={"command": self.command, "length": len(output)}
        )
