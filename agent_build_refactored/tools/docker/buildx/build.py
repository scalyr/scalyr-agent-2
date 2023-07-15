import logging
import os
import shlex
import sys
import io
import re
import abc
import dataclasses
import pathlib as pl
import subprocess
import tarfile
import time
from typing import List, Dict


from agent_build_refactored.tools.constants import AGENT_BUILD_OUTPUT_PATH, CpuArch

logger = logging.getLogger(__name__)

# It is expected to set this env variable to true when build happens inside GitHub Actions.
# It is also expected that GHA cache authentication environment variables are already exposed to the build process.
# see more - https://docs.docker.com/build/cache/backends/gha/
USE_GHA_CACHE = bool(os.environ.get("USE_GHA_CACHE"))

# Just a suffix for the build cache string. May be usefull when it is needed to invalidate the cache.
CACHE_VERSION = os.environ.get("CACHE_VERSION", "")

# When some build can not be fully done from existing cache, it can fall back to using a remote docker builder in
# ec2 instance. If this env variable if not set to True, then this behavior is restricted.
ALLOW_FALLBACK_TO_REMOTE_BUILDER = bool(
    os.environ.get("ALLOW_FALLBACK_TO_REMOTE_BUILDER")
)


@dataclasses.dataclass
class BuildOutput:
    @abc.abstractmethod
    def to_docker_output_option(self):
        pass


@dataclasses.dataclass
class LocalDirectoryBuildOutput(BuildOutput):
    dest: pl.Path

    def to_docker_output_option(self):
        return f"type=local,dest={self.dest}"


@dataclasses.dataclass
class DockerImageBuildOutput(BuildOutput):
    name: str

    def to_docker_output_option(self):
        return f"type=docker"


@dataclasses.dataclass
class OCITarballBuildOutput(BuildOutput):
    dest: pl.Path
    extract: bool = True

    @property
    def tarball_path(self):
        return f"{self.dest}.tar"

    def to_docker_output_option(self):
        return f"type=oci,dest={self.tarball_path}"


def buildx_build(
        dockerfile_path: pl.Path,
        context_path: pl.Path,
        architecture: CpuArch,
        build_args: Dict[str, str] = None,
        build_contexts: Dict[str, str] = None,
        output: BuildOutput = None,
        cache_name: str = None,
        fallback_to_remote_builder: bool = False
):

    build_args = build_args or {}
    build_contexts = build_contexts or {}

    cmd_args = [
        "docker",
        "buildx",
        "build",
        f"-f={dockerfile_path}",
        f"--platform={architecture.as_docker_platform()}",
        "--progress=plain",
    ]

    for name, value in build_args.items():
        cmd_args.append(
            f"--build-arg={name}={value}"
        )

    for name, value in build_contexts.items():
        cmd_args.append(
            f"--build-context={name}={value}"
        )


    if cache_name:
        if USE_GHA_CACHE:
            final_cache_scope = _get_gha_cache_scope(name=cache_name)
            cmd_args.append(
                f"--cache-from=type=gha,scope={final_cache_scope}",
            )
        else:
            cache_dir = _get_local_cache_dir(name=cache_name)
            cmd_args.append(
                f"--cache-from=type=local,src={cache_dir}",
            )

    if output:
        cmd_args.append(
            f"--output={output.to_docker_output_option()}"
        )
        if isinstance(output, DockerImageBuildOutput):
            cmd_args.append(
                f"-t={output.name}"
            )

    cmd_args.append(
        str(context_path)
    )

    retry = False
    if cache_name and fallback_to_remote_builder and ALLOW_FALLBACK_TO_REMOTE_BUILDER:
        if USE_GHA_CACHE:
            # Give more time if we build inside GitHub Action, because its cache may be pretty slow.
            fallback_timeout = 60 * 2
        else:
            fallback_timeout = 60
            #fallback_timeout = 5
        logger.info(
            "Try to preform build locally from cache. If that's not possible, will fallback to a remote builder."
        )
    else:
        fallback_timeout = None

    process = subprocess.Popen(
        cmd_args,
    )

    try:
        process.communicate(timeout=fallback_timeout)
    except subprocess.TimeoutExpired:
        _stop_buildx_build_process(
            process=process
        )
        retry = True

    if retry:

        logger.info("Cache is is not enough to perform a local build, repeat the build in a remote builder")

        from agent_build_refactored.tools.docker.buildx.remote_builder import get_remote_builder

        builder = get_remote_builder(
            architecture=architecture,
        )

        if USE_GHA_CACHE:
            cache_scope = _get_gha_cache_scope(name=cache_name)
            cache_to_option = f"type=gha,scope={cache_scope}"
        else:
            cache_dir = _get_local_cache_dir(name=cache_name)
            cache_to_option = f"type=local,dest={cache_dir}"

        subprocess.run(
            [
                *cmd_args,
                f"--cache-to={cache_to_option}",
                f"--builder={builder.name}",
            ],
            check=True,
        )

    if output:
        if isinstance(output, OCITarballBuildOutput) and output.extract:
            with tarfile.open(output.tarball_path) as tar:
                tar.extractall(path=output.dest)


def _stop_buildx_build_process(process):
    import psutil

    def terminate_children_processes(_process: psutil.Process):
        child_processes = _process.children()

        for child_process in child_processes:
            terminate_children_processes(
                _process=child_process
            )

        _process.terminate()

    psutil_process = psutil.Process(pid=process.pid)

    terminate_children_processes(
        _process=psutil_process
    )


def _get_gha_cache_scope(name: str):
    result = name
    if CACHE_VERSION:
        result = f"{result}_{CACHE_VERSION}"

    return result


def _get_local_cache_dir(name: str):
    return AGENT_BUILD_OUTPUT_PATH / "docker_cache" / name
