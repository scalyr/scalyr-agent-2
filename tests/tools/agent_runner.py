from typing import Dict, Optional, Mapping, Callable
from pathlib import Path
import abc
import json
import tempfile

from .agent_file import MountedFile
from .utils import create_temp_dir


class BaseContainerRunner(abc.ABC):
    def __init__(self, name, image, docker_client, command=None):
        self._docker_client = docker_client
        self._container = None

        self._temp_data_dir: tempfile.TemporaryDirectory = create_temp_dir()
        self._mounted_files: Dict[str, MountedFile] = dict()

        self.environment: Dict[str, str] = dict()

        self.container_name = name
        self.image = image
        self._command = command

    def _create_container(self):
        found = self._docker_client.containers.list(filters={"name": self.container_name}, all=True)
        for container in found:
            container.remove(force=True)

        mounts = [mf.docker_mount for mf in self._mounted_files.values()]
        self._container = self._docker_client.containers.create(
            self.image,
            name=self.container_name,
            command=self._command,
            auto_remove=True,
            **{
                "mounts": mounts,
                "environment": self.environment
            }
        )

    def create(self):
        pass

    def mount_file(self,
                   container_path,
                   mode="r",
                   content=None,
                   watch=False
                   ):
        file = MountedFile(
            container_path,
            Path(self._temp_data_dir.name),
            mode=mode,
            content=content
        )
        self._mounted_files[container_path] = file

        file.create()
        return file

    def run(self):
        self.create()
        self._create_container()
        self._container.start()


class BaseAgentContainerRunner(BaseContainerRunner):
    def __init__(self,
                 name,
                 image,
                 docker_client,
                 test_config: Mapping,
                 command: str = None,
                 agent_json_config: Mapping = None
                 ):

        super().__init__(name, image, docker_client, command=command)
        self._test_config = test_config
        self.agent_json_config = agent_json_config or dict()

        self.agent_json_config_file: Optional[MountedFile] = None
        self.agent_log_file: Optional[MountedFile] = None

        self.agent_system_metrics_monitor_log_file: Optional[MountedFile] = None


    def create(self):
        # add host name to agent.json config
        agent_settings = self._test_config["agent_settings"]
        self.agent_json_config["server_attributes"]["serverHost"] = agent_settings["HOST_NAME"]
        self.agent_json_config["server_attributes"]["serverHost"] = agent_settings["HOST_NAME"]

        self._command = '/bin/bash -c "/usr/sbin/scalyr-agent-2 --no-change-user start && sleep 3000"'

        # create agent.json
        self.agent_json_config_file = self.mount_file(
            "/etc/scalyr-agent-2/agent.json",
            content=json.dumps(self.agent_json_config)
        )

        # add agent.log file
        self.agent_log_file = self.mount_file(
            "/var/log/scalyr-agent-2/agent.log",
            watch=True
        )

        # add system metrics monitor log.
        self.agent_system_metrics_monitor_log_file = self.mount_file(
            "/var/log/scalyr-agent-2/linux_system_metrics.log",
            watch=True
        )


        # init env variables
        agent_settings = self._test_config["agent_settings"]

        self.environment.update({
            "SCALYR_API_KEY": agent_settings["SCALYR_API_KEY"],
            "SCALYR_READ_KEY": agent_settings["SCALYR_READ_KEY"],
            "SCALYR_SERVER": agent_settings["SCALYR_SERVER"]
        })

    def add_log_file(self, path: str, attributes: Dict, mode="r") -> MountedFile:
        file = self.mount_file(path, mode=mode)
        if "logs" not in self.agent_json_config:
            self.agent_json_config["logs"] = list()

        self.agent_json_config["logs"].append({
            "path": path,
            "attributes": attributes
        })

        return file

    @property
    def hostname(self):
        return self.agent_json_config["server_attributes"]["serverHost"]

    def stop(self):
        self._container.stop()

    def remove(self):
        self._container.remove(force=True)
