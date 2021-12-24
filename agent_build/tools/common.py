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
import sys
import subprocess
import shlex
import logging
import os

# If this environment variable is set, then commands output is not suppressed.
DEBUG = bool(os.environ.get("AGENT_BUILD_DEBUG"))

# If this env. variable is set, then the code runs inside the docker.
IN_DOCKER = bool(os.environ.get("AGENT_BUILD_IN_DOCKER"))

# If this env. variable is set, than the code runs in CI/CD (e.g. Github actions)
IN_CICD = bool(os.environ.get("AGENT_BUILD_IN_CICD"))

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


def subprocess_command_run_with_log(func):
    """
    Wrapper for 'subprocess.check_call' and 'subprocess.check_output' function that also logs
    additional info when command is executed.
    :param func: Function to wrap.
    """

    def wrapper(*args, **kwargs):

        global _COMMAND_COUNTER

        # Make info message with all command line arguments.
        cmd_args = kwargs.get("args")
        if cmd_args is None:
            cmd_args = args[0]
        if isinstance(cmd_args, list):
            # Create command string.
            cmd_str = shlex.join(cmd_args)
        else:
            cmd_str = cmd_args

        number = _COMMAND_COUNTER
        _COMMAND_COUNTER += 1
        logging.info(f" ### RUN COMMAND #{number}: '{cmd_str}'. ###", stacklevel=3)
        try:
            result = func(*args, **kwargs)
        except subprocess.CalledProcessError as e:
            logging.info(f" ### COMMAND #{number} FAILED. ###\n", stacklevel=3)
            raise e from None
        else:
            logging.info(f" ### COMMAND #{number} ENDED. ###\n", stacklevel=3)
            return result

    return wrapper


@subprocess_command_run_with_log
def run_command(*args, debug: bool = False, **kwargs):
    """
    Helper command that executes given commands. It combines subprocess' 'check_call' and 'check_output',
    so it print to standard output and also returns that output.
    :param args: The same as in the subprocess functions.
    :param debug: Print standard output if True.
    :param kwargs: The same as in the subprocess functions.
    :return:
    """

    # Make info message with all command line arguments.
    cmd_args = kwargs.get("args")
    if cmd_args is None:
        cmd_args = args[0]

    kwargs.pop("stdout", None)
    kwargs.pop("stderr", None)

    process = subprocess.Popen(
        *args, stderr=subprocess.STDOUT, stdout=subprocess.PIPE, **kwargs
    )

    lines = []

    for line in process.stdout:
        lines.append(line)
        if debug:
            print(line.decode().strip(), file=sys.stderr)

    process.wait()

    stdout = b"\n".join(lines)
    if process.returncode != 0:
        if not debug:
            # Even if it's not debug print output on error.
            print(stdout.decode(), file=sys.stderr)
        raise subprocess.CalledProcessError(
            returncode=process.returncode, cmd=cmd_args, output=stdout
        )

    return stdout


# Also create alternative version of subprocess functions that can log additional messages.
check_call_with_log = subprocess_command_run_with_log(subprocess.check_call)
check_output_with_log = subprocess_command_run_with_log(subprocess.check_output)