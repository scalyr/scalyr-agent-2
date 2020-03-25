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
from __future__ import print_function
from __future__ import absolute_import

import shutil
import os

if False:
    from typing import Dict, Optional, Any

import json
import subprocess

from scalyr_agent.__scalyr__ import PACKAGE_INSTALL, DEV_INSTALL, get_package_root
from scalyr_agent import compat
from scalyr_agent.platform_controller import PlatformController

from tests.utils.compat import Path
from tests.utils.common import get_env

import six

_AGENT_MAIN_PATH = Path(get_package_root(), "agent_main.py")
_CONFIG_MAIN_PATH = Path(get_package_root(), "config_main.py")


def _make_or_clear_directory(path):  # type: (Path) -> None
    """
    Create directory or clear it if exests..
    """
    if path.exists():
        shutil.rmtree(six.text_type(path), ignore_errors=True)
    path.mkdir(exist_ok=True, parents=True)


def _path_or_text(fn):
    def wrapper(self, path, *args, **kwargs):
        if isinstance(path, six.text_type):
            path = Path(path)
        return fn(self, path, *args, **kwargs)

    return wrapper


class AgentRunner(object):
    """
       Agent runner provides ability to launch Scalyr agent with needed configuration settings.
       """

    def __init__(self, installation_type=DEV_INSTALL):  # type: (int) -> None

        # agent data directory path.
        self._agent_data_dir_path = None  # type: Optional[Path]
        # agent logs directory path.
        self.agent_logs_dir_path = None  # type: Optional[Path]
        # path to the agent config.
        self._agent_config_path = None  # type: Optional[Path]

        # path to the agent.log file.
        self.agent_log_file_path = None  # type: Optional[Path]

        # all files processed by the agent
        self._files = dict()  # type: Dict[six.text_type, Path]

        # all files considered as a log files.
        self._log_files = dict()  # type: Dict[six.text_type, Dict[six.text_type, Any]]

        # The gent runner uses this variable as a hint where to search agent essential paths.
        # This is useful when agent was installed from package,
        # and agent runner needs to know it where files are located.
        self._installation_type = installation_type

        self._init_agent_paths()

        self._agent_process = None

    def get_file_path_text(self, path):  # type: (Path) -> str
        return str(self._files[six.text_type(path)])

    @_path_or_text
    def add_file(self, path):  # type: (Path) -> Path
        self._files[six.text_type(path)] = path
        return path

    @_path_or_text
    def add_log_file(self, path, attributes=None):
        # type: (Path, Optional[Dict[six.text_type, Any]]) -> Path
        path = self.add_file(path)

        if attributes is None:
            attributes = {"parser": "json"}

        path_text = six.text_type(path)
        self._log_files[path_text] = {"path": path_text, "attributes": attributes}

        return path

    def _get_default_paths(self):  # type: () -> Dict[six.text_type, Path]
        """
        Get default path for essential directories and files of the agent.  Those paths are fetched from 'PlatformController'.
        """
        # create new 'PlatformController' instance. Since this code is executed on the same machine with agent,
        # platform setting and paths should match.
        platform = PlatformController.new_platform()
        # change install type of the controller to needed one.
        platform._install_type = self._installation_type

        default_types = platform.default_paths

        result = dict()
        for k, v in default_types.__dict__.items():
            result[k] = Path(v)

        return result

    def _init_agent_paths(self):
        """
        Set paths for the essential files and directories.
        """
        default_paths = self._get_default_paths()

        self._agent_data_dir_path = default_paths["agent_data_path"]
        self.agent_logs_dir_path = default_paths["agent_log_path"]

        self._agent_config_path = self.add_file(default_paths["config_file_path"])

        self.agent_log_file_path = self.add_file(self.agent_logs_dir_path / "agent.log")

        self._default_paths = default_paths

    def _create_agent_files(self):
        """
        Create all essential files and directories and dynamically added files.
        """
        _make_or_clear_directory(self._agent_data_dir_path)

        _make_or_clear_directory(self.agent_logs_dir_path)

        for file_path in self._files.values():
            self._create_file(file_path)

        self.write_to_file(self._agent_config_path, json.dumps(self._agent_config))

    def start(self):
        # important to call this function before agent was started.
        self._create_agent_files()

        if self._installation_type == PACKAGE_INSTALL:
            # use service command to start agent, because stop command hands on some of the RHEL based distributions
            # if agent is started differently.
            self._agent_process = subprocess.Popen(
                "service scalyr-agent-2 --no-fork --no-change-user start", shell=True
            )
        else:
            self._agent_process = subprocess.Popen(
                "python {0} --no-fork --no-change-user start".format(_AGENT_MAIN_PATH),
                shell=True,
            )

        print("Agent started.")

    def status(self):
        if self._installation_type == PACKAGE_INSTALL:
            process = subprocess.check_output(
                "service scalyr-agent-2 status -v", shell=True
            )

            return process

        else:
            output = subprocess.check_output(
                "python {0} status -v".format(_AGENT_MAIN_PATH), shell=True
            )
            return output

    def status_json(self):
        if self._installation_type == PACKAGE_INSTALL:
            result = subprocess.check_output(
                "scalyr-agent-2 status -v --format=json", shell=True
            )

            return result

        else:
            result = subprocess.check_call(
                "python {0} status -v --format=json".format(_AGENT_MAIN_PATH),
                shell=True,
            )
            return result

    def switch_version(self, version):
        if self._installation_type == PACKAGE_INSTALL:
            subprocess.check_call(
                "/usr/sbin/scalyr-agent-2-config --set-python {0}".format(version),
                shell=True,
            )
        else:
            subprocess.check_call(
                "python {0} --set=python {1}".format(_CONFIG_MAIN_PATH, version),
                shell=True,
            )

    def stop(self):
        if self._installation_type == PACKAGE_INSTALL:
            result = subprocess.check_call("/usr/sbin/scalyr-agent-2 stop", shell=True)

            return result

        else:
            self._agent_process = subprocess.Popen(
                "python {0} stop".format(_AGENT_MAIN_PATH), shell=True
            )
        print("Agent stopped.")

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
            "api_key": compat.os_environ_unicode["SCALYR_API_KEY"],
            "verify_server_certificate": "false",
            "server_attributes": {"serverHost": self._server_host},
            "logs": list(self._log_files.values()),
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

    @staticmethod
    def read_file_content(path):  # type: (Path) -> six.text_type
        return path.read_text()

    def write_to_file(self, path, data):
        # type: (Path, six.text_type) -> None
        """
        Write data to the file located in 'path'
        """
        data = six.ensure_text(data)
        with path.open("a") as f:
            f.write(data)
            f.flush()

    def write_line(self, path, data):
        # type: (Path, six.text_type) -> None
        data = six.ensure_text(data)
        data = "{0}\n".format(data)
        self.write_to_file(path, data)
