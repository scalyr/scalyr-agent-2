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
        format=f"[%(levelname)s][%(module)s:%(lineno)s]{in_docker_field_format} %(message)s"
    )


def output_suppressed_subprocess_check_call(
        *args,
        debug: bool = False,
        show_on_error_lines_number: int = 20,
        **kwargs
):
    """

    Alternative implementation of the 'subprocess.check_call' function without output to reduce the logging noise.

    :param args: Subprocess args.
    :param debug: If True, then output is enabled.
    :param show_on_error_lines_number: # Number of last lines to show if error has occurred.
    :param kwargs: Subprocess kwargs.
    """

    # If debug, then just run the normal check_call.
    if debug:
        return subprocess.check_call(
            *args, **kwargs
        )

    # Override outputs. Redirect stderr to stdout.
    kwargs.pop("stdout", None)
    kwargs.pop("stderr", None)

    try:
        # Run check_output instead to suppress standard output.
        subprocess.check_output(*args, stderr=subprocess.STDOUT, **kwargs)
    except subprocess.CalledProcessError as e:
        # Show last n lines on error.
        stdout_lines = e.stdout.decode().splitlines()
        lines_to_print = stdout_lines[-show_on_error_lines_number:]

        if lines_to_print:
            stdout_to_print = "\n".join(lines_to_print)
            print(stdout_to_print, file=sys.stderr)
        raise


def subprocess_command_run_with_log(func):
    """
    Wrapper for 'subprocess.check_call' and 'subprocess.check_output' function that also logs
    additional info when command is executed.
    :param func: Function to wrap.
    """
    def wrapper(*args, **kwargs) -> bytes:
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
        logging.info(
            f"RUN COMMAND #{number}: '{cmd_str}'.",
            stacklevel=3
        )

        try:
            result = func(
                *args,
                **kwargs
            )
        except subprocess.CalledProcessError:
            logging.info(
                f"COMMAND #{number} FAILED.\n",
                stacklevel=3
            )
            raise
        else:
            logging.info(
                f"COMMAND #{number} ENDED.\n",
                stacklevel=3
            )
            return result

    return wrapper


check_call_with_log = subprocess_command_run_with_log(output_suppressed_subprocess_check_call)
check_output_with_log = subprocess_command_run_with_log(subprocess.check_output)