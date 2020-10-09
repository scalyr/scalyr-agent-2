from __future__ import unicode_literals

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


class TestableLogFile(object):
    __test__ = False

    def __init__(self, config_builder, name, path, create=True):
        # type: (ConfigBuilder, str, Union[str, pathlib.Path], bool) -> None

        self._config_builder = config_builder
        self.name = name
        self.path = pathlib.Path(path)

        if create:
            self.path.touch()

    def append_lines(self, *lines):  # type: (six.text_type) -> None
        with self.path.open("a") as file:
            for line in lines:
                file.write(line)
                file.write("\n")

    def spawn_log_matcher_for_log_file(self):  # type: () -> LogMatcher
        log_config = self._config_builder.get_log_config(self)

        return LogMatcher(self._config_builder.config, log_config)

    def spawn_log_processors(
        self, checkpoints=None, copy_at_index_zero=False
    ):  # type: (Dict) -> Dict[str, LogFileProcessor]
        matcher = self.spawn_log_matcher_for_log_file()

        if checkpoints is None:
            checkpoints = {}

        return {
            processor.log_path: processor
            for processor in matcher.find_matches(
                existing_processors=[],
                previous_state=checkpoints,
                copy_at_index_zero=copy_at_index_zero,
            )
        }

    def spawn_single_log_processor(self, checkpoints=None, copy_at_index_zero=False):

        processors = self.spawn_log_processors(
            checkpoints=checkpoints, copy_at_index_zero=copy_at_index_zero
        )
        if len(processors) > 1:
            raise RuntimeError(
                "Log matcher created more than one log processors for path '{0}'".format(
                    self.path
                )
            )
        elif len(processors) == 0:
            raise RuntimeError("No matches for path: '{0}'".format(self.path))

        return list(processors.values())[0]

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


class ConfigBuilder(object):
    """
    Builder for tor the configuration object and agent essential environment.
    It allows to make additions which will be included to the resulting config file.
    """

    def __init__(self, config_data=None):

        self._config_initial_data = config_data

        self._config = None
        self._cleared = None

        self._root_path = None

        # self._log_processors = dict()  # type: Dict[str, LogFileProcessor]

        self._initialized = False

        # additional log files that should be reflected in the "logs" section of the configuration.
        self._log_files = collections.OrderedDict()  # type: Dict[str, TestableLogFile]

        self.__use_pipelining = None

        self._create_agent_root_dir()

    def __del__(self):
        self.clear()

    def initialize(self):
        """
        Creates config object and prepares needed environment.
        This config will contain all additions that are made before this method is called.
        :return:
        """

        self._create_config(self._config_initial_data)

        self._initialized = True

    def _create_agent_root_dir(self):  # type: () -> None
        self._root_path = root_path = pathlib.Path(
            tempfile.mkdtemp(prefix="scalyr_testing")
        )

        self._data_dir_path = root_path / "data"
        self._data_dir_path.mkdir()

        self._logs_dir_path = root_path / "logs"
        self._logs_dir_path.mkdir()

        self._agent_config_path = root_path / "agent.json"

    def _create_config(self, config_data=None):  # type: (Optional[Dict]) -> None
        """
        Create config object and apply all additions.
        :param config_data:
        :return:
        """
        self._create_agent_root_dir()

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

        config = Configuration(
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

        abs_path = self._root_path / name

        file_obj = TestableLogFile(
            config_builder=self, name=name, path=abs_path, create=create
        )

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

    def append_lines_to_log_file(self, name, *lines):
        path = self.get_log_file_path(name)
        with path.open("a") as file:
            for line in lines:
                file.write(line)
                file.write("\n")

    @classmethod
    def build_config_with_n_files(cls, n, config_data=None):
        # type: (int, Dict) -> Tuple[Tuple[TestableLogFile, ...], ConfigBuilder]
        """
        Convenient config factory which creates config builder with n log_files.
        """
        config_builder = cls(config_data=config_data)

        log_files = tuple(config_builder.add_log_file(create=True) for _ in range(n))

        config_builder.initialize()
        return log_files, config_builder

    @classmethod
    def build_config_with_single_file(cls, config_data=None):
        # type: (Dict) -> Tuple[TestableLogFile, ConfigBuilder]
        """
        Convenient config factory which creates config builder with one log_files.
        :return: Tuple with log file object and config builder itself.
        """
        (log_file,), config_builder = cls.build_config_with_n_files(1, config_data)

        return log_file, config_builder

    def get_checkpoints_path(self, worker_id):  # type: (six.text_type) -> pathlib.Path
        return self._data_dir_path / "checkpoints" / ("checkpoints-%s.json" % worker_id)

    def get_active_checkpoints_path(
        self, worker_id
    ):  # type: (six.text_type) -> pathlib.Path
        return self._data_dir_path / "checkpoints" / "active-checkpoints-%s.json" % worker_id

    @after_initialize
    def get_checkpoints(self, worker_id):
        return json.loads(self.get_checkpoints_path(worker_id).read_text())

    @after_initialize
    def get_active_checkpoints(self, worker_id):
        return json.loads(self.get_active_checkpoints_path(worker_id).read_text())

    def spawn_checkpoints(self):
        # type: () -> Dict
        """
        Spawn checkpoints dict for all log files in this builder.
        It can be modified and used as initial checkpoints objects in tests.
        """
        checkpoints = {}
        for log_file in self._log_files.values():
            checkpoints[log_file.path] = {"initial_position": 0}

        checkpoints

    def write_checkpoints(self, data):
        self.checpoints_path.write_text(six.text_type(json.dumps(data)))

    def write_active_checkpoints(self, data):
        self.active_checpoints_path.write_text(six.text_type(json.dumps(data)))
