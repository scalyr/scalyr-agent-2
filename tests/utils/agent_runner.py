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
from io import open

if False:  # NOSONAR
    from typing import Dict, Optional, Any, Union

import copy
import json
import pprint
import subprocess
import pathlib as pl

from distutils.spawn import find_executable

from scalyr_agent import __scalyr__
from scalyr_agent import compat
from scalyr_agent.platform_controller import PlatformController
from scalyr_agent.configuration import Configuration

from tests.utils.compat import Path
from tests.utils.common import get_env

import six


# This has to be a DEV installation so we can use install root as source root
_SOURCE_ROOT = __scalyr__.get_install_root()

_AGENT_PACKAGE_PATH = pl.Path(_SOURCE_ROOT, "scalyr_agent")


_AGENT_MAIN_PATH = Path(_AGENT_PACKAGE_PATH, "agent_main.py")
_CONFIG_MAIN_PATH = Path(_AGENT_PACKAGE_PATH, "agent_config.py")


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
        installation_type=__scalyr__.InstallType.DEV_INSTALL,
        enable_coverage=False,
        enable_debug_log=False,
        send_to_server=True,
        workers_type="thread",
        workers_session_count=1,
    ):  # type: (int, bool, bool, bool, six.text_type, int) -> None

        if enable_coverage and installation_type != __scalyr__.InstallType.DEV_INSTALL:
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

        self._workers_type = workers_type
        self._worker_sessions_count = workers_session_count

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

    def start(self, executable="python3"):
        self.clear_agent_logs()
        # important to call this function before agent was started.
        self._create_agent_files()

        if self._installation_type == __scalyr__.InstallType.PACKAGE_INSTALL:
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
                    "--branch",
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
                close_fds=True,
            )

        print("Agent started.")

        # NOTE: We register atexit handler to ensure agent process is always stopped. This means
        # even if a test failure occurs and we don't get a chance to manually call stop() method.
        atexit.register(self.stop)

    def status(self):
        if self._installation_type == __scalyr__.InstallType.PACKAGE_INSTALL:
            cmd = "/usr/sbin/scalyr-agent-2 status -v"
        else:
            cmd = "python3 {0} status -v".format(_AGENT_MAIN_PATH)

        output = compat.subprocess_check_output(cmd=cmd, shell=True)
        output = six.ensure_text(output)
        return output

    def status_json(self, parse_json=False):
        # type: (bool) -> Union[six.text_type, dict]
        """
        :param parse_json: True to parse result as json and return a dict.
        """
        if self._installation_type == __scalyr__.InstallType.PACKAGE_INSTALL:
            cmd = "/usr/sbin/scalyr-agent-2 status -v --format=json"
        else:
            cmd = "python3 {0} status -v --format=json".format(_AGENT_MAIN_PATH)

        output = compat.subprocess_check_output(cmd=cmd, shell=True)
        output = six.ensure_text(output)

        if parse_json:
            return json.loads(output)

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
        if self._installation_type == __scalyr__.InstallType.PACKAGE_INSTALL:
            subprocess.check_call(
                "/usr/sbin/scalyr-agent-2-config --set-python {0}".format(version),
                shell=True,
                **kwargs  # type: ignore
            )
        else:
            subprocess.check_call(
                "python3 {0} --set-python {1}".format(_CONFIG_MAIN_PATH, version),
                shell=True,
                **kwargs  # type: ignore
            )

    def stop(self, executable="python3"):
        if six.PY3:
            atexit.unregister(self.stop)

        if self._stopped:
            return

        print("Stopping agent process...")

        if self._installation_type == __scalyr__.InstallType.PACKAGE_INSTALL:
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

            # Print any output produced by the agent before forking which may not end up in the logs
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

    def restart(self, executable="python3"):
        print("Restarting agent process...")

        if self._installation_type == __scalyr__.InstallType.PACKAGE_INSTALL:
            service_executable = find_executable("service")
            if service_executable:
                cmd = "%s scalyr-agent-2 restart" % (service_executable)
            else:
                # Special case for CentOS 6 where we need to use absolute path to service command
                cmd = "/sbin/service scalyr-agent-2 restart"

            result = subprocess.check_call(cmd, shell=True)

            return result

        else:
            process = subprocess.Popen(
                "{0} {1} restart".format(executable, _AGENT_MAIN_PATH), shell=True
            )

            process.wait()
            self._agent_process.wait()

        print("Agent process restarted.")

    @property
    def agent_pid(self):
        path = self.agent_logs_dir_path / "agent.pid"
        with open(six.text_type(path), "r") as f:
            return int(f.read())

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

        # do not include default log files.
        files_to_exclude_from_config = [
            str(Path(self.agent_logs_dir_path, name))  # type:ignore
            for name in [
                "linux_process_metrics.log",
                "linux_system_metrics.log",
                "agent.log",
            ]
        ]
        config_log_files = list()
        for log_file in self._log_files.values():
            if log_file["path"] not in files_to_exclude_from_config:
                config_log_files.append(log_file)

        config = {
            "api_key": compat.os_environ_unicode["SCALYR_API_KEY"],
            "verify_server_certificate": "false",
            "server_attributes": {"serverHost": self._server_host},
            "logs": config_log_files,
            "default_sessions_per_worker": self._worker_sessions_count,
            "monitors": [],
            "use_multiprocess_workers": self._workers_type == "process",
            # NOTE: We disable this functionality so tests finish faster and we can use lower
            # timeout
            "global_monitor_sample_interval_enable_jitter": False,
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

    @property
    def config_object(self):  # type: () -> Configuration
        """
        Get config object from the config file.
        """
        platform = PlatformController.new_platform()
        platform._install_type = self._installation_type
        default_types = platform.default_paths

        config = Configuration(
            six.text_type(self._agent_config_path), default_types, None
        )
        config.parse()
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

    def clear_agent_logs(self):
        """Clear agent logs directory."""
        if self.agent_logs_dir_path.exists():
            for child in self.agent_logs_dir_path.iterdir():
                if child.is_file():
                    child.unlink()

    @property
    def config(self):
        # type: () -> Dict
        """
        Read config file and return as dict
        """

        return json.loads(self._agent_config_path.read_text())  # type: ignore

    def write_config(self, config):
        # type: (Dict) -> None
        """
        Write new data to the config.
        """
        self._agent_config_path.write_text(six.text_type(json.dumps(config)))  # type: ignore

    @property
    def worker_type(self):
        return self._workers_type

    @property
    def worker_session_ids(self):
        """
        Return ids of all running worker sessions.
        """
        status = json.loads(self.status_json())  # type: ignore
        ids = []
        for worker in status["copying_manager_status"]["workers"]:
            for worker_session in worker["sessions"]:
                ids.append(worker_session["session_id"])

        return ids

    @property
    def worker_sessions_log_paths(self):
        """Get list of log file path for all worker sessions."""
        result = []
        for worker_session_id in self.config_object.get_session_ids_from_all_workers():
            log_file_path = self.config_object.get_worker_session_agent_log_path(
                worker_session_id
            )
            result.append(Path(log_file_path))

        return result
