# Copyright 2014-2022 Scalyr Inc.
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
import shlex
import logging
from typing import List

# Make shlex.join for Python 3.7
if sys.version_info < (3, 8):

    def shlex_join(cmd: List):
        return " ".join(shlex.quote(arg) for arg in cmd)

else:
    shlex_join = shlex.join

__all__ = [
    "check_call_with_log",
    "check_call_with_log_debug",
    "check_output_with_log",
    "check_output_with_log_debug",
]


_COMMAND_MESSAGE_PADDING = " " * 23
# A counter for all commands that have been executed since start of the program.
# Just for more informative logging.
_COMMAND_COUNTER = 0


def subprocess_command_run_with_log(func, debug: bool = False):
    """
    Wrapper for 'subprocess.check_call' and 'subprocess.check_output' function that also logs
    additional info when command is executed.
    :param func: Function to wrap.
    """

    def wrapper(*args, description: str = None, **kwargs):

        global _COMMAND_COUNTER

        # Make info message with all command line arguments.
        cmd_args = kwargs.get("args")
        if cmd_args is None:
            cmd_args = args[0]
        if isinstance(cmd_args, list):
            # Create command string.
            cmd_str = shlex_join(cmd_args)
        else:
            cmd_str = cmd_args

        number = _COMMAND_COUNTER
        _COMMAND_COUNTER += 1

        message = f"### RUN COMMAND #{number}: '{cmd_str}'. ###"

        if description:
            message = f"{description}\n" f"{_COMMAND_MESSAGE_PADDING}{message}"
        if debug:
            level_log = logging.debug
        else:
            level_log = logging.info

        level_log(message)
        try:
            result = func(*args, **kwargs)
        except subprocess.CalledProcessError as e:
            level_log(f" ### COMMAND #{number} FAILED. ###\n")
            raise e from None
        else:
            return result

    return wrapper


# Create alternative version of subprocess functions that can log additional messages.
check_call_with_log = subprocess_command_run_with_log(subprocess.check_call)
check_output_with_log = subprocess_command_run_with_log(subprocess.check_output)

# Also create debug versions of the same subprocess functions which debug level log messages.
check_call_with_log_debug = subprocess_command_run_with_log(
    subprocess.check_call, debug=True
)
check_output_with_log_debug = subprocess_command_run_with_log(
    subprocess.check_output, debug=True
)
