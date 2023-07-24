# Copyright 2014-2023 Scalyr Inc.
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


import pathlib as pl
import shutil

from agent_build_refactored.utils.constants import AGENT_BUILD_OUTPUT_PATH

_PARENT_DIR = pl.Path(__file__).parent


class Builder:
    """
    Base class for any builder that produces some package or image with the Agent.
    """
    NAME: str = None

    def __init__(
        self
    ):
        self.name = self.__class__.NAME

        if self.root_dir.exists():
            shutil.rmtree(self.root_dir)

        self.root_dir.mkdir(parents=True)

        self.work_dir.mkdir(parents=True)
        self.result_dir.mkdir(parents=True)

    @property
    def root_dir(self) -> pl.Path:
        return AGENT_BUILD_OUTPUT_PATH / "builders" / self.name

    @property
    def result_dir(self) -> pl.Path:
        """Directory with builder results."""
        return self.root_dir / "result"

    @property
    def work_dir(self):
        """Directory with builder's intermediate results."""
        return self.root_dir / "work"
