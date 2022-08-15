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
import functools
import json
import sys
import subprocess
import shlex
import logging
import os
import pathlib as pl
from typing import List, Mapping, Dict

from agent_build.tools.steps_libs.container import *

# If this environment variable is set, then commands output is not suppressed.
DEBUG = bool(os.environ.get("AGENT_BUILD_DEBUG"))

# If this env. variable is set, then the code runs inside the docker.
IN_DOCKER = bool(os.environ.get("AGENT_BUILD_IN_DOCKER"))

# If this env. variable is set, than the code runs in CI/CD (e.g. Github actions)
IN_CICD = bool(os.environ.get("AGENT_BUILD_IN_CICD"))
IN_CICD = True

# A counter for all commands that have been executed since start of the program.
# Just for more informative logging.
_COMMAND_COUNTER = 0


def init_logging():
    """
    Init logging and defined additional logging fields to logger.
    """

    # If the code runs in docker, then add such field to the log message.
    in_docker_field_format = "[IN_DOCKER]" if IN_DOCKER else ""

    logging.basicConfig(
        level=logging.INFO,
        format=f"[%(levelname)s][%(module)s:%(lineno)s]{in_docker_field_format} %(message)s",
    )


# Make shlex.join for Python 3.7
if sys.version_info < (3, 8):

    def shlex_join(cmd: List):
        return " ".join(shlex.quote(arg) for arg in cmd)

else:
    shlex_join = shlex.join


COMMAND_MESSAGE_PADDING = " " * 23


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
            message = f"{description}\n" f"{COMMAND_MESSAGE_PADDING}{message}"
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


# Also create alternative version of subprocess functions that can log additional messages.
check_call_with_log = subprocess_command_run_with_log(subprocess.check_call)
check_output_with_log = subprocess_command_run_with_log(subprocess.check_output)

check_call_with_log_debug = subprocess_command_run_with_log(
    subprocess.check_call, debug=True
)
check_output_with_log_debug = subprocess_command_run_with_log(
    subprocess.check_output, debug=True
)


class UniqueDict(dict):
    """
    Simple dict subclass which raises error on attempt of adding existing key.
    Needed to keep tracking that
    """

    def __setitem__(self, key, value):
        if key in self:
            raise ValueError(f"Key '{key}' already exists.")

        super(UniqueDict, self).__setitem__(key, value)

    def update(self, m: Mapping, **kwargs) -> None:
        if isinstance(m, dict):
            m = m.items()
        for k, v in m:
            self[k] = v
