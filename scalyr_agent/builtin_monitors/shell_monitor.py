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

import re
import os

from scalyr_agent import ScalyrMonitor


# Pattern that matches the first line of a string
__first_line_pattern__ = re.compile('[^\r\n]+')


# ShellMonitor implementation
class ShellMonitor(ScalyrMonitor):
    """A Scalyr agent monitor which executes a specified shell command, and records the output.
    """

    def _initialize(self):
        # Fetch and validate our configuration options.
        self.command = self._config.get("command", required_field=True)
        self.max_characters = self._config.get("max_characters", default=200, convert_to=int, min_value=0,
                                               max_value=10000)
        self.log_all_lines = self._config.get("log_all_lines", default=False)

        extract_expression = self._config.get("extract", default="")
        if extract_expression:
            self.extractor = re.compile(extract_expression)
            
            # Verify that the extract expression contains a matching group, i.e. a parenthesized clause.
            # We perform a quick-and-dirty test here, which will work for most regular expressions.
            # If we miss a bad expression, it will result in a stack trace being logged when the monitor
            # executes.
            if extract_expression.find("(") < 0:
                raise Exception("extract expression [%s] must contain a matching group" % extract_expression)
        else:
            self.extractor = None

    def gather_sample(self):
        # Run the command
        command = self.command
        stdin, stdout, stderr = os.popen3(command)
        stdout_text = stdout.read()
        stderr_text = stderr.read()
        stdin.close()
        stdout.close()
        stderr.close()

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
            s = ''
            if first_line is not None:
                s = first_line.group().strip()

        if len(s) > self.max_characters:
            s = s[:self.max_characters] + "..."
        self._logger.emit_value('output', s, extra_fields={'command': self.command, 'length': len(output)})
