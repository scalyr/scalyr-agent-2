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
import shlex
import logging

from agent_build.tools import common
from agent_build.tools import constants


_ORIGINAL_POPEN_CALL = subprocess.Popen
def subprocess_popen_with_log(*args, **kwargs):
    """
    Simple wrapper for the subprocess.Popen to spit an INFO message with command before start.
    :param args: The same as for the 'subprocess.Popen'
    :param kwargs: The same as for the 'subprocess.Popen'
    """

    # Make info message with all command line arguments.

    cmd_args = kwargs.get("args")
    if cmd_args is None:
        cmd_args = args[0]

    # Create command string.
    cmd_str = shlex.join(cmd_args)

    logging.info(f"RUN COMMAND: '{cmd_str}':\n")
    return _ORIGINAL_POPEN_CALL(
        *args,
        **kwargs
    )


# Replace original subprocess with its wrapper that logs additional information about running command.
subprocess.Popen = subprocess_popen_with_log
