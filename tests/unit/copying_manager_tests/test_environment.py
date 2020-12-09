# Copyright 2014-2020 Scalyr Inc.
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


from __future__ import unicode_literals
from __future__ import absolute_import

import json
import shutil
import tempfile

if False:
    from typing import Dict
    from typing import Optional
    from typing import List

from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import DefaultPaths

from scalyr_agent import scalyr_logging


import six
from six.moves import range

if six.PY3:
    import pathlib
else:
    import pathlib2 as pathlib  # pylint: disable=import-error


class TestableLogFile(object):
    """
    A testing purpose class that can perform useful operations on file.
    """

    __test__ = False

    def __init__(self, path):
        # type: (pathlib.Path) -> None

        self._path = pathlib.Path(path)

    def create(self):
        self.path.touch()

    def remove(self):
        self.path.unlink()

    def append_lines(self, *lines):  # type: (six.text_type) -> None
        """
        Append lines to the file.
        """
        # NOTE: We open file in binary mode, otherwise \n gets converted to \r\n on Windows on write
        with self.path.open("ab") as file:  # type: ignore
            for line in lines:
                file.write(line.encode("utf-8"))
                file.write(b"\n")

    @property
    def path(self):
        return self._path

    @property
    def str_path(self):
        return six.text_type(self.path)


class TestingConfiguration(Configuration):
    __test__ = False
    """
    A subclass of the original configuration class, that allow to assign additional options
    which will be useful for testing.
    """

    def __init__(self, *args, **kwargs):
        super(TestingConfiguration, self).__init__(*args, **kwargs)

        # Configure the ability of the testable copying manager to manually control its execution flow.
        self.disable_flow_control = False  # type: bool

        # Configure ApiKEyWorkerPool do not change the file path for the agent log for the workers.
        self.skip_agent_log_change = True


class TestEnvironBuilder(object):
    """
    Builder for tor the configuration object and agent essential environment.
    It allows to make additions which will be included to the resulting config file.
    """

    MAX_NON_GLOB_TEST_LOGS = 10

    def __init__(self, config_data=None, root_path=None):

        self._config_initial_data = config_data

        self._config = None  # type: Optional[TestingConfiguration]

        self._root_path = root_path

        self._current_test_log_files = []

    def __del__(self):
        self.clear()

    def init_agent_dirs(self):
        # if self._root_path is None:
        self._root_path = pathlib.Path(tempfile.mkdtemp(prefix="scalyr_testing"))
        self.agent_data_path.mkdir()
        self.agent_logs_path.mkdir()
        self.test_logs_dir.mkdir()
        self.glob_logs_dir.mkdir()
        self.non_glob_logs_dir.mkdir()

    def init_config(self, config_data=None):  # type: (Optional[Dict]) -> None
        """
        Create config object and apply all additions.
        :param config_data:
        :return:
        """

        default_paths = DefaultPaths(
            six.text_type(self.agent_logs_path),
            six.text_type(self.agent_config_path),
            six.text_type(self.agent_data_path),
        )

        if config_data is None:
            config_data = dict()

        if "api_key" not in config_data:
            config_data["api_key"] = "fake"

        if "debug_level" not in config_data:
            config_data["debug_level"] = 5

        logs = config_data.get("logs", list())

        logs.append({"path": six.text_type(self.glob_logs_dir / "log_*.log")})

        for i in range(self.MAX_NON_GLOB_TEST_LOGS):
            path = self.non_glob_logs_dir / ("log_%s.log" % i)
            logs.append({"path": six.text_type(path)})

        config_data["logs"] = logs

        self.agent_config_path.write_text(six.text_type(json.dumps(config_data)))

        config = TestingConfiguration(
            six.text_type(self.agent_config_path), default_paths, None
        )

        config.parse()

        self._config = config

    def recreate_files(self, files_number, path, file_name_format=None):
        # type: (int, pathlib.Path, six.text_type) -> List
        """
        Recreate *file_number* of files in the *path* directory with the *file_name_format* name format.
        :return:
        """

        if file_name_format is None:
            file_name_format = "log_{0}.log"

        self.remove_files(path)
        result = []
        for i in range(files_number):
            test_file = TestableLogFile(path / file_name_format.format(i))
            test_file.create()
            self._current_test_log_files.append(test_file)
            result.append(test_file)

        return result

    def remove_files(self, path):
        # type: (pathlib.Path) -> None
        for log_path in path.iterdir():
            log_path.unlink()

        self._current_test_log_files = []

    @property
    def config(self):  # type: () -> Configuration
        return self._config  # type: ignore

    def get_log_config(self, log_file):  # type: (TestableLogFile) -> Dict
        """
        Get log config from existing config.
        """

        log_config = self.config.parse_log_config({"path": log_file.str_path})

        return dict(log_config)

    def clear(self):
        scalyr_logging.close_handlers()

        if self._root_path.exists():
            shutil.rmtree(six.text_type(self._root_path))

    @property
    def root_path(self):
        return self._root_path

    @property
    def agent_data_path(self):
        return self.root_path / "data"

    @property
    def agent_logs_path(self):
        return self.root_path / "logs"

    @property
    def agent_config_path(self):
        return self.root_path / "agent.json"

    @property
    def test_logs_dir(self):
        return self._root_path / "test-logs"

    @property
    def glob_logs_dir(self):
        return self.test_logs_dir / "glob-logs"

    @property
    def non_glob_logs_dir(self):
        return self.test_logs_dir / "non-glob-logs"

    def get_checkpoints_path(self, worker_id):  # type: (six.text_type) -> pathlib.Path
        return self.agent_data_path / ("checkpoints-%s.json" % worker_id)

    def get_active_checkpoints_path(
        self, worker_id
    ):  # type: (six.text_type) -> pathlib.Path
        return self.agent_data_path / "active-checkpoints-%s.json" % worker_id

    def get_checkpoints(self, worker_id):
        return json.loads(self.get_checkpoints_path(worker_id).read_text())

    def get_active_checkpoints(self, worker_id):
        return json.loads(self.get_active_checkpoints_path(worker_id).read_text())

    @property
    def current_test_log_files(self):
        return self._current_test_log_files
