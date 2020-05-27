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
import atexit

if False:
    from typing import Dict, Optional, Any

import copy
import json
import pprint
import subprocess

from distutils.spawn import find_executable

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

    def __init__(
        self,
        installation_type=DEV_INSTALL,
        enable_coverage=False,
        enable_debug_log=False,
        send_to_server=True,
    ):  # type: (int, bool, bool, bool) -> None

        if enable_coverage and installation_type != DEV_INSTALL:
            raise ValueError("Coverage is only supported for dev installs")

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

        self._stopped = False

        self._enable_coverage = enable_coverage

        self._enable_debug_log = enable_debug_log

        # if set, the configuration option - 'disable_send_requests' is set to True
        self._send_to_server = send_to_server

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

        self.write_to_file(
            self._agent_config_path, json.dumps(self._agent_config, indent=4)
        )

    def start(self, executable="python"):
        # important to call this function before agent was started.
        self._create_agent_files()

        if self._installation_type == PACKAGE_INSTALL:
            # use service command to start agent, because stop command hands on some of the RHEL based distributions
            # if agent is started differently.
            service_executable = find_executable("service")
            if service_executable:
                cmd = "%s scalyr-agent-2 --no-fork --no-change-user start" % (
                    service_executable
                )
            else:
                # Special case for CentOS 6 where we need to use absolute path to service command
                cmd = "/sbin/service scalyr-agent-2 --no-fork --no-change-user start"

            self._agent_process = subprocess.Popen(
                cmd, shell=True, env=compat.os_environ_unicode.copy()
            )
        else:
            base_args = [
                str(_AGENT_MAIN_PATH),
                "--no-fork",
                "--no-change-user",
                "start",
            ]

            if self._enable_coverage:
                # NOTE: We need to pass in command string as a single argument to coverage run
                args = [
                    "coverage",
                    "run",
                    "--concurrency=thread",
                    "--parallel-mode",
                    " ".join(base_args),
                ]
            else:
                args = [executable] + base_args

            # NOTE: Using list would be safer since args are then auto escaped
            cmd = " ".join(args)
            self._agent_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                close_fds=False,
            )

        print("Agent started.")

        # NOTE: We register atexit handler to ensure agent process is always stopped. This means
        # even if a test failure occurs and we don't get a chance to manually call stop() method.
        atexit.register(self.stop)

    def status(self):
        if self._installation_type == PACKAGE_INSTALL:
            cmd = "/usr/sbin/scalyr-agent-2 status -v"
        else:
            cmd = "python {0} status -v".format(_AGENT_MAIN_PATH)

        output = compat.subprocess_check_output(cmd=cmd, shell=True)
        output = six.ensure_text(output)
        return output

    def status_json(self):
        if self._installation_type == PACKAGE_INSTALL:
            cmd = "/usr/sbin/scalyr-agent-2 status -v --format=json"
        else:
            cmd = "python {0} status -v --format=json".format(_AGENT_MAIN_PATH)

        output = compat.subprocess_check_output(cmd=cmd, shell=True)
        output = six.ensure_text(output)
        return output

    def switch_version(self, version, env=None):
        # type: (six.text_type, Optional[dict]) -> None
        """
        :param version: Python version to switch the agent to.
        :param env: Environment to use with this command.
        :param clean_env: True to perform the switch in a clean environment without the agent config
                          being present and any SCALYR_ environment variables being set.
        """
        if env:
            kwargs = {"env": env}
        else:
            kwargs = {}
        if self._installation_type == PACKAGE_INSTALL:
            subprocess.check_call(
                "/usr/sbin/scalyr-agent-2-config --set-python {0}".format(version),
                shell=True,
                **kwargs  # type: ignore
            )
        else:
            subprocess.check_call(
                "python {0} --set-python {1}".format(_CONFIG_MAIN_PATH, version),
                shell=True,
                **kwargs  # type: ignore
            )

    def stop(self, executable="python"):
        if six.PY3:
            atexit.unregister(self.stop)

        if self._stopped:
            return

        print("Stopping agent process...")

        if self._installation_type == PACKAGE_INSTALL:
            service_executable = find_executable("service")
            if service_executable:
                cmd = "%s scalyr-agent-2 stop" % (service_executable)
            else:
                # Special case for CentOS 6 where we need to use absolute path to service command
                cmd = "/sbin/service scalyr-agent-2 stop"

            result = subprocess.check_call(cmd, shell=True)

            return result

        else:
            process = subprocess.Popen(
                "{0} {1} stop".format(executable, _AGENT_MAIN_PATH), shell=True
            )

            process.wait()
            self._agent_process.wait()

            # Print any output produced by the agent before working which may not end up in the logs
            if self._agent_process.stdout and self._agent_process.stderr:
                stdout = self._agent_process.stdout.read().decode("utf-8")
                stderr = self._agent_process.stderr.read().decode("utf-8")

                if stdout:
                    print("Agent process stdout: %s" % (stdout))

                if stderr:
                    print("Agent process stderr: %s" % (stderr))

            if self._enable_coverage:
                # Combine all the coverage files for this process and threads into a single file so
                # we can copy it over.
                print("Combining coverage data...")
                os.system("coverage combine")

        print("Agent stopped.")
        self._stopped = True

    def __del__(self):
        self.stop()

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
        config = {
            "api_key": compat.os_environ_unicode["SCALYR_API_KEY"],
            "verify_server_certificate": "false",
            "server_attributes": {"serverHost": self._server_host},
            "logs": list(self._log_files.values()),
            "monitors": [],
            "max_log_offset_size": 5242880,
            "max_existing_log_offset_size": 104857600,
        }

        if self._enable_debug_log:
            # NOTE: We also enable copy_from_start if debug_level is enabled to we ship whole debug
            # log to scalyr
            config["debug_level"] = 5
            config["logs"].append({"path": "agent_debug.log"})  # type: ignore

        if not self._send_to_server:
            # do not send requests to server.
            config["disable_send_requests"] = True

        # Print out the agent config (masking the secrets) to make troubleshooting easier
        config_sanitized = copy.copy(config)
        config_sanitized.pop("api_key", None)

        print("Using agent config: %s" % (pprint.pformat(config_sanitized)))

        return config

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
