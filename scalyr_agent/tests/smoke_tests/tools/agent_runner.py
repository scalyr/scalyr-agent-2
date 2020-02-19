from __future__ import unicode_literals

import shutil
import os
from typing import Dict, Optional, Mapping, Any, List, Callable

try:
    from pathlib import Path
except ImportError:
    from pathlib2 import Path
import json
import tempfile
import subprocess

from scalyr_agent.__scalyr__ import PACKAGE_INSTALL, DEV_INSTALL
from scalyr_agent.platform_controller import PlatformController

from .utils import get_env

import six

AGENT_TEST_DIRECTORY_PATH = Path(tempfile.gettempdir()) / ".scalyr_agent_testing"


def _make_or_clear_directory(path):  # type: (Path) -> None
    """
    Create directory or clear it if exests..
    """
    if path.exists():
        shutil.rmtree(six.text_type(path), ignore_errors=True)
    path.mkdir(exist_ok=True, parents=True)


def map_path_to_another_path(path1, path2):  # type: (Path, Path) -> Path
    """
    Replace the root of the second path with first path.
    Example:
    path1 = /home/user/data
    path2 = /etc/hosts.txt
    result = /home/user/data/etc/hosts.txt
    """
    result = path1 / path2.relative_to(path2.parts[0])
    return result


def get_mapped_default_paths(path):  # type: (Path) -> Dict[six.text_type, Path]

    default_paths = _get_default_paths()
    for name, value in list(default_paths.items()):
        default_paths[name] = map_path_to_another_path(path, Path(value))

    return default_paths


def _path_or_text(fn):
    def wrapper(self, path, *args, **kwargs):
        if isinstance(path, six.text_type):
            path = Path(path)
        return fn(self, path, *args, **kwargs)

    return wrapper


class AgentRunner(object):
    """
       Base class for all kinds of agent runners.
       Agent runner provides ability to launch Scalyr agent with needed configuration settings.
       """

    def __init__(self, installation_type=DEV_INSTALL):  # type: () -> None

        self._agent_data_dir_path = None  # type: Optional[Path]
        self.agent_logs_dir_path = None  # type: Optional[Path]
        self._agent_config_path = None  # type: Optional[Path]

        self.agent_log_file_path = None  # type: Optional[Path]

        self._files = dict()  # type: Dict[six.text_type, Path]

        self._file_objects = dict()

        self._log_files = dict()  # type: Dict[six.text_type, Dict[six.text_type, Any]]

        self._installation_type = installation_type

        self._init_agent_paths()

    def get_file_path_text(self, path):  # type: (Path) -> str
        return str(self._files[six.text_type(path)])

    @_path_or_text
    def add_file(self, path):  # type: (Path) -> Path
        self._files[six.text_type(path)] = path
        return path

    @_path_or_text
    def add_log_file(self, path, attributes=None):  # type: (Path, Optional[Dict[six.text_type, Any]]) -> Path
        path = self.add_file(path)

        if attributes is None:
            attributes = {"parser": "json"}

        path_text = six.text_type(path)
        self._log_files[path_text] = {
            "path": path_text,
            "attributes": attributes
        }

        return path

    def _get_default_paths(self):  # type: () -> Dict[six.text_type, Path]
        platform = PlatformController.new_platform()
        platform._install_type = self._installation_type
        default_types = platform.default_paths

        result = dict()
        for k, v in default_types.__dict__.items():
            result[k] = Path(v)

        return result

    def _init_agent_paths(self):
        default_paths = self._get_default_paths()

        self._agent_data_dir_path = default_paths["agent_data_path"]
        self.agent_logs_dir_path = default_paths["agent_log_path"]

        self._agent_config_path = self.add_file(default_paths["config_file_path"])

        self.agent_log_file_path = self.add_file(self.agent_logs_dir_path / "agent.log")

        self._default_paths = default_paths

    def _create_agent_files(self):

        _make_or_clear_directory(self._agent_data_dir_path)

        _make_or_clear_directory(self.agent_logs_dir_path)
        # self._create_file(self.agent_log_file_path)

        # self._create_file(self._agent_config_path, content=self._agent_config)

        for file_path in self._files.values():
            self._create_file(file_path)

        self.write_to_file(
            self._agent_config_path,
            json.dumps(self._agent_config)
        )

    def _start(self):
        if self._installation_type == PACKAGE_INSTALL:
            self._agent_process = subprocess.Popen(
                ["/usr/sbin/scalyr-agent-2", "--no-fork", "--no-change-user", "start"],
            )
        else:
            self._agent_process = subprocess.Popen(
                "python -m scalyr_agent.agent_main --no-fork --no-change-user start",
                shell=True
            )
        return

    def start(self):
        self._create_agent_files()
        self._start()

    def stop(self):
        if self._agent_process.returncode is None:
            self._agent_process.terminate()

    @property
    def _server_host(self):  # type: () -> six.text_type
        return get_env("AGENT_HOST_NAME")

    @property
    def _agent_config(self):
        # type: () -> Dict[six.text_type, Any]
        """
        Build and return agent configuration.
        :return: dict with configuration.
        """
        return {
            "server_attributes": {
                "serverHost": self._server_host,
            },
            "logs": list(self._log_files.values())
        }

    @staticmethod
    def _create_file(path, content=None):
        # type: (Path, Optional[Any[six.text_type, six.binary_type]]) -> None
        """
        Add new file to runner's data directory.
        :param path: path to new file, it is relative to runner's data directory path.
        :param content: if set, write its data to file.
        :return:
        """

        if path.exists():
            os.remove(six.text_type(path))
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()

        if content:
            if isinstance(content, six.text_type):
                path.write_text(content)
            else:
                path.write_bytes(content)

    def read_file_content(self, path):  # type: (Path) -> six.text_type
        return path.read_text()

    def _write_to_file(self, path, data, mode="w"):
        # type: (Path, Any[six.text_type, six.binary_type], six.text_type) -> None
        data = six.ensure_text(data)

        file_object = self._file_objects.get(six.text_type(path))
        if file_object is None:
            file_object = path.open("w+")
            self._file_objects[six.text_type(path)] = file_object
        file_object.write(data)
        file_object.flush()

    def write_to_file(self, path, data):
        # type: (Path, Any[six.text_type, six.binary_type]) -> None
        self._write_to_file(path, data, mode="w")

    def append_to_file(self, path, data):
        # type: (Path, Any[six.text_type, six.binary_type]) -> None
        self._write_to_file(path, data, mode="a")

    def write_line(self, path, data):
        # type: (Path, Any[six.text_type, six.binary_type]) -> None
        final_data = data + type(data)("\n")
        self.append_to_file(path, final_data)
