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

import logging
import os
from typing import Mapping

from agent_build.tools.steps_libs.subprocess_with_log import *
from agent_build.tools.steps_libs.container import *

# If this environment variable is set, then commands output is not suppressed.
DEBUG = bool(os.environ.get("AGENT_BUILD_DEBUG"))

# If this env. variable is set, then the code runs inside the docker.
IN_DOCKER = bool(os.environ.get("AGENT_BUILD_IN_DOCKER"))

# If this env. variable is set, than the code runs in CI/CD (e.g. Github actions)
IN_CICD = bool(os.environ.get("AGENT_BUILD_IN_CICD"))
IN_CICD = True


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
