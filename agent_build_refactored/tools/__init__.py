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

import os
from typing import Mapping

from agent_build_refactored.tools.steps_libs.subprocess_with_log import (  # NOQA
    check_output_with_log,
    check_call_with_log,
    check_output_with_log_debug,
    check_call_with_log_debug,
)
from agent_build_refactored.tools.steps_libs.container import (  # NOQA
    LocalRegistryContainer,
    DockerContainer,
)

from agent_build_refactored.tools.steps_libs.build_logging import (  # NOQA
    init_logging,
)
from agent_build_refactored.tools.steps_libs.constants import IN_DOCKER  # NOQA


# If this environment variable is set, then commands output is not suppressed.
DEBUG = bool(os.environ.get("AGENT_BUILD_DEBUG"))

# If this env. variable is set, than the code runs in CI/CD (e.g. Github actions)
IN_CICD = bool(os.environ.get("AGENT_BUILD_IN_CICD"))


class UniqueDict(dict):
    """
    Simple dict subclass which raises error on attempt of adding existing key.
    Needed to keep tracking unique Runners.
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
