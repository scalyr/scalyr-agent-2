# Copyright 2022 Scalyr Inc.
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

"""
NOTE: This monitor is only used for testing purposes and is not to be used in production.

Agent monitor which scans for files which match the provided glob and creates symlink(s) for
each of the matching file to a new location using a specified file name.

For example, let's say we have the following files on disk:

    /tmp/openmetrics_monitor_file1.log
    /tmp/openmetrics_monitor_file2.log

And the following monitor config:

    input_path_glob: "/tmp/openmetrics_monitor_*.log"
    symlink_file_name_format: "worker-{index}s-{file_name}s"
    symlink_count: 2

In this case, this monitor would create the following symlinks when a file which matches
the input glob is found:

    /tmp/worker-0-openmetrics_monitor_file1.log
    /tmp/worker-0-openmetrics_monitor_file2.log
    /tmp/worker-1-openmetrics_monitor_file1.log
    /tmp/worker-1-openmetrics_monitor_file2.log

This would then allow us to configure to additional workers to ingest those files into different
accounts.

For example:

    {
      "path": "/tmp/worker-0-openmetrics_monitor_file*.log",
      "worker_id": "test_team_one",
      "copy_from_start": true,
   },
   {
      "path": "/tmp/worker-1-openmetrics_monitor_file*.log",
      "worker_id": "test_team_two",
      "copy_from_start": true,
   },

Keep in mind that we use a unique prefix and not suffix so we can still utilize agent glob matching
for files which are to be ingested - if we used a unique suffix, main worker would still ingest
the symlinked files because we can't exclude those files using the glob notation we support.
"""

import os
import os.path

from scalyr_agent import ScalyrMonitor
from scalyr_agent import define_config_option

from scalyr_agent.util import match_glob

__monitor__ = __name__

define_config_option(
    __monitor__,
    "module",
    "Always ``scalyr_agent.builtin_monitors.symlink_file_monitor``",
)

define_config_option(
    __monitor__,
    "id",
    "Included in each log message generated by this monitor, as a field named ``instance``. Allows "
    "you to distinguish between values recorded by different monitors.",
)

define_config_option(
    __monitor__,
    "input_path_glob",
    "Glob for the input files which this monitor will try to find.",
    default=False,
)

define_config_option(
    __monitor__,
    "symlink_file_name_format",
    "File name format to use for the created symlink files..",
    default=False,
)

define_config_option(
    __monitor__,
    "symlinks_count",
    "How many unique symlinks to create for the matched file.",
    default=1,
    convert_to=int,
    min_value=1,
    max_value=10,
)


class SymlinkMatchingFilesMonitor(ScalyrMonitor):
    def _initialize(self):
        self._input_path_glob = self._config.get("input_path_glob")
        self._symlink_file_name_format = self._config.get("symlink_file_name_format")
        self._symlinks_count = self._config.get("symlinks_count")

    def gather_sample(self):
        matching_input_file_paths = self.__find_matching_files()

        self._logger.debug(
            "Found %s matching files for the input glob %s"
            % (len(matching_input_file_paths), self._input_path_glob)
        )

        for file_path in matching_input_file_paths:
            self.__symlink_matching_file(file_path=file_path)

    def __find_matching_files(self):
        return match_glob(self._input_path_glob)

    def __symlink_matching_file(self, file_path):
        file_directory = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)

        for index in range(0, self._symlinks_count):
            symlink_destination_path = self._symlink_file_name_format.format(
                index=index, file_name=file_name
            )
            symlink_destination_path = os.path.join(
                file_directory, symlink_destination_path
            )

            if os.path.isfile(symlink_destination_path):
                # This symlink destination already exists, skip creation
                continue

            self._logger.debug(
                "Creating symlink: %s -> %s" % (file_path, symlink_destination_path)
            )
            os.symlink(file_path, symlink_destination_path)
