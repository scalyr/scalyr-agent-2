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


import abc
import os
import pathlib as pl
import hashlib
import shutil
import tempfile
import logging
from typing import List

from agent_build.tools import constants

LOG = logging.getLogger(__name__)


class FilesChecksumTracker:
    """
    This mixin class allows to define some set of files and then call a custom
        function in the environment, where only those files are available.

    For example, it is used in our 'DeploymentStep' class to be sure that script that runs by step could only
        access files that are used in the step checksum calculation to keep cache keys valid and up to date if new
        files are added.
    """

    def __init__(self):

        # All final file paths to track.
        self._original_files = []

        # Resolve file globs to get all files to track.
        for file_glob in self._tracked_file_globs:
            path = pl.Path(file_glob)

            if path.is_absolute():
                raise ValueError(
                    f"File '{path}' can not be absolute. Class: {type(self)}"
                )

            found = list(constants.SOURCE_ROOT.glob(str(file_glob)))

            self._original_files.extend(found)

        self._original_files = sorted(list(set(self._original_files)))

        # Create temp directory to store only tracked files.
        self._isolated_source_tmp_dir = tempfile.TemporaryDirectory(
            prefix="scalyr-agent-build-checksum-isolated-root-"
        )
        self._isolated_source_root_path = pl.Path(self._isolated_source_tmp_dir.name)

    @property
    @abc.abstractmethod
    def _tracked_file_globs(self) -> List[pl.Path]:
        """
        The list of all files to be tracked.
        """
        pass

    def _get_files_checksum(self, additional_seed: str = None) -> str:
        """
        The checksum of the step. It is based on content of the used files.
        :param additional_seed: Additional data to add in checksum calculation.
        """

        # Calculate the sha256 for each file's content, filename and permissions.
        sha256 = hashlib.sha256()
        for file_path in self._original_files:
            LOG.debug(f"Adding file {file_path} for checksum calculation")
            sha256.update(str(file_path.relative_to(constants.SOURCE_ROOT)).encode())
            sha256.update(file_path.read_bytes())

        if additional_seed:
            sha256.update(additional_seed)

        return sha256.hexdigest()

    def _run_function_in_isolated_source_directory(self, function):
        """
        Create a separate isolated directory with only files that are tracked, and run given function.
            Before running the function the current working directory is changed to an isolated directory, so the given
            function can only use them instead of real files.
        :param function: Function to call.
        """

        # Copy all tracked files to new isolated directory.
        for file_path in self._original_files:
            dest_path = self._isolated_source_root_path / file_path.parent.relative_to(
                constants.SOURCE_ROOT
            )
            dest_path.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest_path)

        # Save original cwd.
        original_cwd = pl.Path(os.getcwd())

        os.chdir(self._isolated_source_root_path)
        try:
            return function()
        except Exception as e:

            globs = [str(g) for g in self._tracked_file_globs]
            LOG.error(
                f"'{type(self).__name__}' has failed. "
                "HINT: Make sure that you have specified all files. "
                f"For now, tracked files are: {globs}"
            )
            raise e from None
        finally:
            os.chdir(original_cwd)
