import subprocess
import threading
import pathlib as pl
from typing import List, Optional, Dict

from agent_build_refactored.tools.docker.common import delete_container, ContainerWrapper


class EC2InstanceWrapper:
    def __init__(
        self,
        boto3_instance,
        ssh_client_docker_image: str,
        private_key_path: pl.Path,
        username: str
    ):
        self.id = boto3_instance.id.lower()
        self.boto3_instance = boto3_instance
        self.ssh_client_docker_image = ssh_client_docker_image
        self.private_key_path = private_key_path
        self.username = username

        #self._ssh_container: Optional[ContainerWrapper] = None
        self._ssh_tunnel_containers: Dict[int, ContainerWrapper] = {}

        self._ssh_client_container_name = f"ec2_instance_{boto3_instance.id}_ssh_client"
        self._ssh_client_container_host_port = f"ec2_instance_{boto3_instance.id}_ssh_client"
        self._ssh_client_container_in_docker_private_key_path = pl.Path("/tmp/mounts/private_key.pem")

        #self.ssh_client_container_thread = threading.Thread(target=self.start_ssh_client_container)
        #self.ssh_client_container_thread.start()

        self._ssh_container: Optional[ContainerWrapper] = self.start_ssh_client_container()

        # self._ssh_containers: List[ContainerWrapper] = []
        #
        # self._ssh_container = self.start_ssh_client_container()

    def start_ssh_client_container(
        self,
    ):

        delete_container(
            self._ssh_client_container_name
        )

        # if port:
        #     other_kwargs["ports"] = f"{port}/{port_protocol}"

        container = ContainerWrapper(
            name=self._ssh_client_container_name,
            image=self.ssh_client_docker_image,
            volumes={self.private_key_path: self._ssh_client_container_in_docker_private_key_path},
            rm=True,
            command_args=[
                "/bin/bash",
                "-c",
                "while true; do sleep 86400; done"
            ],
        )

        container.run()

        return container



        a=10
        # subprocess.run(
        #     [
        #         "docker",
        #         "run",
        #         #"-i",
        #         "-d",
        #         f"--name={self._ssh_client_container_name}",
        #         "--net=host",
        #         f"--volume={self.private_key_path}:{self._ssh_client_container_in_docker_private_key_path}",
        #         self.ssh_client_docker_image,
        #         "/bin/bash",
        #         "-c",
        #         "while true; do sleep 86400; done"
        #     ],
        #     check=True,
        # )

    @property
    def ssh_hostname(self):
        return f"{self.username}@{self.boto3_instance.public_ip_address}"

    @property
    def _common_ssh_options(self):
        return [
            "-i",
            str(self._ssh_client_container_in_docker_private_key_path),
            "-o",
            "StrictHostKeyChecking=no",
            self.ssh_hostname,
        ]

    @property
    def common_ssh_command_args(self):
        return [
            "docker",
            "exec",
            "-i",
            self._ssh_container.name,
            "ssh",
            *self._common_ssh_options
        ]

    def open_ssh_tunnel(
        self,
        remote_port: int,
        local_port: int = None
    ):

        local_port = local_port or remote_port
        full_local_port = f"{local_port}/tcp"

        container = ContainerWrapper(
            name=f"{self.id}_{local_port}-{remote_port}",
            image=self.ssh_client_docker_image,
            rm=False,
            ports={0: full_local_port},
            volumes={self.private_key_path: self._ssh_client_container_in_docker_private_key_path},
            command_args=[
                "ssh",
                *self._common_ssh_options,
                "-N",
                "-L",
                f"0.0.0.0:{local_port}:localhost:{remote_port}",
            ]
        )

        container.run(interactive=False)

        host_port = container.get_host_port(container_port=full_local_port)

        self._ssh_tunnel_containers[host_port] = container

        return host_port

        # subprocess.run(
        #     [
        #         "docker",
        #         "exec",
        #         "-d",
        #         self._ssh_client_container_name,
        #         "ssh",
        #         "-i",
        #         str(self._ssh_client_container_in_docker_private_key_path),
        #         "-N",
        #         "-L",
        #         f"0.0.0.0:{local_port}:localhost:{remote_port}",
        #         self.ssh_hostname,
        #     ],
        #     check=True
        # )


    def terminate(self):
        delete_container(
            container_name=self._ssh_client_container_name
        )

        if self._ssh_container:
            self._ssh_container.remove(force=True)

        for container in self._ssh_tunnel_containers.values():
            container.remove(force=True)
        #self.ssh_client_container_thread.join(timeout=20)

        self.boto3_instance.terminate()


