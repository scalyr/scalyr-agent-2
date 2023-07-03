import abc
import collections
import dataclasses
import functools
import importlib
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
import inspect
from typing import Dict, List, Any, Union, Type

from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch

AGENT_BUILD_OUTPUT_PATH = SOURCE_ROOT / "agent_build_output"

BUILDKIT_VERSION = "v0.11.6"

USE_GHA_CACHE = bool(os.environ.get("USE_GHA_CACHE"))


@dataclasses.dataclass
class BuildxBuilderWrapper:
    name: str

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


def docker_build_or_stop_on_cache_miss(
        cmd_args: List[str],
        input: bytes,
):

    if input:
        stdin = subprocess.PIPE
    else:
        stdin = None

    process = subprocess.Popen(
        [
            *cmd_args,
        ],
        stderr=subprocess.PIPE,
        stdin=stdin
    )

    if input:
        process.stdin.write(input)

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
            if line is None:
                break
            print(line.strip(), file=sys.stderr)

    def _raise_process_error():
        output = "\n".join(all_lines)
        raise Exception(f"Command {cmd_args} ended with error {process.returncode}. Stderr: {output}")

    if process.poll() is not None:
        if process.returncode == 0:
            _print_rest_of_the_process_oupput()
            return False
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


#_existing_builders: Dict[CpuArch, Dict[str, RemoteBuildxBuilderWrapper]] = collections.defaultdict(dict)
_existing_builders: Dict[str, RemoteBuildxBuilderWrapper] = {}


class BuilderCacheMissError(Exception):
    pass


ALL_BUILDER_STEPS: Dict[str, 'BuilderStep'] = {}

def u(cls):
    def wrapper(*args, **kwargs):
        new_instance = cls(*args, **kwargs)

        instance = ALL_BUILDER_STEPS.get(new_instance.id)

        if instance is None:
            ALL_BUILDER_STEPS[new_instance.id] = new_instance
            instance = new_instance

        return instance

    return wrapper


_BUILD_STEPS_OUTPUT_OCI_DIR = AGENT_BUILD_OUTPUT_PATH / "oci"
_BUILD_STEPS_OUTPUT_OUTPUT_DIR = AGENT_BUILD_OUTPUT_PATH / "output"


class BuilderStep():
    def __init__(
        self,
        name: str,
        context: pl.Path,
        dockerfile: Union[str, pl.Path],
        build_contexts: List['BuilderStep'] = None,
        build_args: Dict[str, str] = None,
        platform: CpuArch = CpuArch.x86_64,
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

    @classmethod
    def create(cls, *args, **kwargs):
        global ALL_BUILDER_STEPS

        new_instance = cls(*args, **kwargs)

        instance = ALL_BUILDER_STEPS.get(new_instance.id)

        if instance is None:
            ALL_BUILDER_STEPS[new_instance.id] = new_instance
            instance = new_instance

        return instance


    @property
    def oci_layout(self):
        return _BUILD_STEPS_OUTPUT_OCI_DIR / self.id

    @property
    def oci_layout_tarball(self):
        return self.oci_layout.parent / f"{self.oci_layout.name}.tar"

    @property
    def output_dir(self):
        return _BUILD_STEPS_OUTPUT_OUTPUT_DIR / self.id

    def get_build_command_args(self):
        cmd_args = [
            "docker",
            "buildx",
            "build",
            "--platform",
            self.platform.as_docker_platform(),
            "-f",
            "-",
        ]

        if self.cache and False:
            if USE_GHA_CACHE:
                cmd_args.extend([
                    "--cache-from",
                    f"type=gha,scope={self.name}",
                    "--cache-to",
                    f"type=gha,scope={self.name}",
                ])
            else:
                cache_type = "local"
                cache_path = AGENT_BUILD_OUTPUT_PATH / "cache" / self.name
                # cache_path = AGENT_BUILD_OUTPUT_PATH / "cache"
                cmd_args.extend([
                    "--cache-from",
                    f"type={cache_type},src={cache_path}",
                    "--cache-to",
                    f"type={cache_type},dest={cache_path}",
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
            fail_on_cache_miss: bool = False,
        ):

        for step in self.build_contexts:
            step.run_and_output_in_oci_tarball(
                fail_on_cache_miss=fail_on_cache_miss,
                #no_cleanup=True
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

        cmd_args = self.get_build_command_args()

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

        if fail_on_cache_miss:

            nginc_container_name = "nginx"
            subprocess.run(
                ["docker", "rm", "-f", nginc_container_name],
                check=True
            )
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

            dockerfile_content = re.sub(
                r"(^FROM [^\n]+$)",
                r"\1\nCOPY --from=cache_check2 / /",
                dockerfile_content,
                flags=re.MULTILINE
            )

            dockerfile_content = f"{TEMPLATE}\n" \
                                 f"{dockerfile_content}"

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
            subprocess.run(
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
            if fail_on_cache_miss and full_no_cache_error_message in build_process_stderr:
                raise BuilderCacheMissError(f"Can not find cache for '{self.name}' with flag 'fail_on_cache_miss' set.")

            raise


    def run_and_output_in_oci_tarball(
            self,
            #tarball_path: pl.Path = None,
            fail_on_cache_miss: bool = False,
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
            fail_on_cache_miss=fail_on_cache_miss,
        )

        with tarfile.open(self.oci_layout_tarball) as tar:
                tar.extractall(path=self.oci_layout)

        self.oci_layout_ready = True

        # if tarball_path:
        #     shutil.copy(self.oci_layout_tarball, tarball_path)

    def run_and_output_in_local_directory(
            self,
            output_dir: pl.Path = None,
            fail_on_cache_miss:bool = False,
            #no_cleanup: bool = False,

    ):
        # if not no_cleanup:
        #     _cleanup_output_dirs()

        if not self.local_output_ready:
            if self.output_dir.exists():
                shutil.rmtree(self.output_dir)

            self.run(
                output=f"type=local,dest={self.output_dir}",
                fail_on_cache_miss=fail_on_cache_miss,
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
            fail_on_cache_miss: bool = False,
            #no_cleanup: bool = False,
    ):
        if tags is None:
            tags = [self.name]

        self.run(
            output=f"type=docker", tags=tags,
            fail_on_cache_miss=fail_on_cache_miss,
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

    def find_child_context_by_identifier(self, identifier):
        for context in self.build_contexts:
            if identifier == context.id:
                return context

            if identifier == context.unique_name:
                return context

            if identifier == context.name:
                return context




BUILDER_NAME = "agent_cicd"

_BUILDX_BUILDER_PORT = "1234"

_IN_DOCKER_SOURCE_ROOT = pl.Path("/tmp/source")

_DOCKERFILE_CONTENT_TEMPLATE = f"""
FROM {{base_image}} as main
{{copy_dependencies}}
{{copy_args_dirs}}
ADD . {_IN_DOCKER_SOURCE_ROOT}

ENV PYTHONPATH="{_IN_DOCKER_SOURCE_ROOT}"
WORKDIR {_IN_DOCKER_SOURCE_ROOT}
RUN python3 /tmp/source/agent_build_refactored/scripts/builder_helper.py {{module}}.{{builder_name}} {{builder_args}}

FROM scratch
COPY --from=main {{work_dir}}/. /work_dir
COPY --from=main {{output_dir}}/. /output_dir
"""

_BUILDERS_OUTPUT_DIR = AGENT_BUILD_OUTPUT_PATH / "builder_output"
_BUILDERS_WORK_DIR = AGENT_BUILD_OUTPUT_PATH / "builder_work_dir"

BUILDER_CLASSES: Dict[str, Type['Builder']] = {}


class BuilderMeta(type):
    def __new__(mcs, *args, **kwargs):
        global BUILDER_CLASSES

        builder_cls: Type[Builder] = super(BuilderMeta, mcs).__new__(mcs, *args, **kwargs)  # NOQA

        if builder_cls.NAME is None:
            return builder_cls

        if builder_cls.NAME in BUILDER_CLASSES:
            raise Exception(
                f"Builder class with name '{builder_cls.NAME}' already exist"
            )

        BUILDER_CLASSES[builder_cls.NAME] = builder_cls
        return builder_cls

        # if builder_cls.NAME is None:
        #     return builder_cls
        #
        # attrs = args[2]
        # fqdn = f'{attrs["__module__"]}.{builder_cls.NAME}'
        #
        # existing_builder_cls = BUILDER_CLASSES.get(fqdn)
        # if existing_builder_cls:
        #     return existing_builder_cls
        #
        # builder_cls.FQDN = fqdn
        # BUILDER_CLASSES[fqdn] = builder_cls
        # return builder_cls


@dataclasses.dataclass
class BuilderArg:
    name: str
    cmd_line_name: str
    cmd_line_action: str = None
    default: Union[str, int, bool] = None
    type: Type = None

    def get_value(self, values: Dict):
        if self.name in values:
            value = values[self.name]

            if self.type is None:
                return value

            return self.type(value)

        if self.default is None:
            raise Exception(f"Value for build argument {self.name} is not specified.")

        return self.default


class BuilderPathArg(BuilderArg):
    pass


class Builder(metaclass=BuilderMeta):
    NAME: str = None
    FQDN: str = None

    LOCALLY_ARG = BuilderArg(
        name="locally",
        cmd_line_name="--locally",
        cmd_line_action="store_true",
        default=False,
    )

    REUSE_EXISTING_DEPENDENCIES_OUTPUTS = BuilderArg(
        name="reuse_existing_dependencies_outputs",
        cmd_line_name="--reuse-existing-dependencies-outputs",
        cmd_line_action="store_true",
        default=False,
    )

    # RUN_DEPENDENCY_STEP_ARG = BuilderArg(
    #     name="run_dependency_step",
    #     cmd_line_name="--run-dependency-step",
    # )

    FAIL_ON_CACHE_MISS_ARG = BuilderArg(
        name="fail_on_cache_miss",
        cmd_line_name="--fail-on-cache-miss",
        cmd_line_action="store_true",
        default=False,
    )

    def __init__(
            self,
            base: BuilderStep,
            dependencies: List[BuilderStep] = None,
    ):
        self.name = self.__class__.NAME
        self.base = base
        self.dependencies = dependencies or []

        # These attributes will have values only after Builder's run.
        self.run_kwargs = None
        self._output_ready = False

    @classmethod
    def get_all_builder_args(cls) -> Dict[str, BuilderArg]:
        result = {}
        for name in dir(cls):

            attr = getattr(cls, name)

            if isinstance(attr, BuilderArg):
                result[name] = attr

        return result

    def get_docker_step(self, run_args: Dict):
        copy_dependencies_str = ""

        for dep in self.dependencies:
            dep_rel_output_dir = dep.output_dir.relative_to(SOURCE_ROOT)
            in_docker_dep_output_dir = _IN_DOCKER_SOURCE_ROOT / dep_rel_output_dir
            copy_dependencies_str = f"{copy_dependencies_str}\n" \
                                    f"COPY --from={dep.id} / {in_docker_dep_output_dir}"

        rel_output_dir = self.output_dir.relative_to(SOURCE_ROOT)
        rel_work_dir = self.work_dir.relative_to(SOURCE_ROOT)

        dockerfile_cmd_args = []
        copy_args_dirs_str = ""
        build_args_contexts = {}
        for builder_arg in self.__class__.get_all_builder_args().values():
            arg_value = run_args.get(builder_arg.name)

            dockerfile_cmd_args.append(builder_arg.cmd_line_name)

            if isinstance(builder_arg, BuilderPathArg):

                arg_path = pl.Path(arg_value).absolute()
                in_docker_arg_path = pl.Path(f"/tmp/builder_arg_dirs{arg_path}")
                if arg_path.is_file():
                    in_docker_arg_dir = in_docker_arg_path.parent
                else:
                    in_docker_arg_dir = in_docker_arg_path

                final_arg_value = in_docker_arg_path

                arg_context_name = f"arg_{builder_arg.name}"
                copy_args_dirs_str = f"{copy_args_dirs_str}\n" \
                                     f"COPY --from={arg_context_name} . {in_docker_arg_dir}"

                build_args_contexts[arg_context_name] = arg_value
            else:
                final_arg_value = arg_value

            if builder_arg.cmd_line_action is None or not builder_arg.cmd_line_action.startswith("store_"):
                dockerfile_cmd_args.append(str(final_arg_value))

        #module = importlib.import_module(self.__class__.__module__)
        module = sys.modules[self.__class__.__module__]
        module_path = pl.Path(module.__file__)
        rel_module_path = module_path.relative_to(SOURCE_ROOT)

        module_path_parts = [*rel_module_path.parent.parts, rel_module_path.stem]
        module_fqdn = ".".join(module_path_parts)

        dockerfile_content = _DOCKERFILE_CONTENT_TEMPLATE.format(
            base_image=self.base.name,
            copy_dependencies=copy_dependencies_str,
            copy_args_dirs=copy_args_dirs_str,
            module=module_fqdn,
            builder_name=self.name,
            builder_args=shlex.join(dockerfile_cmd_args),
            work_dir=str(_IN_DOCKER_SOURCE_ROOT / rel_work_dir),
            output_dir=str(_IN_DOCKER_SOURCE_ROOT / rel_output_dir)
        )

        docker_step = BuilderStep(
            name=f"builder_{self.name}_docker_step",
            context=SOURCE_ROOT,
            dockerfile=dockerfile_content,
            build_contexts=[
                self.base,
                *self.dependencies,
            ],
            platform=self.base.platform,
            cache=False,
            local_dir_contexts=build_args_contexts,
        )

        return docker_step

    @property
    def output_dir(self) -> pl.Path:
        return _BUILDERS_OUTPUT_DIR / self.name

    @property
    def work_dir(self):
        return _BUILDERS_WORK_DIR / self.name

    @abc.abstractmethod
    def build(self):
        pass

    def get_builder_arg_value(self, builder_arg: BuilderArg):
        return builder_arg.get_value(self.run_kwargs)

    def run_package_builder(
        self,
        output_dir: pl.Path = None,
        locally: bool = False,
    ):
        return self.run_builder(
            output_dir=output_dir,
            **{
                self.__class__.LOCALLY_ARG.name: locally,
            }
        )

    def run_builder(
        self,
        output_dir: pl.Path = None,
        **kwargs,
    ):
        self.run_kwargs = kwargs
        locally = self.get_builder_arg_value(self.LOCALLY_ARG)
        reuse_existing_dependencies_outputs = self.get_builder_arg_value(
            self.REUSE_EXISTING_DEPENDENCIES_OUTPUTS
        )
        fail_on_cache_miss = self.get_builder_arg_value(
            self.FAIL_ON_CACHE_MISS_ARG
        )

        def _copy_to_output():
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    self.output_dir,
                    output_dir,
                    dirs_exist_ok=True,
                )

        if self._output_ready:
            _copy_to_output()
            return

        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)

        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        if not locally:
            docker_step = self.get_docker_step(run_args=kwargs)
            docker_step.run_and_output_in_local_directory(
                #no_cleanup=no_cleanup,
                fail_on_cache_miss=fail_on_cache_miss,
            )
            shutil.copytree(
                docker_step.output_dir / "work_dir",
                self.work_dir,
                dirs_exist_ok=True,
                symlinks=True,
            )
            shutil.copytree(
                docker_step.output_dir / "output_dir",
                self.output_dir,
                dirs_exist_ok=True,
                symlinks=True,
            )

        else:
            if not reuse_existing_dependencies_outputs:
                for step in self.dependencies:
                    step.run_and_output_in_local_directory()
            self.build()

        self._output_ready = True

        _copy_to_output()

    def run_step(self, path: str):

        path_parts = path.split(".")

        current_step_part = path_parts[0]
        other_parts = path_parts[1:]

        all_steps = self.dependencies[:]
        all_steps.append(self.base)

        found_step = None
        current_steps = all_steps

        current_step_part = path_parts[0]
        other_parts = path_parts[1:]

        current_parts = path_parts
        found_step = None

        while True:
            current_step = None
            for step in current_steps:
                child_step = step.find_child_context_by_identifier(
                    identifier=current_step_part,
                )
                if child_step is not None:
                    current_step = step
                    break

            if len(current_steps) == 0:
                if len(current_parts) != 1:
                    raise Exception("1111")
                else:
                    found_step = current_step
                    break

            current_steps = current_step.build_contexts[:]
            current_step_part = current_parts[0]
            current_parts = current_parts[1:]










    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):

        for builder_arg in cls.get_all_builder_args().values():

            extra_args = {}

            if builder_arg.cmd_line_action:
                extra_args["action"] = builder_arg.cmd_line_action

            if builder_arg.default:
                extra_args["default"] = builder_arg.default

            parser.add_argument(
                builder_arg.cmd_line_name,
                dest=builder_arg.name,
                **extra_args,
            )

    @classmethod
    def get_run_arguments_from_command_line(cls, args):
        result = {}
        for builder_arg in cls.get_all_builder_args().values():
            if not isinstance(builder_arg, BuilderArg):
                continue

            value = getattr(args, builder_arg.name)
            result[builder_arg.name] = value

        return result

    @classmethod
    def get_constructor_arguments_from_command_line(cls, args):
        return {}

    @classmethod
    def create_and_run_builder_from_command_line(cls, args):

        constructor_args = cls.get_constructor_arguments_from_command_line(args=args)
        builder = cls(**constructor_args)

        run_args = cls.get_run_arguments_from_command_line(args=args)

        # if args.run_dependency_step:
        #     builder.run_step(path=args.run_dependency_step)
        # else:
        #     builder.run_builder(
        #         **run_args
        #     )

        builder.run_builder(
            **run_args
        )


def _cleanup_output_dirs():
    if _BUILD_STEPS_OUTPUT_OCI_DIR.exists():
        shutil.rmtree(_BUILD_STEPS_OUTPUT_OCI_DIR)
    _BUILD_STEPS_OUTPUT_OCI_DIR.mkdir(parents=True)

    if _BUILD_STEPS_OUTPUT_OUTPUT_DIR.exists():
        shutil.rmtree(_BUILD_STEPS_OUTPUT_OUTPUT_DIR)
    _BUILD_STEPS_OUTPUT_OUTPUT_DIR.mkdir(parents=True)

    if _BUILDERS_OUTPUT_DIR.exists():
        shutil.rmtree(_BUILDERS_OUTPUT_DIR)
    _BUILDERS_OUTPUT_DIR.mkdir(parents=True)

    if _BUILDERS_WORK_DIR.exists():
        shutil.rmtree(_BUILDERS_WORK_DIR)
    _BUILDERS_WORK_DIR.mkdir(parents=True)

from agent_build_refactored.managed_packages import managed_packages_builders

# if __name__ == '__main__':
#     base_parser = argparse.ArgumentParser()
#     base_parser.add_argument("fqdn")
#     base_args, other_argv = base_parser.parse_known_args()
#
#     module_name, builder_name = base_args.fqdn.rsplit(".", 1)
#     #spec = importlib.util.spec_from_file_location(module_name, file_path)
#     # print("MODULE_NAME", module_name)
#     # print("NAMEEEE", builder_name)
#
#     from agent_build_refactored.tools.builder import Builder
#
#     #__import__(module_name)
#     module = importlib.import_module(module_name)
#
#     m = sys.modules[__name__]
#
#     builder_cls = sys.modules[__name__].BUILDER_CLASSES[builder_name]
#
#     parser = argparse.ArgumentParser()
#
#     builder_cls.add_command_line_arguments(parser=parser)
#     args = parser.parse_args(args=other_argv)
#
#     builder = builder_cls.create_and_run_builder_from_command_line(args=args)

