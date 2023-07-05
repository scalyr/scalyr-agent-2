import abc
import dataclasses
import json
import os
import pathlib as pl
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from typing import List, Any, Union, Dict

from agent_build_refactored.tools.constants import CpuArch, AGENT_BUILD_OUTPUT_PATH


@dataclasses.dataclass
class BuildxBuilderWrapper:
    name: str

    @abc.abstractmethod
    def create_builder(self):
        pass

    # def bake_or_stop_on_cache_miss(self, bake_file_path: pl.Path):
    #     process = subprocess.Popen(
    #         [
    #             *self._bake_common_cmd_args,
    #             "-f",
    #             str(bake_file_path),
    #             "--builder",
    #             self.name,
    #         ],
    #         stderr=subprocess.PIPE,
    #     )
    #
    #     def _real_line():
    #         raw_line = process.stderr.readline().decode()
    #
    #         if not raw_line:
    #             return None
    #
    #         return raw_line.strip()
    #
    #     def _check_if_run_command_is_missed_cache(line: str):
    #         if line == f"#{number} CACHED":
    #             return False
    #
    #         if re.match(rf"#{number} sha256:[\da-fA-F]+ .*", line):
    #             return False
    #
    #         if re.match(rf"#{number} extracting sha256:[\da-fA-F]+ .*", line):
    #             return False
    #
    #         return True
    #
    #     is_missed_cache = False
    #
    #     while True:
    #         line = _real_line()
    #
    #         if line is None:
    #             break
    #
    #         print(line, file=sys.stderr)
    #
    #         m = re.match(r"#(\d+) \[[^]]+] RUN .*", line)
    #
    #         if not m:
    #             continue
    #
    #         number = m.group(1)
    #         line = _real_line()
    #
    #         is_missed_cache = _check_if_run_command_is_missed_cache(line=line)
    #         print(line, file=sys.stderr)
    #
    #         if is_missed_cache:
    #             break
    #
    #     if is_missed_cache:
    #         import psutil
    #
    #         pr = psutil.Process(process.pid)
    #
    #         def _get_child_process(process: psutil.Process):
    #             result = []
    #             for child in process.children():
    #                 result.append(child)
    #                 result.extend(_get_child_process(process=child))
    #
    #             return result
    #
    #         all_children = _get_child_process(process=pr)
    #
    #         process.terminate()
    #         for c in all_children:
    #             c.terminate()
    #
    #         process.wait()
    #     else:
    #         process.wait()
    #         if process.returncode != 0:
    #             raise Exception(f"Build command finished with error code {process.returncode}.")
    #
    #     while True:
    #         raw_line = process.stderr.readline()
    #         try:
    #             line = raw_line.decode(errors="replace")
    #         except:
    #             print(f"Line: {raw_line}")
    #             raise
    #
    #         if not line:
    #             break
    #
    #         print(line.strip(), file=sys.stderr)
    #
    #     return is_missed_cache


@dataclasses.dataclass
class LocalBuildxBuilderWrapper(BuildxBuilderWrapper):

    def create_builder(self):

        try:
            result = subprocess.run(
                [
                    "docker", "buildx", "ls"
                ],
                check=True,
                capture_output=True
            )
        except subprocess.SubprocessError as e:
            print(e.stderr.decode(), file=sys.stderr)
            raise

        r = result.stdout.decode()
        a=10

        try:
            subprocess.run(
                ["docker", "buildx", "rm", "-f", self.name],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.SubprocessError as e:
            stderr = e.stderr.decode()
            if stderr != f'ERROR: no builder "{self.name}" found\n':
                raise Exception(f"Can not inspect builder. Stderr: {stderr}")

        create_builder_args = [
            "docker",
            "buildx",
            "create",
            "--name",
            self.name,
            "--driver",
            "docker-container",
            "--driver-opt",
            f"image=moby/buildkit:{BUILDKIT_VERSION}",
            "--driver-opt",
            "network=host",
            "--bootstrap",

        ]

        subprocess.run(
            create_builder_args,
            check=True
        )


@dataclasses.dataclass
class RemoteBuildxBuilderWrapper(BuildxBuilderWrapper):
    host_port: int = dataclasses.field(init=False)
    container_name: str = dataclasses.field(init=False)

    def create_builder(self):

        try:
            subprocess.run(
                ["docker", "buildx", "rm", "-f", self.name],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except subprocess.SubprocessError as e:
            stderr = e.stderr.decode()
            if stderr != f'ERROR: no builder "{self.name}" found\n':
                raise Exception(f"Can not inspect builder. Stderr: {stderr}")

        self.host_port = self.start_builder_container()

        create_builder_args = [
            "docker",
            "buildx",
            "create",
            "--name",
            self.name,
            "--driver",
            "remote",
            "--bootstrap",
            f"--platform={self.architecture.as_docker_platform()}",
            f"tcp://localhost:{self.host_port}",
        ]

        subprocess.run(
            create_builder_args,
            check=True
        )

    @property
    @abc.abstractmethod
    def docker_common_cmd_args(self) -> List[str]:
        return []

    def start_builder_container(self):

        self.container_name = self.name
        subprocess.run(
            [
                *self.docker_common_cmd_args,
                "docker",
                "rm",
                "-f",
                self.container_name,
            ],
            check=True
        )

        # subprocess.run(
        #     [
        #         *self.docker_common_cmd_args,
        #         "docker",
        #         "create",
        #         "--rm",
        #         f"--name={self.container_name}",
        #         "--privileged",
        #         "-p",
        #         f"0:{_BUILDX_BUILDER_PORT}/tcp",
        #         f"moby/buildkit:{BUILDKIT_VERSION}",
        #         "--addr", f"tcp://0.0.0.0:{_BUILDX_BUILDER_PORT}",
        #     ],
        #     check=True
        # )


        # subprocess.run(
        #     [
        #         *self.docker_common_cmd_args,
        #         "docker",
        #         "cp",
        #         f"{self.container_name}:/tmp/config.toml"
        #     ],
        #     check=True
        # )

        subprocess.run(
            [
                *self.docker_common_cmd_args,
                "docker",
                "run",
                "-d",
                #"-i",
                "--rm",
                f"--name={self.container_name}",
                f"--platform={self.architecture.as_docker_platform()}",
                "--privileged",
                "-p",
                f"0:{_BUILDX_BUILDER_PORT}/tcp",
                f"moby/buildkit:{BUILDKIT_VERSION}",
                "--addr", f"tcp://0.0.0.0:{_BUILDX_BUILDER_PORT}",
            ],
            check=True
        )

        # subprocess.run(
        #     [
        #         *self.docker_common_cmd_args,
        #         "docker",
        #         "start",
        #         self.container_name
        #     ],
        #     check=True
        # )

        host_port = self.get_host_port(container_name=self.container_name, cmd_args=self.docker_common_cmd_args)
        return host_port

    @staticmethod
    def get_host_port(container_name: str, cmd_args: List[str] = None):
        cmd_args = cmd_args or []

        inspect_result = subprocess.run(
            [
                *cmd_args,
                "docker",
                "inspect",
                container_name
            ],
            check=True,
            capture_output=True,
        )

        inspect_infos = json.loads(
            inspect_result.stdout.decode()
        )
        container_info = inspect_infos[0]
        host_port = container_info["NetworkSettings"]["Ports"][f"{_BUILDX_BUILDER_PORT}/tcp"][0]["HostPort"]
        return host_port

    def close(self):
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            check=True
        )


@dataclasses.dataclass
class DockerBackedBuildxBuilderWrapper(RemoteBuildxBuilderWrapper):
    @property
    def docker_common_cmd_args(self) -> List[str]:
        return []


@dataclasses.dataclass
class EC2BackedRemoteBuildxBuilderWrapper(RemoteBuildxBuilderWrapper):
    ec2_instance: Any = dataclasses.field(init=False)
    ssh_container_name: str = dataclasses.field(init=False)
    ssh_host: str = dataclasses.field(init=False)
    ssh_container_mapped_private_key_path: pl.Path = dataclasses.field(default=pl.Path("/tmp/private.pem"), init=False)

    def start_builder_container(self):

        from agent_build_refactored.tools.run_in_ec2.remote_docker_buildx_builder.buildx_builder_ami import \
            get_buildx_builder_ami_image
        from agent_build_refactored.tools.run_in_ec2.boto3_tools import create_and_deploy_ec2_instance, AWSSettings, \
            EC2DistroImage

        _ARM_IMAGE = EC2DistroImage(
            image_id="ami-0e2b332e63c56bcb5",
            image_name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
            short_name="ubuntu2204_ARM",
            size_id="c7g.medium",
            ssh_username="ubuntu",
        )

        DOCKER_EC2_BUILDERS = {
            CpuArch.x86_64: _ARM_IMAGE,
            CpuArch.AARCH64: _ARM_IMAGE,
            CpuArch.ARMV7: _ARM_IMAGE
        }

        base_ec2_image = DOCKER_EC2_BUILDERS[self.architecture]
        aws_settings = AWSSettings.create_from_env()
        boto3_session = aws_settings.create_boto3_session()
        image = get_buildx_builder_ami_image(
            architecture=self.architecture,
            base_ec2_image=base_ec2_image,
            boto3_session=boto3_session,
            aws_settings=aws_settings,

        )

        ec2_image = EC2DistroImage(
            image_id=image.id,
            image_name=image.name,
            short_name=base_ec2_image.short_name,
            size_id=base_ec2_image.size_id,
            ssh_username=base_ec2_image.ssh_username,
        )

        self.ec2_instance = create_and_deploy_ec2_instance(
            boto3_session=boto3_session,
            ec2_image=ec2_image,
            name_prefix="remote_docker",
            aws_settings=aws_settings,
            root_volume_size=32,
        )

        try:
            self.ssh_host = f"{ec2_image.ssh_username}@{self.ec2_instance.public_ip_address}"
            self.ssh_container_name = "ssh"

            subprocess.run(
                ["docker", "rm", "-f", self.ssh_container_name],
                check=True
            )

            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    self.ssh_container_name,
                    "-p",
                    f"0:{_BUILDX_BUILDER_PORT}/tcp",
                    "-v",
                    f"{aws_settings.private_key_path}:{self.ssh_container_mapped_private_key_path}",
                    "kroniak/ssh-client",
                    "sleep",
                    "99999"
                ],
                check=True
            )

            host_port = self.get_host_port(container_name=self.ssh_container_name)

            builder_container_host_port = super(EC2BackedRemoteBuildxBuilderWrapper, self).start_builder_container()

            subprocess.run(
                [
                    "docker",
                    "exec",
                    "-d",
                    self.ssh_container_name,
                    "ssh", "-i", str(self.ssh_container_mapped_private_key_path), "-N", "-L",
                    f"0.0.0.0:{_BUILDX_BUILDER_PORT}:localhost:{builder_container_host_port}", self.ssh_host
                ],
                check=True
            )

            return host_port

        except Exception:
            self.ec2_instance.terminate()
            raise

    def close(self):
        self.ec2_instance.terminate()

        subprocess.run(
            ["docker", "rm", "-f", self.ssh_container_name],
            check=True
        )

    @property
    def docker_common_cmd_args(self) -> List[str]:
        return [
            "docker",
            "exec",
            "-i",
            self.ssh_container_name,
            "ssh",
            "-i",
            str(self.ssh_container_mapped_private_key_path),
            "-o",
            "StrictHostKeyChecking=no",
            self.ssh_host
        ]


class BuilderCacheMissError(Exception):
    pass



BUILDER_NAME = "agent_cicd"
_BUILDX_BUILDER_PORT = "1234"
BUILDKIT_VERSION = "v0.11.6"
USE_GHA_CACHE = bool(os.environ.get("USE_GHA_CACHE"))

_BUILD_STEPS_OUTPUT_OCI_DIR = AGENT_BUILD_OUTPUT_PATH / "oci"
_BUILD_STEPS_OUTPUT_OUTPUT_DIR = AGENT_BUILD_OUTPUT_PATH / "output"


ALL_BUILDER_STEPS: Dict[str, 'BuilderStep'] = {}


class BuilderStep():
    def __init__(
        self,
        name: str,
        context: pl.Path,
        dockerfile: Union[str, pl.Path],
        platform: CpuArch,
        build_contexts: List['BuilderStep'] = None,
        build_args: Dict[str, str] = None,
        cache: bool = True,
        unique_name_suffix: str = None,
        local_dir_contexts: Dict[str, pl.Path] = None,
    ):

        unique_name_suffix = unique_name_suffix or ""
        self.name = name
        self.unique_name = f"{name}{unique_name_suffix}"
        self.id = f"{self.unique_name}_{platform.value}"
        self.platform = platform
        self.build_context = context

        if isinstance(dockerfile, pl.Path):
            self.dockerfile_content = dockerfile.read_text()
        else:
            self.dockerfile_content = dockerfile

        #self.dockerfile = dockerfile
        self.build_contexts = build_contexts or []
        self.build_args = build_args or {}
        self.cache = cache
        self.local_dir_contexts = local_dir_contexts or {}

        self.all_identifiers = {
            self.name,
            self.unique_name,
            self.id
        }

        self.oci_layout_ready = False
        self.local_output_ready = False

        self.fqdn = None


    @property
    def oci_layout(self):
        return _BUILD_STEPS_OUTPUT_OCI_DIR / self.id

    @property
    def oci_layout_tarball(self):
        return self.oci_layout.parent / f"{self.oci_layout.name}.tar"

    @property
    def output_dir(self):
        return _BUILD_STEPS_OUTPUT_OUTPUT_DIR / self.id

    def get_build_command_args(
            self,
            use_only_cache: bool
    ):
        cmd_args = [
            "docker",
            "buildx",
            "build",
            "--platform",
            self.platform.as_docker_platform(),
            "-f",
            "-",
        ]

        if self.cache:
            if USE_GHA_CACHE:
                cache_to_value = f"type=gha,scope={self.id}"
                cache_from_value = f"type=gha,scope={self.id}"
            else:
                cache_path = AGENT_BUILD_OUTPUT_PATH / "cache" / self.id
                cache_to_value = f"type=local,src={cache_path}"
                cache_from_value = f"type=local,dest={cache_path}"

            cmd_args.extend([
                "--cache-from",
                cache_from_value,
            ])

            if not use_only_cache:
                cmd_args.extend([
                    "--cache-to",
                    cache_to_value
                ])

        for name, value in self.build_args.items():
            cmd_args.extend([
                "--build-arg",
                f"{name}={value}",
            ])

        for step in self.build_contexts:
            for context_name in [step.name, step.unique_name, step.id]:
                cmd_args.extend([
                    "--build-context",
                    f"{context_name}=oci-layout://{step.oci_layout}"
                ])

        for name, path in self.local_dir_contexts.items():
            cmd_args.extend([
                "--build-context",
                f"{name}={path}"
            ])

        cmd_args.append(
            str(self.build_context)
        )

        return cmd_args

    def run(self,
            output: str = None,
            tags: List[str] = None,
            use_only_cache: bool = False,
            ):

        for step in self.build_contexts:
            step.run_and_output_in_oci_tarball(
                use_only_cache=use_only_cache,
            )

        machine_name = platform.machine()
        if machine_name.lower() in ["x86_64"]:
            current_machine_arch = CpuArch.x86_64
        elif machine_name.lower() in ["aarch64"]:
            current_machine_arch = CpuArch.AARCH64
        elif machine_name.lower() in ["armv7l"]:
            current_machine_arch = CpuArch.ARMV7
        else:
            raise Exception(f"Unknown uname machine {machine_name}")

        # if self.platform != current_machine_arch:
        #     return

        cmd_args = self.get_build_command_args(
            use_only_cache=use_only_cache
        )

        if output:
            cmd_args.extend([
                "--output",
                output,
            ])

        if tags:
            for tag in tags:
                cmd_args.extend([
                    "-t",
                    tag
                ])

        TEMPLATE  = """
FROM ubuntu:22.04 as cache_check
RUN apt update && apt install -y curl dnsutils
ARG d=3
ARG ERROR_MESSAGE
RUN echo -n "Can not continue." >> /tmp/error_mgx.txt
RUN echo " ${ERROR_MESSAGE}" >> /tmp/error_mgx.txt
RUN if curl -s localhost:8080 > /dev/null; then cat /tmp/error_mgx.txt ; exit 1; fi
RUN mkdir -p /tmp/empty

FROM scratch as cache_check2
COPY --from=cache_check /tmp/empty/. /
"""

        COPY_TEMPLATE = """
COPY --from 
        """

        dockerfile_content = self.dockerfile_content

        dockerfile_content = re.sub(
            r"(^FROM [^\n]+$)",
            r"\1\nCOPY --from=cache_check2 / /",
            dockerfile_content,
            flags=re.MULTILINE
        )

        dockerfile_content = re.sub(
            r"(^FROM [^\n]+$)",
            fr"{TEMPLATE}\n\1",
            dockerfile_content,
            count=1,
            flags=re.MULTILINE
        )

        nginc_container_name = "nginx"
        subprocess.run(
            ["docker", "rm", "-f", nginc_container_name],
            check=True
        )

        if use_only_cache:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    nginc_container_name,
                    "-p",
                    "8080:80",
                    "nginx"
                ],
                check=True
            )

        local = True

        if local:
            name = "local_agent_builder"
            builder_info = LocalBuildxBuilderWrapper(
                name=name,
            )
            builder_info.create_builder()
        else:
            builder_info = self.prepare_remote_buildx_builders(in_ec2=False)

        self.oci_layout.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                [
                    *cmd_args,
                    "--build-arg",
                    "ERROR_MESSAGE=This build is supposed to be rebuilt from cache",
                    "--builder",
                    builder_info.name,
                ],
                check=True,
                input=dockerfile_content.encode(),
                capture_output=True,
            )
        except subprocess.SubprocessError as e:
            full_no_cache_error_message = "Can not continue. This build is supposed to be rebuilt from cache"
            build_process_stderr = e.stderr.decode()
            print(build_process_stderr, file=sys.stderr)
            if use_only_cache and full_no_cache_error_message in build_process_stderr:
                raise BuilderCacheMissError(f"Can not find cache for '{self.name}' with flag 'fail_on_cache_miss' set.")
            raise

        if not use_only_cache:
            print(result.stderr.decode(errors="replace"), file=sys.stderr)


    def run_and_output_in_oci_tarball(
            self,
            #tarball_path: pl.Path = None,
            use_only_cache: bool = False,
            #no_cleanup: bool = False,
    ):
        # if not no_cleanup:
        #     _cleanup_output_dirs()

        if self.oci_layout_ready:
            return

        if self.oci_layout.exists():
            shutil.rmtree(self.oci_layout)

        if self.oci_layout_tarball.exists():
            self.oci_layout_tarball.unlink()

        self.run(
            output=f"type=oci,dest={self.oci_layout_tarball}",
            use_only_cache=use_only_cache,
        )

        with tarfile.open(self.oci_layout_tarball) as tar:
                tar.extractall(path=self.oci_layout)

        self.oci_layout_ready = True

        # if tarball_path:
        #     shutil.copy(self.oci_layout_tarball, tarball_path)

    def run_and_output_in_local_directory(
            self,
            output_dir: pl.Path = None,
            use_only_cache:bool = False,
            #no_cleanup: bool = False,

    ):
        # if not no_cleanup:
        #     _cleanup_output_dirs()

        if not self.local_output_ready:
            if self.output_dir.exists():
                shutil.rmtree(self.output_dir)

            self.run(
                output=f"type=local,dest={self.output_dir}",
                use_only_cache=use_only_cache,
            )
            self.local_output_ready = True

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                self.output_dir,
                output_dir,
                dirs_exist_ok=True,
                symlinks=True,
            )

    def run_and_output_in_docker(
            self,
            tags: List[str] = None,
            use_only_cache: bool = False,
            #no_cleanup: bool = False,
    ):
        if tags is None:
            tags = [self.name]

        self.run(
            output=f"type=docker", tags=tags,
            use_only_cache=use_only_cache,
        )

    def prepare_remote_buildx_builders(
        self,
        in_ec2: bool = False
    ):

        global _existing_builders

        if in_ec2:
            suffix = "ec2"
        else:
            suffix = "docker"

        builder_name = f"{BUILDER_NAME}_{self.platform.value}_{suffix}"

        info = _existing_builders.get(builder_name)

        if info:
            return info

        if in_ec2:
            info = EC2BackedRemoteBuildxBuilderWrapper(
                name=builder_name,
                architecture=self.platform
            )
            # info = DockerBackedBuildxBuilderWrapper(
            #     name=builder_name,
            #     architecture=self.platform
            # )
        else:
            info = DockerBackedBuildxBuilderWrapper(
                name=builder_name,
                architecture=self.platform
            )

        info.create_builder()

        _existing_builders[builder_name] = info

        return info

    def get_children(self) -> Dict[str, 'BuilderStep']:
        result = {}

        for step in self.build_contexts:
            result[step.id] = step
            result.update(step.get_children())

        return result

    def find_child_context_by_identifier(self, identifier):
        for context in self.build_contexts:
            if identifier == context.id:
                return context

            if identifier == context.unique_name:
                return context

            if identifier == context.name:
                return context

    @classmethod
    def create(cls, *args, **kwargs):
        global ALL_BUILDER_STEPS

        #module = kwargs.pop("module")

        new_instance = cls(*args, **kwargs)

        #fqdn = f"{module}.{new_instance.id}"

        instance = ALL_BUILDER_STEPS.get(new_instance.id)

        if instance is None:
            #new_instance.fqdn = fqdn
            ALL_BUILDER_STEPS[new_instance.id] = new_instance
            instance = new_instance

        return instance
