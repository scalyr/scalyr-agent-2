import enum
import io
import os
import pathlib as pl
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import logging
import atexit
from typing import List, Union, Dict, Optional, Set

from agent_build_refactored.tools.constants import CpuArch, AGENT_BUILD_OUTPUT_PATH
from agent_build_refactored.tools.docker.buildx_builder import LocalBuildxBuilderWrapper, BuildxBuilderWrapper
from agent_build_refactored.tools.docker.common import get_docker_container_host_port, delete_container, ContainerWrapper

logger = logging.getLogger(__name__)


class BuilderCacheMissError(Exception):
    pass



USE_GHA_CACHE = bool(os.environ.get("USE_GHA_CACHE"))
CACHE_VERSION = os.environ.get("CACHE_VERSION", "")
#REMOTE_BUILDX_BUILDER_TYPE = os.environ.get("REMOTE_BUILDX_BUILDER_TYPE", "docker")
REMOTE_BUILDX_BUILDER_TYPE = os.environ.get("REMOTE_BUILDX_BUILDER_TYPE", "ec2")

_BUILD_STEPS_OUTPUT_OCI_DIR = AGENT_BUILD_OUTPUT_PATH / "oci"
_BUILD_STEPS_OUTPUT_OUTPUT_DIR = AGENT_BUILD_OUTPUT_PATH / "output"


ALL_BUILDER_STEPS: Dict[str, 'BuilderStep'] = {}

_essential_images: Set[str] = set()

_running_essential_containers: List[str] = []


class CacheMissPolicy(enum.Enum):
    #FALLBACK_TO_REMOTE_BUILDX_BUILDER = "fallback_to_remot_buildx_buildere"
    CONTINUE = "continue"
    FAIL = "fail"


TEMPLATE = """

# This is a special stage that has to fail when it is not reused from cache ad has to run from the beginning.
# By using this stage we can fail the build early when we do not want to build everything from the beginning.
FROM --platform=linux/amd64 essential_ubuntu_tools as cache_check
ARG ERROR_MESSAGE
RUN echo -n "Can not continue." >> /tmp/error_mgx.txt
RUN echo " ${ERROR_MESSAGE}" >> /tmp/error_mgx.txt

# When the curl command finishes with failure, that means we allow build without cache.
# If the curl command finishes successfully, that meant that this build is not meant to be run without cache.

# If build is supposed to be run from the beginning and without cache,
# the endpoint that is queried by the curl has to be unreachable.
# When we expect that build has to be fully reused from cache, we make this endpoint available for curl,
# so the next this instruction will fail if it's not cached.
RUN if curl -s localhost:8080 > /dev/null; then cat /tmp/error_mgx.txt ; exit 1; fi
RUN mkdir -p /tmp/empty

FROM scratch as cache_check_dummy_files
COPY --from=cache_check /tmp/empty/. /
"""

_BUILDX_BUILDER_NAME_PREFIX = "agent_cicd"


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
        run_in_remote_builder_if_possible: bool = False,
        needs_essential_dependencies: bool = True,
    ):

        unique_name_suffix = unique_name_suffix or ""
        self.name = name
        self.unique_name = f"{name}{unique_name_suffix}"
        self.id = f"{self.unique_name}_{platform.value}"
        self.platform = platform
        self.build_context = context
        self.run_in_remote_builder_if_possible = run_in_remote_builder_if_possible
        self.needs_essential_dependencies = needs_essential_dependencies

        if isinstance(dockerfile, pl.Path):
            self.dockerfile_content = dockerfile.read_text()
        else:
            self.dockerfile_content = dockerfile

        build_contexts = build_contexts or []

        self.essential_ubuntu_tools: Optional[EssentialTools] = None

        if needs_essential_dependencies:
            self.essential_ubuntu_tools = EssentialTools.create()
            build_contexts.extend([
                self.essential_ubuntu_tools,
            ])

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
            cache_name = f"{self.id}"
            if CACHE_VERSION:
                cache_name = f"{cache_name}_{CACHE_VERSION}"

            if USE_GHA_CACHE:
                cache_from_value = f"type=gha,scope={cache_name}"
                cache_to_value = f"type=gha,scope={cache_name}"
            else:
                cache_path = AGENT_BUILD_OUTPUT_PATH / "cache" / cache_name
                cache_from_value = f"type=local,src={cache_path}"
                cache_to_value = f"type=local,dest={cache_path}"

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

    def render_final_dockerfile(self):

        dockerfile_content = self.dockerfile_content
        if not self.needs_essential_dependencies or not  self.cache:
            return dockerfile_content

        dockerfile_content = re.sub(
            r"(^FROM [^\n]+$)",
            r"\1\nCOPY --from=cache_check_dummy_files / /",
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

        return dockerfile_content

    def run(
        self,
        output: str = None,
        tags: List[str] = None,
        on_cache_miss: CacheMissPolicy = CacheMissPolicy.CONTINUE,
        on_children_cache_miss: CacheMissPolicy = CacheMissPolicy.CONTINUE,
        verbose: bool = True,
        verbose_children: bool = True
    ):
        global _MISSED_CACHE_BUILD_CRASHER

        for step in self.build_contexts:
            step.run_and_output_in_oci_tarball(
                on_cache_miss=on_children_cache_miss,
                on_children_cache_miss=on_children_cache_miss,
                verbose=verbose_children,
                verbose_children=verbose_children,
            )

        logger.info(f"Build dependency: {self.id}")

        use_only_cache = on_cache_miss != CacheMissPolicy.CONTINUE

        cmd_args = self.get_build_command_args(
            use_only_cache=use_only_cache,
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

        dockerfile_content = self.render_final_dockerfile()

        if self.needs_essential_dependencies and self.cache:
            if use_only_cache:
                if _MISSED_CACHE_BUILD_CRASHER is None:
                    _MISSED_CACHE_BUILD_CRASHER = MissedCacheBuildCrasher()
                    _MISSED_CACHE_BUILD_CRASHER

        local = False

        machine_name = platform.machine()
        if machine_name.lower() in ["x86_64"]:
            current_machine_arch = CpuArch.x86_64
        elif machine_name.lower() in ["aarch64"]:
            current_machine_arch = CpuArch.AARCH64
        elif machine_name.lower() in ["armv7l"]:
            current_machine_arch = CpuArch.ARMV7
        else:
            raise Exception(f"Unknown uname machine {machine_name}")

        builder_info = None
        if self.platform != current_machine_arch:
            if not use_only_cache and self.run_in_remote_builder_if_possible:
                builder_info = self.prepare_buildx_builders(local=False)

        if builder_info is None:
            builder_info = self.prepare_buildx_builders(local=True)

        self.oci_layout.parent.mkdir(parents=True, exist_ok=True)

        process = subprocess.Popen(
            [
                *cmd_args,
                "--build-arg",
                "ERROR_MESSAGE=This build is supposed to be rebuilt from cache",
                "--builder",
                builder_info.name,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        process.stdin.write(dockerfile_content.encode())
        process.stdin.close()

        stderr_buffer = io.BytesIO()
        while True:
            line = process.stderr.readline()
            if not line:
                break

            if verbose:
                sys.stderr.buffer.write(line)

            stderr_buffer.write(line)

        process.wait()

        if process.returncode != 0:
            if not verbose:
                sys.stderr.buffer.write(stderr_buffer.getvalue())
            full_no_cache_error_message = b"Can not continue. This build is supposed to be cached"
            if full_no_cache_error_message in stderr_buffer.getvalue():
                raise BuilderCacheMissError(full_no_cache_error_message.decode())

            raise subprocess.CalledProcessError(
                returncode=process.returncode,
                cmd=cmd_args,
                output=process.stdout.read(),
                stderr=stderr_buffer.getvalue(),
            )

        if use_only_cache:
            logger.info(f"Dependency '{self.id}' is successfully restored from cache.")
        else:
            logger.info(f"Dependency '{self.id}' is successfully built.")

    def run_and_output_in_oci_tarball(
            self,
            on_cache_miss: CacheMissPolicy = CacheMissPolicy.CONTINUE,
            on_children_cache_miss: CacheMissPolicy = CacheMissPolicy.CONTINUE,
            verbose: bool = True,
            verbose_children: bool = True
    ):

        if self.oci_layout_ready:
            return

        if self.oci_layout.exists():
            shutil.rmtree(self.oci_layout)

        if self.oci_layout_tarball.exists():
            self.oci_layout_tarball.unlink()

        self.run(
            output=f"type=oci,dest={self.oci_layout_tarball}",
            on_cache_miss=on_cache_miss,
            on_children_cache_miss=on_children_cache_miss,
            verbose=verbose,
            verbose_children=verbose_children,
        )

        with tarfile.open(self.oci_layout_tarball) as tar:
                tar.extractall(path=self.oci_layout)

        self.oci_layout_ready = True

    def run_and_output_in_local_directory(
            self,
            output_dir: pl.Path = None,
            on_cache_miss: CacheMissPolicy = CacheMissPolicy.CONTINUE,
            on_children_cache_miss: CacheMissPolicy = CacheMissPolicy.CONTINUE,
            verbose: bool = True,
            verbose_children: bool = True,

    ):

        if not self.local_output_ready:
            if self.output_dir.exists():
                shutil.rmtree(self.output_dir)

            self.run(
                output=f"type=local,dest={self.output_dir}",
                on_cache_miss=on_cache_miss,
                on_children_cache_miss=on_children_cache_miss,
                verbose=verbose,
                verbose_children=verbose_children,
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
            on_cache_miss: CacheMissPolicy = CacheMissPolicy.CONTINUE,
            on_children_cache_miss: CacheMissPolicy = CacheMissPolicy.CONTINUE,
            verbose: bool = True,
            verbose_children: bool = True,
    ):
        if tags is None:
            tags = [self.name]

        self.run(
            output=f"type=docker", tags=tags,
            on_cache_miss=on_cache_miss,
            on_children_cache_miss=on_children_cache_miss,
            verbose=verbose,
            verbose_children=verbose_children,
        )

    def prepare_buildx_builders(
        self,
        local: bool,
    ):
        global _essential_images

        builder_name_suffix = "local" if local else "remote"
        builder_name = f"{_BUILDX_BUILDER_NAME_PREFIX}_{self.platform.value}_{builder_name_suffix}"
        if local:
            info = LocalBuildxBuilderWrapper.create(
                name=builder_name
            )
        else:
            ssh_client_image_name = "agent_remote_build_ssh_client_image_name"

            if ssh_client_image_name not in _essential_images:
                self.essential_ubuntu_tools.run_and_output_in_docker(
                    tags=[ssh_client_image_name],
                    verbose=False,
                    verbose_children=False
                )
                _essential_images.add(ssh_client_image_name)

            from agent_build_refactored.tools.docker.buildx_builder.remote import (
                EC2BackedRemoteBuildxBuilderWrapper
            )

            info = EC2BackedRemoteBuildxBuilderWrapper.create(
                name=builder_name,
                architecture=self.platform,
                ssh_client_image_name=ssh_client_image_name,
            )

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


class EssentialTools(BuilderStep):
    CONTEXT_DIR = pl.Path(__file__).parent / "essential_ubuntu_tools"

    def __init__(self):
        super(EssentialTools, self).__init__(
            name=self.__class__.CONTEXT_DIR.name,
            context=self.__class__.CONTEXT_DIR,
            dockerfile=self.__class__.CONTEXT_DIR / "Dockerfile",
            platform=CpuArch.x86_64,
            cache=True,
            run_in_remote_builder_if_possible=False,
            needs_essential_dependencies=False,
        )


class MissedCacheBuildCrasher:
    def __init__(
        self
    ):

        self._container_name = "cache_test"
        self._container_port = "80/tcp"

        self._container = ContainerWrapper(
            name=self._container_name,
            image="nginx",
            network="test",
            rm=True,
            ports={0: self._container_port},
        )

        self.host_port = None

    def start(self):

        self._container.run()

        self.host_port = self._container.get_host_port(
            container_port=self._container_port,
        )

    def add_entry(self, name: str, value: str):
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                self._container_name,
                "/bin/bash",
                "-e",
                f'echo "{value}" /usr/share/nginx/html/{name}.html'
            ]
        )

    def stop(self):
        self._container.remove(force=True)


_MISSED_CACHE_BUILD_CRASHER: Optional[MissedCacheBuildCrasher] = None


def cleanup():
    global _MISSED_CACHE_BUILD_CRASHER

    if _MISSED_CACHE_BUILD_CRASHER:
        delete_container(
            container_name=_CACHE_CHECKER_CONTAINER_NAME,
        )


atexit.register(cleanup)