# Copyright 2014-2023 Scalyr Inc.
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

import logging
import os
import sys
import io
import abc
import dataclasses
import pathlib as pl
import subprocess
import tarfile
from typing import List, Dict, Union


from agent_build_refactored.utils.constants import AGENT_BUILD_OUTPUT_PATH, CpuArch

logger = logging.getLogger(__name__)

# It is expected to set this env variable to true when build happens inside GitHub Actions.
# It is also expected that GHA cache authentication environment variables are already exposed to the build process.
# see more - https://docs.docker.com/build/cache/backends/gha/
USE_GHA_CACHE = bool(os.environ.get("USE_GHA_CACHE"))
USE_DOCKER_CACHE=bool(os.environ.get("USE_DOCKER_CACHE"))

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
        if self.extract:
            return self.dest.parent / f"{self.dest.name}.tar"
        else:
            return self.dest

    def to_docker_output_option(self):
        return f"type=oci,dest={self.tarball_path}"


def buildx_build(
        dockerfile_path: pl.Path,
        context_path: pl.Path,
        architectures: List[CpuArch] = None,
        build_args: Dict[str, str] = None,
        build_contexts: Dict[str, str] = None,
        stage: str = None,
        output: BuildOutput = None,
        cache_name: str = None,
        fallback_to_remote_builder: bool = False,
        capture_output: bool = False,
        buildx_builder: str = None
):
    """
    Wrapper for the 'docker buildx build' command.
    Additionally, it also can stop the build if it can not be done locally just by using cache, and fall back
    to a remote docker engine to speed-up fresh build. That is especially helpful when we compile for a non-native
    architecture, which can take hours.
    """

    build_args = build_args or {}
    build_contexts = build_contexts or {}

    cmd_args = [
        "docker",
        "buildx",
        "build",
        f"-f={dockerfile_path}",
        "--progress=plain"
    ]

    if buildx_builder:
        cmd_args.append(
            f"--builder={buildx_builder}",
        )

    architectures = architectures or []
    for arch in architectures:
        cmd_args.append(
            f"--platform={arch.as_docker_platform()}",
        )

    for name, value in build_args.items():
        cmd_args.append(
            f"--build-arg={name}={value}"
        )

    for name, value in build_contexts.items():
        cmd_args.append(
            f"--build-context={name}={value}"
        )

    if stage:
        cmd_args.append(
            f"--target={stage}"
        )

    if cache_name:
        if USE_GHA_CACHE:
            final_cache_scope = _get_gha_cache_scope(name=cache_name)
            cmd_args.extend([
                f"--cache-from=type=gha,scope={final_cache_scope}",
                f"--cache-to=type=gha,scope={final_cache_scope}",
            ])
        elif USE_DOCKER_CACHE:
            # Add nothing
            pass
        else:
            cache_dir = _get_local_cache_dir(name=cache_name)
            cmd_args.extend([
                f"--cache-from=type=local,src={cache_dir}",
                f"--cache-to=type=local,dest={cache_dir}",
            ])

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

    allow_fallback_to_remote_builder = ALLOW_FALLBACK_TO_REMOTE_BUILDER and len(architectures) <= 1

    retry = False
    if cache_name and fallback_to_remote_builder and allow_fallback_to_remote_builder:
        if USE_GHA_CACHE:
            # Give more time if we build inside GitHub Action, because its cache may be pretty slow.
            fallback_timeout = 60 * 2
        else:
            fallback_timeout = 40

        logger.info(
            "Try to preform build locally from cache. If that's not possible, will fallback to a remote builder."
        )
    else:
        fallback_timeout = None

    kwargs = {}
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT

    process = subprocess.Popen(
        cmd_args,
        **kwargs
    )

    output_buffer = io.BytesIO()

    try:
        logger.info(f"Running {' '.join(cmd_args)}")
        stdout, stdee = process.communicate(timeout=fallback_timeout)
        
        logger.info("-----------")
        logger.info("DONE")
        if stdout:
            logger.info(stdout.decode())
        logger.info(f"Return code: {process.returncode}")
        logger.info("-----------")

    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout")
        # Timeout occurred, need to abort the build.
        _stop_buildx_build_process(
            process=process
        )
        retry = True

    if capture_output:
        output_buffer.write(stdout)

    if not retry and process.returncode != 0:
        if capture_output:
            sys.stderr.buffer.write(output_buffer.getvalue())
        raise Exception("Build command has failed")

    if retry:

        logger.info("Cache is is not enough to perform a local build, repeat the build in a remote builder")

        from agent_build_refactored.utils.docker.buildx.remote_builder import get_remote_builder

        if len(architectures) != 1:
            raise Exception(
                "It is expected that only single arch builds can fall back to remote builders. "
                f"Current architectures: {[a.value for a in architectures]}"
            )

        builder = get_remote_builder(
            architecture=architectures[0],
        )

        logger.info(
            f"Running {cmd_args}"
        )

        result = subprocess.run(
            [
                *cmd_args,
                f"--builder={builder.name}",
            ],
            check=True,
            **kwargs,
        )

        logger.info(result.stdout)

        if capture_output:
            output_buffer.write(result.stdout.decode())

    if output:
        if isinstance(output, OCITarballBuildOutput) and output.extract:
            with tarfile.open(output.tarball_path) as tar:
                tar.extractall(path=output.dest)

    if capture_output:
        return output_buffer.getvalue()


def _stop_buildx_build_process(process):
    """
    Unfortunately docker buildx build command does not react on a notmal termination or kill signals,
    so the workaround is to terminate its child processes first.
    """
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


