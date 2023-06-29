import abc
import collections
import dataclasses
import functools
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
from typing import Dict, List, Any, Union

import psutil

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
    ):

        unique_name_suffix = unique_name_suffix or ""
        self.name = name
        self.unique_name = f"{name}{unique_name_suffix}"
        self.id = f"{self.unique_name}_{platform.value}"
        self.platform = platform
        self.build_context = context
        self.dockerfile = dockerfile
        self.build_contexts = build_contexts or []
        self.build_args = build_args or {}
        self.cache = cache

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
            "-f"
        ]

        if isinstance(self.dockerfile, pl.Path):
            cmd_args.append(str(self.dockerfile))
        else:
            cmd_args.append("-")

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
                no_cleanup=True
            )

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

        if isinstance(self.dockerfile, str):
            build_dockerfile_input = self.dockerfile.encode()
        else:
            build_dockerfile_input = None

        if local:
            subprocess.run(
                cmd_args,
                check=True,
                input=build_dockerfile_input,
            )

        else:

            docker_remote_builder_info = self.prepare_remote_buildx_builders(in_ec2=False)

            is_cache_miss = docker_build_or_stop_on_cache_miss(
                cmd_args=[
                    *cmd_args,
                    "--builder",
                    docker_remote_builder_info.name,
                ],
                input=build_dockerfile_input
            )

            if not is_cache_miss:
                return

            if fail_on_cache_miss:
                raise BuilderCacheMissError()

            ec2_remote_builder_info = self.prepare_remote_buildx_builders(in_ec2=False)

            subprocess.run(
                [
                    *cmd_args,
                    "--builder",
                    ec2_remote_builder_info.name,
                ],
                check=True,
                input=build_dockerfile_input
            )


        a=10

    def run_and_output_in_oci_tarball(
            self,
            tarball_path: pl.Path = None,
            fail_on_cache_miss: bool = False,
            no_cleanup: bool = False,
    ):
        if not no_cleanup:
            _cleanup_output_dirs()

        if not self.oci_layout.exists():
            self.run(
                output=f"type=oci,dest={self.oci_layout_tarball}",
                fail_on_cache_miss=fail_on_cache_miss,
            )

            with tarfile.open(self.oci_layout_tarball) as tar:
                    tar.extractall(path=self.oci_layout)

        if tarball_path:
            shutil.copy(self.oci_layout_tarball, tarball_path)

    def run_and_output_in_local_directory(
            self,
            output_dir: pl.Path = None,
            fail_on_cache_miss:bool = False,
            no_cleanup: bool = False,

    ):
        if not no_cleanup:
            _cleanup_output_dirs()

        if not self.output_dir.exists():
            self.run(
                output=f"type=local,dest={self.output_dir}",
                fail_on_cache_miss=fail_on_cache_miss,
            )

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                self.output_dir,
                output_dir,
                dirs_exist_ok=True,
            )

    def run_and_output_in_docker(
            self,
            tags: List[str] = None,
            fail_on_cache_miss: bool = False,
            no_cleanup: bool = False,
    ):
        if not no_cleanup:
            _cleanup_output_dirs()

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
        else:
            info = DockerBackedBuildxBuilderWrapper(
                name=builder_name,
                architecture=self.platform
            )

        info.create_builder()

        _existing_builders[builder_name] = info

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
    CpuArch.AARCH64: _ARM_IMAGE,
    CpuArch.ARMV7: _ARM_IMAGE
}

_BUILDX_BUILDER_PORT = "1234"

_IN_DOCKER_SOURCE_ROOT = pl.Path("/tmp/source")

_DOCKERFILE_CONTENT_TEMPLATE = f"""
FROM {{base_image}} as main
{{copy_dependencies}}
ADD . {_IN_DOCKER_SOURCE_ROOT}

ENV PYTHONPATH="{_IN_DOCKER_SOURCE_ROOT}"
WORKDIR {_IN_DOCKER_SOURCE_ROOT}
RUN python3 /tmp/source/{{entrypoint_script}} {{builder_name}} --locally --no-cleanup

FROM scratch
COPY --from=main {{work_dir}}/. /work_dir
COPY --from=main {{output_dir}}/. /output_dir
"""

_BUILDERS_OUTPUT_DIR = AGENT_BUILD_OUTPUT_PATH / "builder_output"
_BUILDERS_WORK_DIR = AGENT_BUILD_OUTPUT_PATH / "builder_work_dir"

class Builder:
    ENTRYPOINT_SCRIPT: pl.Path = None
    NAME: str

    def __init__(
            self,
            name: str,
            base: BuilderStep,
            dependencies: List[BuilderStep] = None,
    ):
        self.name = name
        self.base = base
        self.dependencies = dependencies or []
        copy_dependencies_str = ""

        for dep in self.dependencies:
            dep_rel_output_dir = dep.output_dir.relative_to(SOURCE_ROOT)
            in_docker_dep_output_dir = _IN_DOCKER_SOURCE_ROOT / dep_rel_output_dir
            copy_dependencies_str = f"{copy_dependencies_str}\n" \
                                    f"COPY --from={dep.name} / {in_docker_dep_output_dir}\n"

        rel_output_dir = self.output_dir.relative_to(SOURCE_ROOT)
        rel_work_dir = self.work_dir.relative_to(SOURCE_ROOT)

        entrypoint_script_rel_path = self.__class__.ENTRYPOINT_SCRIPT.relative_to(SOURCE_ROOT)

        dockerfile_content = _DOCKERFILE_CONTENT_TEMPLATE.format(
            base_image=self.base.name,
            copy_dependencies=copy_dependencies_str,
            entrypoint_script=str(entrypoint_script_rel_path),
            builder_name=self.__class__.NAME,
            work_dir=str(_IN_DOCKER_SOURCE_ROOT / rel_work_dir),
            output_dir=str(_IN_DOCKER_SOURCE_ROOT / rel_output_dir)
        )

        self.docker_step = BuilderStep(
            name=f"builder_{self.name}_docker_step",
            context=SOURCE_ROOT,
            dockerfile=dockerfile_content,
            build_contexts=[
                self.base,
                *self.dependencies,
            ],
            platform=self.base.platform,
            cache=False
        )

    @property
    def output_dir(self) -> pl.Path:
        return _BUILDERS_OUTPUT_DIR / self.name

    @property
    def work_dir(self):
        return _BUILDERS_WORK_DIR / self.name

    @abc.abstractmethod
    def build(self):
        pass

    def run_builder(
        self,
        output_dir: pl.Path = None,
        locally: bool = False,
        no_cleanup: bool = False
    ):
        if not no_cleanup:
            _cleanup_output_dirs()

        if not locally:
            self.docker_step.run_and_output_in_local_directory(
                no_cleanup=no_cleanup,
            )
            shutil.copytree(
                self.docker_step.output_dir / "work_dir",
                self.work_dir,
                dirs_exist_ok=True,
                symlinks=True,
            )
            shutil.copytree(
                self.docker_step.output_dir / "output_dir",
                self.output_dir,
                dirs_exist_ok=True,
                symlinks=True,
            )
            return

        for step in self.dependencies:
            step.run_and_output_in_local_directory(no_cleanup=True)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.build()

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                self.output_dir,
                output_dir,
                dirs_exist_ok=True,
            )






    # def run_builder(self):
    #     if self.run_in_docker:
    #         self.run_builder_in_docker()
    #     else:
    #         self.run_builder_locally()


    @staticmethod
    def create_parser():
        parser = argparse.ArgumentParser()

        parser.add_argument(
            "--locally",
            action="store_true"
        )

        parser.add_argument(
            "--no-cleanup",
            action="store_true"
        )

        return parser

    def run_builder_from_command_line(self, args):
        return functools.partial(
            self.run_builder,
            locally=args.locally,
            no_cleanup=args.no_cleanup,
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

