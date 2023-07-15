import json
import logging
import subprocess
import pathlib as pl
from typing import List, Dict

logger = logging.getLogger(__name__)


def get_docker_container_host_port(
    container_name: str,
    container_port: str,
    prefix_cmd_args: List[str] = None,
):

    prefix_cmd_args = prefix_cmd_args or []

    try:
        inspect_result = subprocess.run(
            [
                *prefix_cmd_args,
                "docker",
                "inspect",
                container_name
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logger.exception(
            f"The docker inspect command has failed. Stderr: {e.stderr.decode()}"
        )
        raise

    inspect_result = json.loads(
        inspect_result.stdout.decode()
    )
    container_info = inspect_result[0]
    host_port = container_info["NetworkSettings"]["Ports"][container_port][0]["HostPort"]
    return host_port



def delete_container(
    container_name: str,
    force: bool = True,
    initial_cmd_args: List[str] = None,
    logger=None
):
    initial_cmd_args = initial_cmd_args or []

    cmd_args = [
        *initial_cmd_args,
        "docker",
        "rm",
    ]
    if force:
        cmd_args.append("-f")
    try:
        subprocess.run(
            [
                *cmd_args,
                container_name
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        if logger:
            logger.exception(f"Can not remove container '{container_name}'. Stderr: {e.stderr.decode()}")

        raise


class ContainerWrapper:
    def __init__(
        self,
        name: str,
        image: str,
        rm: bool = False,
        ports: Dict[int, str] = None,
        volumes: Dict[pl.Path, pl.Path] = None,
        network: str = None,
        privileged: bool = False,
        prefix_command_args: List[str] = None,
        command_args: List[str] = None,
    ):
        self.name = name
        self.rm = rm
        self.ports = ports or {}
        self.volumes = volumes or {}
        self.network = network
        self.privileged = privileged
        self.prefix_command_args = prefix_command_args or []
        self.command = command_args or []

        self.image = image

        self._created = False
        self.host_ports = {}

    def run(
        self,
        interactive: bool = False,
    ):

        cmd_args = [
            *self.prefix_command_args,
            "docker",
            "run",
            f"--name={self.name}",
        ]

        if interactive:
            cmd_args.append("-i")
        else:
            cmd_args.append("-d")

        if self.rm:
            cmd_args.append("--rm")

        if self.privileged:
            cmd_args.append("--privileged")

        if self.network:
            cmd_args.append(
                f"--network={self.network}"
            )

        for host_port, container_port in self.ports.items():
            if host_port != 0:
                self.host_ports[container_port] = host_port

            cmd_args.append(f"-p={host_port}:{container_port}")

        for src_path, dest_path in self.volumes.items():
            cmd_args.append(f"--volume={src_path}:{dest_path}")

        cmd_args.append(self.image)
        cmd_args.extend(self.command)

        subprocess.run(
            cmd_args,
            check=True,
        )

    def get_host_port(self, container_port: str):

        host_port = self.host_ports.get(container_port)

        if host_port:
            return host_port

        host_port = get_docker_container_host_port(
            container_name=self.name,
            container_port=container_port,
            prefix_cmd_args=self.prefix_command_args,
        )

        self.host_ports[container_port] = host_port

        return host_port

    def remove(self, force: bool = False):
        delete_container(
            container_name=self.name,
            force=force,
        )


