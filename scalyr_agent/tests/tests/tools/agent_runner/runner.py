from typing import Dict, Optional, Mapping, Any
from pathlib import Path
import abc
import json
import tempfile
import os
import socket

#from .agent_file import DockerMountedFile
from scalyr_agent.tests.tests.tools.utils import create_temp_dir_with_constant_name

from scalyr_agent.platform_controller import PlatformController
from scalyr_agent.platform_controller import DefaultPaths

import six


class AgentRunner:
    """
    Base class for all kinds of agent runners.
    Agent runner provides ability to launch Scalyr agent with needed configuration settings.
    """

    def __init__(self, test_config=None):
        # type: (Mapping) -> None
        """
        :param test_config: dict-like object with testing configuration.
        """
        #self._test_config = test_config

        # create temporary root directory. Path should be constant for more convenient navigation in Scalyr UI.
        # this directory acts like root directory for agent.
        self._data_dir_path = create_temp_dir_with_constant_name()

        os.system("xdg-open {}".format(self._data_dir_path))

        self._agent_data_dir_path = None  # type: Optional[Path]
        self._agent_logs_dir_path = None  # type: Optional[Path]
        self._agent_config_path = None  # type: Optional[Path]

        self._agent_log_file_path = None  # type: Optional[Path]

        self._files = dict()  # type: Dict[str,Path]

        # get default values from appropriate controller.
        default_paths = PlatformController.new_platform().default_paths
        # needs to called after all attributes are defined.
        self._init_paths(default_paths)

    def _init_paths(self, default_paths):  # type: (DefaultPaths) -> None
        """
        Init paths for agent default files.
        :param default_paths scalyr_agent/platform_controller.DefaultPaths object with default paths,
        """

        self._agent_data_dir_path = Path(default_paths.agent_data_path)
        self._agent_logs_dir_path = Path(default_paths.agent_log_path)
        self._agent_config_path = Path(default_paths.config_file_path)

        self._agent_log_file_path = self._agent_logs_dir_path / "agent.log"

    @property
    def _server_host(self):  # type: () -> six.text_type
        """Returns value for 'server_attributes.serverHost' in agent config."""
        return six.ensure_text(socket.gethostname())

    @property
    def _agent_config(self):
        # type: () -> Dict[str, Any]
        """
        Build and return agent configuration.
        :return: dict with configuration.
        """
        return {
            "server_attributes": {
                "serverHost": self._server_host
            },
        }

    def add_file(self, path, content=None):
        # type: (Path, Optional[Any[six.text_type, six.binary_type]]) -> None
        """
        Add new file to runner's data directory.
        :param path: path to new file, it is relative to runner's data directory path.
        :param content: if set, write its data to file.
        :return:
        """

        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

        if content:
            if isinstance(content, six.text_type):
                path.write_text(content)
            else:
                path.write_bytes(content)

        self._files[str(path)] = path

    def _create_files(self):
        # prepare logs path

        self.add_file(
            Path(self._agent_config_path), content=json.dumps(self._agent_config)
        )
        self.add_file(self._agent_log_file_path)

        self._agent_data_dir_path.mkdir(parents=True, exist_ok=True)

    def _start(self):
        self._create_files()

    def start(self):
        self._start()

    def read_file_content(self, path):  # type: (Path) -> six.text_type
        pass


# class BaseContainerRunner(abc.ABC):
#     def __init__(self, name, image, docker_client, command=None):
#         self._docker_client = docker_client
#         self._container = None
#
#         self._temp_data_dir: tempfile.TemporaryDirectory = create_temp_dir_with_constant_name()
#         self._mounted_files: Dict[str, DockerMountedFile] = dict()
#
#         self.environment: Dict[str, str] = dict()
#
#         self.container_name = name
#         self.image = image
#         self._command = command
#
#     def _create_container(self):
#         found = self._docker_client.containers.list(
#             filters={"name": self.container_name}, all=True
#         )
#         for container in found:
#             container.remove(force=True)
#
#         mounts = [mf.docker_mount for mf in self._mounted_files.values()]
#         self._container = self._docker_client.containers.create(
#             self.image,
#             name=self.container_name,
#             command=self._command,
#             auto_remove=True,
#             **{"mounts": mounts, "environment": self.environment}
#         )
#
#     def create(self):
#         pass
#
#     def mount_file(self, container_path, mode="r", content=None, watch=False):
#         file = DockerMountedFile(
#             container_path, Path(self._temp_data_dir.name), mode=mode, content=content
#         )
#         self._mounted_files[container_path] = file
#
#         file.create()
#         return file
#
#     def run(self):
#         self.create()
#         self._create_container()
#         self._container.start()


# class BaseAgentContainerRunner(BaseContainerRunner):
#     def __init__(
#             self,
#             name,
#             image,
#             docker_client,
#             test_config: Mapping,
#             command: str = None,
#             agent_json_config: Mapping = None,
#     ):
#         super().__init__(name, image, docker_client, command=command)
#         self._test_config = test_config
#         self.agent_json_config = agent_json_config or dict()
#
#         self.agent_json_config_file: Optional[DockerMountedFile] = None
#         self.agent_log_file: Optional[DockerMountedFile] = None
#
#         self.agent_system_metrics_monitor_log_file: Optional[DockerMountedFile] = None
#
#     def create(self):
#         # add host name to agent.json config
#         agent_settings = self._test_config["agent_settings"]
#         self.agent_json_config["server_attributes"]["serverHost"] = agent_settings[
#             "HOST_NAME"
#         ]
#         self.agent_json_config["server_attributes"]["serverHost"] = agent_settings[
#             "HOST_NAME"
#         ]
#
#         self._command = '/bin/bash -c "/usr/sbin/scalyr-agent-2 --no-change-user start && sleep 3000"'
#
#         # create agent.json
#         self.agent_json_config_file = self.mount_file(
#             "/etc/scalyr-agent-2/agent.json", content=json.dumps(self.agent_json_config)
#         )
#
#         # add agent.log file
#         self.agent_log_file = self.mount_file(
#             "/var/log/scalyr-agent-2/agent.log", watch=True
#         )
#
#         # add system metrics monitor log.
#         self.agent_system_metrics_monitor_log_file = self.mount_file(
#             "/var/log/scalyr-agent-2/linux_system_metrics.log", watch=True
#         )
#
#         # init env variables
#         agent_settings = self._test_config["agent_settings"]
#
#         self.environment.update(
#             {
#                 "SCALYR_API_KEY": agent_settings["SCALYR_API_KEY"],
#                 "SCALYR_READ_KEY": agent_settings["SCALYR_READ_KEY"],
#                 "SCALYR_SERVER": agent_settings["SCALYR_SERVER"],
#             }
#         )
#
#     def add_log_file(self, path: str, attributes: Dict, mode="r") -> DockerMountedFile:
#         file = self.mount_file(path, mode=mode)
#         if "logs" not in self.agent_json_config:
#             pass  # self.agent_json_config["logs"] = list()
#
#         self.agent_json_config["logs"].append({"path": path, "attributes": attributes})
#
#         return file
#
#     @property
#     def hostname(self):
#         return self.agent_json_config["server_attributes"]["serverHost"]
#
#     def stop(self):
#         self._container.stop()
#
#     def remove(self):
#         self._container.remove(force=True)
