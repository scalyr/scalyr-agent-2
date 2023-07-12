import logging
import os
import sys
import io
import re
import abc
import dataclasses
import pathlib as pl
import subprocess
import tarfile
from typing import List, Dict


from agent_build_refactored.tools.constants import AGENT_BUILD_OUTPUT_PATH, CpuArch

logger = logging.getLogger(__name__)


USE_GHA_CACHE = bool(os.environ.get("USE_GHA_CACHE"))
CACHE_VERSION = os.environ.get("CACHE_VERSION", "")


class BuilderCacheMissError(Exception):
    pass


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
        cache_scope: str = None,
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

    if cache_scope and USE_GHA_CACHE:

        final_cache_scope = cache_scope
        if CACHE_VERSION:
            final_cache_scope = f"{final_cache_scope}_{CACHE_VERSION}"

        cmd_args.extend([
            f"--cache-from=type=gha,scope={final_cache_scope}",
            f"--cache-to=type=gha,scope={final_cache_scope}",
        ])

        # local_cache_dir = AGENT_BUILD_OUTPUT_PATH / "docker_cache" / cache_scope
        # cmd_args.extend([
        #     f"--cache-from=type=local,src={local_cache_dir}",
        #     f"--cache-to=type=local,dest={local_cache_dir}",
        # ])

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
    if cache_scope and fallback_to_remote_builder:
        try:
            _build_and_verify_cache(
                cmd_args=cmd_args,
                fail_on_cache_miss=True,
                #builder_name="test_builder",
            )
        except BuilderCacheMissError:
            retry = True
    else:
        _build_and_verify_cache(
            cmd_args=cmd_args,
            fail_on_cache_miss=False,
        )

    if retry:

        logger.info("Cache is is not enough to perform a local build, repeat the build in a remote builder")

        from agent_build_refactored.tools.docker.buildx.remote_builder import get_remote_builder

        builder = get_remote_builder(
            architecture=architecture,
        )

        _build_and_verify_cache(
            cmd_args=cmd_args,
            fail_on_cache_miss=False,
            builder_name=builder.name,
        )


    # subprocess.run(
    #     cmd_args,
    #     check=True
    # )

    if output:
        if isinstance(output, OCITarballBuildOutput) and output.extract:
            with tarfile.open(output.tarball_path) as tar:
                tar.extractall(path=output.dest)


def _build_and_verify_cache(
        cmd_args: List[str],
        fail_on_cache_miss: bool,
        builder_name: str = None,
        verbose: bool = True,
):

    final_cmd_args = cmd_args[:]

    if builder_name:
        final_cmd_args.append(
            f"--builder={builder_name}"
        )

    process = subprocess.Popen(
        final_cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stderr_buffer = io.BytesIO()

    def read_line():
        line_bytes = process.stderr.readline()

        if not line_bytes:
            return ""

        stderr_buffer.write(line_bytes)
        line_str = line_bytes.decode(errors="replace")
        return line_str

    def _print_line(line):
        if verbose:
            print(line, end="", file=sys.stderr)

    def read_run_lines(command_number: int):
        lines_count = 0
        while True:
            run_line = read_line()

            if not run_line:
                raise Exception("Expected at least one message related to the previous RUN command")

            lines_count += 1
            _print_line(run_line)

            if not run_line.startswith(f"#{command_number} "):
                continue

            if run_line.startswith(f"#{command_number} sha256:"):
                return True

            if run_line.startswith(f"#{command_number} extracting sha256:"):
                return True

            if re.match(rf"#{command_number} CACHED\n", run_line):
                return True

            return False

    cache_miss = False
    if fail_on_cache_miss:
        while True:
            line = read_line()

            if not line:
                break

            _print_line(line)

            m = re.match(r"#(\d+) \[[^]]*\] RUN .+", line)
            if m:
                command_number = m.group(1)
                if not read_run_lines(command_number=command_number):
                    _stop_buildx_build_process(
                        process=process
                    )
                    cache_miss = True
                    break

    while True:
        line = read_line()

        if not line:
            break

        _print_line(line)

    process.wait()

    if process.returncode != 0:
        stderr = stderr_buffer.getvalue()
        if not verbose:
            sys.stderr.buffer.write(stderr)
        if not fail_on_cache_miss or not cache_miss:
            raise subprocess.CalledProcessError(
                returncode=process.returncode,
                cmd=cmd_args,
                stderr=stderr,
            )

    if cache_miss:
        raise BuilderCacheMissError(
            f"Build has had cache miss and can not be continues"
        )


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
