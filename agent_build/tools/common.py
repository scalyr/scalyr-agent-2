# Copyright 2014-2021 Scalyr Inc.
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


import subprocess
import sys

# Number of files before the output of the subprocess.check_call command is suppressed.
MAX_OUTPUT_LINES = 100

# Number of last lines to show if error has occurred.
MAX_ERROR_LINES = 20


_ORIGINAL_POPEN = subprocess.Popen


def output_suppressed_subprocess_check_call(*args, debug: bool = False, **kwargs):
    """
    A wrapper for the 'subprocess.check_call' function which suppress output if it too long.

    :param debug: If True, then just the output is not suppressed and normal 'check_output' is called.
    :param args: The same as for the 'subprocess.check_call'
    :param kwargs: The same as for the 'subprocess.check_call'
    """

    if debug:
        # do not suppress if debug.
        return subprocess.check_call(
            *args,
            **kwargs
        )

    kwargs.pop("stdout", None)
    kwargs.pop("stderr", None)

    process = subprocess.Popen(
        *args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kwargs
    )

    lines = []
    lines_printed = 0

    for line_bytes in process.stdout:
        line = line_bytes.decode().strip()
        lines.append(line)
        if len(lines) <= MAX_OUTPUT_LINES:
            print(line, file=sys.stderr)
            lines_printed += 1

            if len(lines) == MAX_OUTPUT_LINES:
                print(
                    "\n========================================================================\n"
                    "###### The output is to long. Use 'debug' option for full output. ######"
                    "\n========================================================================\n",
                    file=sys.stderr
                )

    process.wait()

    cmd_args = kwargs.get("args")
    if cmd_args is None:
        cmd_args = args[0]

    # Add last empty line so it can be easier to detect the end of the command output.
    lines.append("")

    if process.returncode != 0:
        # There is an error print last n lines.

        not_printed_lines = lines[lines_printed:]

        error_lines = not_printed_lines[-MAX_ERROR_LINES + 1:]

        if error_lines:
            stdout = "\n".join(error_lines)
            print(stdout, file=sys.stderr)

        raise subprocess.CalledProcessError(returncode=1, cmd=cmd_args)



