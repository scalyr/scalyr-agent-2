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
import collections

try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib

if False:
    from typing import Union
    from typing import Dict
    from typing import Tuple
    from typing import Optional

from scalyr_agent.configuration import Configuration
from scalyr_agent.log_processing import LogMatcher, LogFileProcessor
from scalyr_agent.platform_controller import DefaultPaths


import six
from six.moves import range


class TestableLogFile(object):
    """
    A testing purpose class that can perform useful operations on file.
    """

    __test__ = False

    def __init__(self, config, name):
        # type: (Configuration, Union[str, pathlib.Path]) -> None

        self._config = config
        self.name = name

        # the path of the file, it is unknown until the file is created by the 'create' function
        self.path = None

    def create(self, root_path):
        """
        Create file in the root path.
        """
        self.path = pathlib.Path(root_path, self.name)
        self.path.touch()

    def append_lines(self, *lines):  # type: (six.text_type) -> None
        """
        Append lines to the file.
        """
        with self.path.open("a") as file:
            for line in lines:
                file.write(line)
                file.write("\n")

    def _create_log_matcher_for_log_file(self):  # type: () -> LogMatcher
        """
        Create log matcher from the appropriate log config from the configuration.
        """

        log_config = next(
            iter(lc for lc in self._config.log_configs if lc["path" == self.path])
        )

        return LogMatcher(self._config, log_config)

    def create_single_log_processor(
        self, checkpoints=None, copy_at_index_zero=False
    ):  # type: (Dict, bool) -> LogFileProcessor
        """
        Create log file processor by the log matcher.
        :return:
        """

        matcher = self._create_log_matcher_for_log_file()

        if checkpoints is None:
            checkpoints = {}

        processors = []
        for processor in matcher.find_matches(
            existing_processors=[],
            previous_state=checkpoints,
            copy_at_index_zero=copy_at_index_zero,
        ):
            processors.append(processor)

        return processors[0]

    @property
    def str_path(self):
        return six.text_type(self.path)


def after_initialize(f):
    """
    Decorator for the methods of the 'ConfigBuilder' class.
    It raises error if decorated method must not be called before Config builder is initialized.
    """

    def wrapper(self, *args, **kwargs):
        if not self._initialized:
            raise RuntimeError(
                "Method '{0}' cannot be called before this Test config is initialized.".format(
                    f.__name__
                )
            )

        return f(self, *args, **kwargs)

    return wrapper


def before_initialize(f):
    """
    Decorator for the methods of the 'ConfigBuilder' class.
    It raises error if decorated method must not be called after Config builder is initialized.
    """

    def wrapper(self, *args, **kwargs):
        if self._initialized:
            raise RuntimeError(
                "Method '{0}' cannot be called after this Test config is initialized.".format(
                    f.__name__
                )
            )
        return f(self, *args, **kwargs)

    return wrapper


class TestingConfiguration(Configuration):
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

    def __init__(self, config_data=None):

        self._config_initial_data = config_data

        self._config = None  # type: Optional[TestingConfiguration]
        self._cleared = None

        self._root_path = None

        # self._log_processors = dict()  # type: Dict[str, LogFileProcessor]

        self._initialized = False

        # additional log files that should be reflected in the "logs" section of the configuration.
        self._log_files = collections.OrderedDict()  # type: Dict[str, TestableLogFile]

        self.__use_pipelining = None

    def __del__(self):
        self.clear()

    def initialize(self):
        """
        Creates config object and prepares needed environment.
        This config will contain all additions that are made before this method is called.
        :return:
        """

        self._root_path = root_path = pathlib.Path(
            tempfile.mkdtemp(prefix="scalyr_testing")
        )
        self._data_dir_path = root_path / "data"
        self._data_dir_path.mkdir()

        self._logs_dir_path = root_path / "logs"
        self._logs_dir_path.mkdir()

        self._agent_config_path = root_path / "agent.json"

        for log_file in self._log_files.values():
            log_file.create(self._root_path)

        self._create_config(self._config_initial_data)

        self._initialized = True

    def _create_config(self, config_data=None):  # type: (Optional[Dict]) -> None
        """
        Create config object and apply all additions.
        :param config_data:
        :return:
        """

        default_paths = DefaultPaths(
            six.text_type(self._logs_dir_path),
            six.text_type(self._agent_config_path),
            six.text_type(self._data_dir_path),
        )

        if config_data is None:
            config_data = dict()

        if "api_key" not in config_data:
            config_data["api_key"] = "fake"

        if "debug_level" not in config_data:
            config_data["debug_level"] = 5

        logs = config_data.get("logs", list())

        for log_file in self._log_files.values():
            logs.append({"path": six.text_type(log_file.path)})

        config_data["logs"] = logs

        self._agent_config_path.write_text(six.text_type(json.dumps(config_data)))

        config = TestingConfiguration(
            six.text_type(self._agent_config_path), default_paths, None
        )

        config.parse()

        self._config = config

    @property
    @after_initialize
    def config(self):  # type: () -> Configuration
        return self._config

    @property
    @after_initialize
    def log_files(self):  # type: () -> Dict[str, TestableLogFile]
        return self._log_files

    @after_initialize
    def get_log_config(self, log_file):  # type: (TestableLogFile) -> Dict
        """
        Get log config from existing config.
        """

        for log_config in self._config.log_configs:
            if six.text_type(log_file.path) == log_config["path"]:
                return log_config

        raise RuntimeError(
            "Log config for file: '{0}' is not found.".format(log_file.path)
        )

    def clear(self):
        if not self._cleared:
            shutil.rmtree(six.text_type(self._root_path))
            self._cleared = True

    @before_initialize
    def add_log_file(
        self, name=None, create=True
    ):  # type: (Optional[str], bool) -> TestableLogFile
        """
        Add new file into "logs" section.
        :param name: Name to the file relative to ths environment root path.
        :param create: Create file in filesystem if True
        """

        if name is None:
            name = "test_file_{0}".format(len(self._log_files))

        file_obj = TestableLogFile(config=self._config, name=name)

        self._log_files[name] = file_obj

        return file_obj

    @after_initialize
    def get_log_file(self, name):  # type: (str) -> TestableLogFile
        log_file = self._log_files.get(name)
        if name is None:
            raise RuntimeError(
                "Can not find file '{0}' in config".format(log_file.path)
            )

        return log_file

    @after_initialize
    def get_log_file_path(self, name):  # type: (str) -> pathlib.Path

        log_file = self._log_files.get(name)
        if name is None:
            raise RuntimeError("Can not find file '{0}' in config")

        return pathlib.Path(log_file.path)

    @after_initialize
    def append_lines_to_log_file(self, name, *lines):
        path = self.get_log_file_path(name)
        with path.open("a") as file:
            for line in lines:
                file.write(line)
                file.write("\n")

    @classmethod
    def create_with_n_files(cls, n, config_data=None):
        # type: (int, Dict) -> Tuple[Tuple[TestableLogFile, ...], TestEnvironBuilder]
        """
        Convenient config factory which creates config builder with n log_files.
        """
        test_environment = cls(config_data=config_data)

        log_files = tuple(test_environment.add_log_file(create=True) for _ in range(n))

        test_environment.initialize()
        return log_files, test_environment

    @property
    @after_initialize
    def agent_data_path(self):
        return self._data_dir_path

    @after_initialize
    def get_checkpoints_path(self, worker_id):  # type: (six.text_type) -> pathlib.Path
        return self._data_dir_path / ("checkpoints-%s.json" % worker_id)

    @after_initialize
    def get_active_checkpoints_path(
        self, worker_id
    ):  # type: (six.text_type) -> pathlib.Path
        return self._data_dir_path / "active-checkpoints-%s.json" % worker_id

    @after_initialize
    def get_checkpoints(self, worker_id):
        return json.loads(self.get_checkpoints_path(worker_id).read_text())

    @after_initialize
    def get_active_checkpoints(self, worker_id):
        return json.loads(self.get_active_checkpoints_path(worker_id).read_text())
