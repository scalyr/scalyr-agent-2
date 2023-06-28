import abc
import collections
import dataclasses
import json
import pathlib as pl
import argparse
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import os
import enum
import signal
from typing import Dict, List, Any


from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch
from agent_build_refactored.tools.run_in_ec2.remote_docker_buildx_builder.buildx_builder_ami import get_buildx_builder_ami_image
from agent_build_refactored.tools.run_in_ec2.boto3_tools import create_and_deploy_ec2_instance, AWSSettings, EC2DistroImage

AGENT_BUILD_OUTPUT_PATH = SOURCE_ROOT / "agent_build_output"

BUILDKIT_VERSION = "v0.11.6"

USE_GHA_CACHE = bool(os.environ.get("USE_GHA_CACHE"))


@dataclasses.dataclass
class BuildxBuilderWrapper:
    name: str
    architecture: CpuArch

    @abc.abstractmethod
    def create_builder(self):
        pass

    def is_builder_exists(self):
        pass
        # try:
        #     subprocess.run(
        #         ["docker", "buildx", "rm", "-f", self.name],
        #         check=True,
        #         capture_output=True,
        #         timeout=60,
        #     )
        # except subprocess.SubprocessError as e:
        #     stderr = e.stderr.decode()
        #     if stderr == f'ERROR: no builder "{self.name}" found\n':
        #         return False
        #
        #     raise Exception(f"Can not inspect builder. Stderr: {stderr}")


    @property
    def _bake_common_cmd_args(self):
        return [
            "docker",
            "buildx",
            "bake",
        ]

    def bake(self, bake_file_path: pl.Path):
        subprocess.run(
            [
                *self._bake_common_cmd_args,
                "-f",
                str(bake_file_path),
                "--builder",
                self.name,
            ],
            env={"BUILDKIT_INLINE_CACHE": "0", **os.environ},
            check=True
        )

    def bake_or_stop_on_cache_miss(self, bake_file_path: pl.Path):
        process = subprocess.Popen(
            [
                *self._bake_common_cmd_args,
                "-f",
                str(bake_file_path),
                "--builder",
                self.name,
            ],
            stderr=subprocess.PIPE,
        )

        def _real_line():
            raw_line = process.stderr.readline().decode()

            if not raw_line:
                return None

            return raw_line.strip()

        def _check_if_run_command_is_missed_cache(line: str):
            if line == f"#{number} CACHED":
                return False

            if re.match(rf"#{number} sha256:[\da-fA-F]+ .*", line):
                return False

            if re.match(rf"#{number} extracting sha256:[\da-fA-F]+ .*", line):
                return False

            return True

        is_missed_cache = False

        while True:
            line = _real_line()

            if line is None:
                break

            print(line, file=sys.stderr)

            m = re.match(r"#(\d+) \[[^]]+] RUN .*", line)

            if not m:
                continue

            number = m.group(1)
            line = _real_line()

            is_missed_cache = _check_if_run_command_is_missed_cache(line=line)
            print(line, file=sys.stderr)

            if is_missed_cache:
                break

        if is_missed_cache:
            import psutil

            pr = psutil.Process(process.pid)

            def _get_child_process(process: psutil.Process):
                result = []
                for child in process.children():
                    result.append(child)
                    result.extend(_get_child_process(process=child))

                return result

            all_children = _get_child_process(process=pr)

            process.terminate()
            for c in all_children:
                c.terminate()

            process.wait()
        else:
            process.wait()
            if process.returncode != 0:
                raise Exception(f"Build command finished with error code {process.returncode}.")

        while True:
            raw_line = process.stderr.readline()
            try:
                line = raw_line.decode(errors="replace")
            except:
                print(f"Line: {raw_line}")
                raise

            if not line:
                break

            print(line.strip(), file=sys.stderr)

        return is_missed_cache


def docker_build_or_stop_on_cache_miss(cmd_args: List[str]):
    process = subprocess.Popen(
        [
            *cmd_args,
        ],
        stderr=subprocess.PIPE,
    )

    all_lines = []

    def _real_line(decode_errors="strict"):
        raw_line = process.stderr.readline().decode(
            errors=decode_errors
        )

        if not raw_line:
            return None

        stripped_line = raw_line.strip()

        all_lines.append(stripped_line)

        return stripped_line

    def _check_if_run_command_is_missed_cache(line: str):
        if line == f"#{number} CACHED":
            return False

        if re.match(rf"#{number} sha256:[\da-fA-F]+ .*", line):
            return False

        if re.match(rf"#{number} extracting sha256:[\da-fA-F]+ .*", line):
            return False

        return True

    is_missed_cache = False

    while True:
        line = _real_line()

        if line is None:
            break

        print(line, file=sys.stderr)

        m = re.match(r"#(\d+) \[[^]]+] RUN .*", line)

        if not m:
            continue

        number = m.group(1)
        line = _real_line()

        is_missed_cache = _check_if_run_command_is_missed_cache(line=line)
        print(line, file=sys.stderr)

        if is_missed_cache:
            break

    def _print_rest_of_the_process_oupput():
        while True:
            line = _real_line(decode_errors="replace")
            if not line:
                break
        print(line.strip(), file=sys.stderr)

    def _raise_process_error():
        output = "\n".join(all_lines)
        raise Exception(f"Command {cmd_args} ended with error {process.returncode}. Stderr: {output}")

    if process.poll() is not None:
        if process.returncode == 0:
            _print_rest_of_the_process_oupput()
            return
        else:
            _raise_process_error()

    if is_missed_cache:
        import psutil

        pr = psutil.Process(process.pid)

        def _get_child_process(process: psutil.Process):
            result = []
            for child in process.children():
                result.append(child)
                result.extend(_get_child_process(process=child))

            return result

        all_children = _get_child_process(process=pr)

        process.terminate()
        for c in all_children:
            c.terminate()

        process.wait()
    else:
        process.wait()
        if process.returncode != 0:
            _raise_process_error()

    _print_rest_of_the_process_oupput()

    return is_missed_cache

@dataclasses.dataclass
class LocalBuildxBuilderWrapper(BuildxBuilderWrapper):

    def create_builder(self):

        return

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

        config_path = AGENT_BUILD_OUTPUT_PATH / "config.toml"

        config_path.write_text(
            """
[worker.oci]
max-parallelism = 1
"""
        )

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
            "--bootstrap",
            "--config",
            str(config_path)

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

        subprocess.run(
            "docker ps -a",
            shell=True,
            check=True
        )

        subprocess.run(
            [
                *cmd_args,
                "docker",
                "inspect",
                container_name,
                "--help"
            ],
            check=True,
        )

        subprocess.run(
            [
                *cmd_args,
                "docker",
                "inspect",
                container_name
            ],
            check=True,
        )

        inspect_result = subprocess.run(
            [
                *cmd_args,
                "docker",
                "inspect",
                "--format",
                "json",
                container_name
            ],
            check=True,
            capture_output=True,
        )

        print("!!!!")
        print(inspect_result.stdout.decode())
        print(inspect_result.stderr.decode())
        print("2222")
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


#_existing_builders: Dict[CpuArch, Dict[str, RemoteBuildxBuilderWrapper]] = collections.defaultdict(dict)
_existing_builders: Dict[CpuArch, RemoteBuildxBuilderWrapper] = {}


class BuilderStep:
    def __init__(
        self,
        name: str,
        context: pl.Path,
        dockerfile_path: pl.Path,
        build_contexts: List['BuilderStep'] = None,
        build_args: Dict[str, str] = None,
        platform: CpuArch = CpuArch.x86_64,
        cache: bool = True,
    ):

        self.name = name
        self.platform = platform
        self.build_context = context
        self.dockerfile_path = dockerfile_path
        self.build_contexts = build_contexts or []
        self.build_args = build_args or {}
        self.cache = cache

    @property
    def as_bake_target(self):

        cache_path = AGENT_BUILD_OUTPUT_PATH / "cache" / self.name
        cache_path = AGENT_BUILD_OUTPUT_PATH / "cache"

        mode = "min"

        #cache_sources = [f"type=local,mode=min,tag={self.name},src={cache_path}"]
        cache_sources = [f"type=local,mode={mode},src={cache_path}"]
        contexts = {}

        for step in self.build_contexts:
            contexts[step.name] = f"target:{step.name}"

            src = str(AGENT_BUILD_OUTPUT_PATH / "cache" / step.name)
            #cache_sources.append(f"type=local,mode=min,tag={step.name},src={src}")
            #cache_sources.append(f"type=local,mode={mode},src={src}")

        target = {
            "context": str(self.build_context),
            "dockerfile": str(self.dockerfile_path),
            "args": {
                "BUILDKIT_INLINE_CACHE":"1",
                **self.build_args,
            },
            "cache-from": cache_sources,
            # ignore-error=true
            #"cache-to": [f"type=local,mode=min,tag={self.name},dest={cache_path}"],
            "cache-to": [f"type=local,mode={mode},dest={cache_path}"],
            #"output": [f"type=local,dest={AGENT_BUILD_OUTPUT_PATH / 'output' / self.name}"]
        }

        if self.platform:
            target["platforms"] = [self.platform.as_docker_platform()]

        if contexts:
            target["contexts"] = contexts
        return target

    def get_all_dependency_steps(self) -> List['BuilderStep']:
        result = [self]

        for step in self.build_contexts:
            result.extend(step.get_all_dependency_steps())

        return result

    # def run(
    #     self,
    # ):
    #     result = {}
    #     all_targets = {}
    #     default_group_targets = []
    #
    #     for step in self.get_all_dependency_steps():
    #         all_targets[step.name] = step.as_bake_target
    #         default_group_targets.append(step.name)
    #
    #     AGENT_BUILD_OUTPUT_PATH.mkdir(exist_ok=True, parents=True)
    #
    #     for path in AGENT_BUILD_OUTPUT_PATH.glob("bake_*.json"):
    #         path.unlink()
    #
    #     bake_file_path = AGENT_BUILD_OUTPUT_PATH / f"bake_{self.name}_{str(int(time.time()))}.json"
    #
    #     result["target"] = all_targets
    #
    #     #result["target"]["default"] = result["target"].pop("build_xz")
    #
    #     a=10
    #
    #     result["group"] = {
    #         "default": {
    #             "targets": default_group_targets,
    #             #"targets": [self.name]
    #         }
    #     }
    #
    #     bake_file_json = json.dumps(
    #         result,
    #         sort_keys=True,
    #         indent=4
    #     )
    #     bake_file_path.write_text(bake_file_json)
    #
    #     machine_name = platform.machine()
    #     if machine_name in ["x86_64"]:
    #         current_machine_arch = CpuArch.x86_64
    #     elif machine_name in ["aarch64"]:
    #         current_machine_arch = CpuArch.AARCH64
    #     elif machine_name in ["armv7l"]:
    #         current_machine_arch = CpuArch.ARMV7
    #     else:
    #         raise Exception(f"Unknown uname machine {machine_name}")
    #
    #     local_builder_info = self.prepare_buildx_builders(local=True)
    #
    #     if self.platform == current_machine_arch:
    #         return
    #
    #     repeat_in_remote = local_builder_info.bake_or_stop_on_cache_miss(bake_file_path=bake_file_path)
    #
    #     if repeat_in_remote:
    #         remote_builder_info = self.prepare_buildx_builders(local=False)
    #         remote_builder_info.bake(bake_file_path=bake_file_path)
    #
    #
    #
    #
    #     a=10

    @property
    def oci_layout(self):
        return AGENT_BUILD_OUTPUT_PATH / "oci" / self.name

    @property
    def output_dir(self):
        return AGENT_BUILD_OUTPUT_PATH / "output" / self.name

    @property
    def oci_layout_tarball(self):
        return self.oci_layout.parent / f"{self.oci_layout.name}.tar"

    def _cleanup(self):
        if self.oci_layout.parent.exists():
            shutil.rmtree(self.oci_layout.parent)
        self.oci_layout.parent.mkdir(parents=True)

        if self.output_dir.parent.exists():
            shutil.rmtree(self.output_dir.parent)
        self.output_dir.parent.mkdir(parents=True)

    def run(self,
            output: str = None,
            tags: List[str] = None,
        ):

        for step in self.build_contexts:
            step.run_and_output_in_oci_tarball(initial=False)

        machine_name = platform.machine()
        if machine_name in ["x86_64"]:
            current_machine_arch = CpuArch.x86_64
        elif machine_name in ["aarch64"]:
            current_machine_arch = CpuArch.AARCH64
        elif machine_name in ["armv7l"]:
            current_machine_arch = CpuArch.ARMV7
        else:
            raise Exception(f"Unknown uname machine {machine_name}")

        local = False
       #local_builder_info = self.prepare_buildx_builders(local=True)

        if self.platform != current_machine_arch:
            return

        cache_path = AGENT_BUILD_OUTPUT_PATH / "cache" / self.name
        #cache_path = AGENT_BUILD_OUTPUT_PATH / "cache"

        cmd_args = [
            "docker",
            "buildx",
            "build",
            "-f",
            str(self.dockerfile_path),
        ]

        if self.cache:

            if USE_GHA_CACHE:
                cmd_args.extend([
                    "--cache-from",
                    f"type=gha,scope={self.name}",
                    "--cache-to",
                    f"type=gha,scope={self.name}",
                ])
            else:
                cache_type = "local"
                cmd_args.extend([
                    "--cache-from",
                    f"type={cache_type},src={cache_path}",
                    "--cache-to",
                    f"type={cache_type},dest={cache_path}",
                ])

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

        for name, value in self.build_args.items():
            cmd_args.extend([
                "--build-arg",
                f"{name}={value}",
            ])

        for step in self.build_contexts:
            cmd_args.extend([
                "--build-context",
                f"{step.name}=oci-layout://{step.oci_layout}"
            ])

        cmd_args.append(
            str(self.build_context)
        )

        if local:
            subprocess.run(
                cmd_args,
                check=True
            )

        else:
            remote_builder_info = self.prepare_remote_buildx_builders()
            cmd_args.extend([
                "--builder",
                remote_builder_info.name,
            ])
            subprocess.run(
                cmd_args,
                check=True
            )


        a=10

    def run_and_output_in_oci_tarball(self, initial: bool = True, tarball_path: pl.Path = None):
        if initial:
            self._cleanup()

        if not self.oci_layout.exists():
            self.run(output=f"type=oci,dest={self.oci_layout_tarball}")

            with tarfile.open(self.oci_layout_tarball) as tar:
                    tar.extractall(path=self.oci_layout)

        if tarball_path:
            shutil.copy(self.oci_layout_tarball, tarball_path)

    def run_and_output_in_loacl_directory(self, initial: bool = True, output_dir: pl.Path = None):
        if initial:
            self._cleanup()
        output_dir = output_dir or self.output_dir
        self.run(output=f"type=local,dest={output_dir}")

    def run_and_output_in_docker(self, initial: bool = True, tags: List[str] = None):
        if initial:
            self._cleanup()

        if tags is None:
            tags = [self.name]

        self.run(output=f"type=docker", tags=tags)

    def prepare_remote_buildx_builders(
        self
    ):

        global _existing_builders

        builder_name = f"{BUILDER_NAME}_{self.platform.value}"

        info = _existing_builders.get(self.platform)

        if info:
            return info

        info = DockerBackedBuildxBuilderWrapper(
            name=builder_name,
            architecture=self.platform
        )

        info.create_builder()

        _existing_builders[self.platform] = info

        return info


        # try:
        #     subprocess.run(
        #         ["docker", "buildx", "rm", "-f", builder_name],
        #         check=True,
        #         capture_output=True,
        #         timeout=60,
        #     )
        # except subprocess.SubprocessError as e:
        #     stderr = e.stderr.decode()
        #     if stderr != f'ERROR: no builder "{builder_name}" found\n':
        #         raise Exception(f"Can not inspect builder. Stderr: {stderr}")

        if local:
            info = LocalBuildxBuilderWrapper(
                name=builder_name,
                architecture=self.platform
            )
            # info = DockerBackedBuildxBuilderWrapper(
            #     name=builder_name,
            #     architecture=self.platform
            # )

            # info = EC2BackedRemoteBuildxBuilderWrapper(
            #     name=builder_name,
            #     architecture=self.platform,
            # )
        else:

            info = EC2BackedRemoteBuildxBuilderWrapper(
                name=builder_name,
                architecture=self.platform,
            )

        info.create_builder()

        _existing_builders[self.platform][locality] = info

        return info


BUILDER_NAME = "agent_cicd"


_ARM_IMAGE = EC2DistroImage(
    image_id="ami-0e2b332e63c56bcb5",
    image_name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
    short_name="ubuntu2204_ARM",
    size_id="c7g.medium",
    ssh_username="ubuntu",
)

DOCKER_EC2_BUILDERS = {
    CpuArch.x86_64: _ARM_IMAGE,
    CpuArch.ARMV7: _ARM_IMAGE
}

_BUILDX_BUILDER_PORT = "1234"


# def create_node_in_ec2(architecture: CpuArch):
#     base_ec2_image = DOCKER_EC2_BUILDERS[architecture]
#     aws_settings = AWSSettings.create_from_env()
#     boto3_session = aws_settings.create_boto3_session()
#     image = get_buildx_builder_ami_image(
#         architecture=architecture,
#         base_ec2_image=base_ec2_image,
#         boto3_session=boto3_session,
#         aws_settings=aws_settings,
#
#     )
#
#     ec2_image = EC2DistroImage(
#         image_id=image.id,
#         image_name=image.name,
#         short_name=base_ec2_image.short_name,
#         size_id=base_ec2_image.size_id,
#         ssh_username=base_ec2_image.ssh_username,
#     )
#
#     instance = create_and_deploy_ec2_instance(
#         boto3_session=boto3_session,
#         ec2_image=ec2_image,
#         name_prefix="remote_docker",
#         aws_settings=aws_settings,
#         root_volume_size=32,
#     )
#
#     try:
#         ssh_host = f"{ec2_image.ssh_username}@{instance.public_ip_address}"
#         container_name = "ssh"
#
#         subprocess.run(
#             ["docker", "rm", "-f", container_name],
#             check=True
#         )
#
#         mapped_private_key_path = pl.Path("/tmp/private.pem")
#         subprocess.run(
#             [
#                 "docker",
#                 "run",
#                 "-d",
#                 "--rm",
#                 "--name",
#                 container_name,
#                 "-p",
#                 "1234:1234",
#                 "-v",
#                 f"{aws_settings.private_key_path}:${mapped_private_key_path}",
#                 "kroniak/ssh-client",
#                 "ssh", "-i", "/tmp/private.pem", "-o", "StrictHostKeyChecking=no", "-N", "-L",
#                 "0.0.0.0:1234:localhost:1234", ssh_host
#             ],
#             check=True
#         )
#
#         builder_info = EC2BackedBuilderInfo(
#             architecture=architecture,
#             container_name=container_name
#             # ec2_instance=instance,
#             # ssh_container_name=container_name,
#             # ssh_host=ssh_host,
#             # ssh_container_mapped_private_key_path=mapped_private_key_path,
#         )
#
#         return builder_info
#
#     except Exception:
#         instance.terminate()
#         raise







# class Builder:
#     def __init__(
#         self,
#         base_environment: BuilderStep,
#         required_steps: List[BuilderStep],
#     ):
#         self._required_steps = required_steps
#
#     def _generate_bake_dict(self):
#         result = {}
#
#         all_targets = {}
#         default_group_targets = []
#         for step in self._required_steps:
#             for dep_step in step.get_all_dependency_steps():
#                 all_targets[dep_step.name] = dep_step.as_bake_target
#                 default_group_targets.append(dep_step.name)
#
#
#         combine_outputs_target = {
#
#         }
#
#         result["target"] = all_targets
#
#         result["group"] = {
#             "default": {
#                 "targets": default_group_targets,
#             }
#         }
#
#         return result
#
#     def run(self):
#
#         bake_dict = self._generate_bake_dict()
#
#         bake_file_path = AGENT_BUILD_OUTPUT_PATH / "bake.json"
#
#         bake_json = json.dumps(bake_dict, sort_keys=True, indent=4)
#         bake_file_path.write_text(bake_json)
#         subprocess.run(
#             [
#                 "docker",
#                 "buildx",
#                 "bake",
#                 "-f",
#                 str(bake_file_path),
#             ],
#             check=True
#         )
#
#     def main(self, args: List[str] = None):
#         pass

