# Copyright 2014-2022 Scalyr Inc.
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

import subprocess
import json
import pathlib as pl
from typing import List, Dict


__all__ = ["DockerContainer", "LocalRegistryContainer"]


class DockerContainer:
    """
    Simple wrapper around docker container that allows to use context manager to clean up when container is not
    needed anymore.
    NOTE: The 'docker' library is not used on purpose, since there's only one abstraction that is needed. Using
    docker through the docker CLI is much easier and does not require the "docker" lib as a dependency.
    """

    def __init__(
        self,
        name: str,
        image_name: str,
        ports: Dict[str, str] = None,
        mounts: List[str] = None,
        command: List[str] = None,
        detached: bool = True,
    ):
        self.name = name
        self.image_name = image_name
        self.mounts = mounts or []

        self.ports = {}
        ports = ports or {}
        for name, p in ports.items():
            host, guest = p.split(":")
            if "/" in guest:
                guest_port, proto = guest.split("/")
            else:
                guest_port = guest
                proto = "tcp"
            self.ports[name] = f"{host}:{guest_port}/{proto}"
        self.command = command or []
        self.detached = detached

        self.real_ports = {}

    def start(self):

        # Kill the previously run container, if exists.
        self.kill()

        command_args = [
            "docker",
            "run",
            "-d" if self.detached else "-i",
            "--name",
            self.name,
        ]

        for ports in self.ports.values():
            command_args.append("-p")
            command_args.append(ports)

        for mount in self.mounts:
            command_args.append("-v")
            command_args.append(mount)

        command_args.append(self.image_name)

        command_args.extend(self.command)

        subprocess.check_call(
            command_args,
        )

        self.real_ports = self._get_real_ports()

    def kill(self):
        subprocess.check_call(
            ["docker", "rm", "-f", self.name],
        )

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.kill()

    def _get_real_ports(self):
        output = (
            subprocess.check_output(["docker", "container", "inspect", self.name])
            .decode()
            .strip()
        )
        container_info = json.loads(output)[0]
        ports_info = container_info["NetworkSettings"]["Ports"]

        result = {}
        for name, ports in self.ports.items():
            host, guest = ports.split(":")
            host_info = ports_info[guest][0]
            result[name] = int(host_info["HostPort"])

        return result


class LocalRegistryContainer(DockerContainer):
    """
    Container start runs local docker registry inside.
    """

    def __init__(
        self, name: str, registry_port: int, registry_data_path: pl.Path = None
    ):
        """
        :param name: Name of the container.
        :param registry_port: Host port that will be mapped to the registry's port.
        :param registry_data_path: Host directory that will be mapped to the registry's data root.
        """

        mounts = []
        if registry_data_path:
            mounts.append(f"{registry_data_path}:/var/lib/registry")

        super(LocalRegistryContainer, self).__init__(
            name=name,
            image_name="registry:2",
            ports={"registry_port": f"{registry_port}:{5000}"},
            mounts=mounts,
        )

    @property
    def real_registry_port(self):
        return self.real_ports["registry_port"]
