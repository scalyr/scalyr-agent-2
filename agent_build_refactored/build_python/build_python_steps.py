import collections
import enum
import os
import dataclasses
import pathlib as pl
import shutil
import stat
from typing import Dict, Callable


from agent_build_refactored.tools.constants import Architecture, DockerPlatform, SOURCE_ROOT
from agent_build_refactored.tools.runner import RunnerStep, EnvironmentRunnerStep, DockerImageSpec, Runner

from agent_build_refactored.tools.dependabot_aware_docker_images import UBUNTU_22_04
from agent_build_refactored.build_python.steps import (
    download_build_dependencies,
    install_build_environment,
    build_python_dependencies,
    build_openssl,
    build_python,
    build_dev_requirements,
    prepare_c_runtime_environment_with_python,
    prepare_toolset
)

from agent_build_refactored.managed_packages.build_dependencies_versions import (
    PYTHON_PACKAGE_SSL_1_VERSION,
    PYTHON_PACKAGE_SSL_3_VERSION,
    EMBEDDED_PYTHON_VERSION,
    EMBEDDED_PYTHON_PIP_VERSION,
    RUST_VERSION,
)


# Name of the subdirectory of the agent packages.
AGENT_SUBDIR_NAME = "scalyr-agent-2"

AGENT_OPT_DIR = pl.Path("/opt") / AGENT_SUBDIR_NAME
PYTHON_INSTALL_PREFIX = f"{AGENT_OPT_DIR}/python3"

EMBEDDED_PYTHON_SHORT_VERSION = ".".join(EMBEDDED_PYTHON_VERSION.split(".")[:2])


PARENT_DIR = pl.Path(__file__).parent.absolute()
STEPS_SCRIPTS_DIR = PARENT_DIR / "steps"
FILES_DIR = PARENT_DIR / "files"


# Simple dataclass to store information about base environment step.
@dataclasses.dataclass
class BuildEnvInfo:
    # Script to run.
    script_name: str
    # Docker image to use.
    image: str


BUILD_ENV_CENTOS_6 = BuildEnvInfo(
    script_name="install_gcc_centos_6.sh", image="centos:6"
)
BUILD_ENV_CENTOS_7 = BuildEnvInfo(
    script_name="install_gcc_centos_7.sh", image="centos:7"
)

SUPPORTED_ARCHITECTURES = [
    Architecture.X86_64,
    Architecture.ARM64,
]

_PYTHON_BUILD_DEPENDENCIES_VERSIONS = dict(
    xz_version="5.2.6",
    libffi_version="3.4.2",
    util_linux_version="2.38",
    ncurses_version="6.3",
    libedit_version_commit="0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030"
    gdbm_version="1.23",
    zlib_version="1.2.13",
    bzip_version="1.0.8",
    openssl_1_version=PYTHON_PACKAGE_SSL_1_VERSION,
    openssl_3_version=PYTHON_PACKAGE_SSL_3_VERSION,
)

DOWNLOAD_PYTHON_DEPENDENCIES_STEP = download_build_dependencies.create_step(
    **_PYTHON_BUILD_DEPENDENCIES_VERSIONS,
    python_version=EMBEDDED_PYTHON_VERSION
)


class CRuntime(enum.Enum):
    GLIBC = "glibc"
    MUSL = "musl"


@dataclasses.dataclass
class DependencyToolchain:
    """
    Data class that contains all steps that are required in order to build Python and other dependencies
        for a particular C runtime (e.g. glibc or musl) and CPU architecture.
    """
    c_runtime: CRuntime
    architecture: Architecture
    install_build_environment: EnvironmentRunnerStep
    openssl_1: RunnerStep
    openssl_3: RunnerStep
    python_with_openssl_1: RunnerStep
    python_with_openssl_3: RunnerStep
    dev_requirements: RunnerStep
    c_runtime_environment_with_python: EnvironmentRunnerStep


def create_all_toolchains():
    """
    Create toolchains for all C runtimes and CPU architectures.
    """
    result_toolchains = collections.defaultdict(dict)

    for c_runtime in CRuntime:
        for architecture in SUPPORTED_ARCHITECTURES:

            steps_name_suffix = f"{c_runtime.value}_{architecture.value}"

            run_in_remote_docker = architecture != Architecture.X86_64

            print(f"ARCH: {architecture},  RUNSSS: {run_in_remote_docker}")

            if architecture == Architecture.X86_64:
                base_image_name = "centos:6"
            else:
                base_image_name = "centos:7"

            base_image = DockerImageSpec(
                name=base_image_name,
                platform=architecture.as_docker_platform.value
            )

            install_build_environment_step = install_build_environment.create_step(
                name_suffix=steps_name_suffix,
                base_image=base_image,
                run_in_remote_docker=run_in_remote_docker
            )

            build_python_dependencies_step = build_python_dependencies.create_step(
                name_suffix=steps_name_suffix,
                install_build_environment_step=install_build_environment_step,
                download_build_dependencies_step=DOWNLOAD_PYTHON_DEPENDENCIES_STEP,
                **_PYTHON_BUILD_DEPENDENCIES_VERSIONS,
                run_in_remote_docker=run_in_remote_docker
            )

            build_openssl_1_step = build_openssl.create_step(
                name_suffix=steps_name_suffix,
                openssl_version=PYTHON_PACKAGE_SSL_1_VERSION,
                openssl_major_version=1,
                install_build_environment_step=install_build_environment_step,
                download_build_dependencies_step=DOWNLOAD_PYTHON_DEPENDENCIES_STEP,
                run_in_remote_docker=run_in_remote_docker
            )

            build_openssl_3_step = build_openssl.create_step(
                name_suffix=steps_name_suffix,
                openssl_version=PYTHON_PACKAGE_SSL_3_VERSION,
                openssl_major_version=3,
                install_build_environment_step=install_build_environment_step,
                download_build_dependencies_step=DOWNLOAD_PYTHON_DEPENDENCIES_STEP,
                run_in_remote_docker=run_in_remote_docker
            )

            def create_python_step(
                    build_openssl_step: RunnerStep,
                    openssl_major_version: int
            ):
                return build_python.create_step(
                    name_suffix=f"_with_openssl_{openssl_major_version}_{steps_name_suffix}",
                    download_build_dependencies_step=DOWNLOAD_PYTHON_DEPENDENCIES_STEP,
                    install_build_environment_step=install_build_environment_step,
                    build_python_dependencies_step=build_python_dependencies_step,
                    build_openssl_step=build_openssl_step,
                    python_version=EMBEDDED_PYTHON_VERSION,
                    python_short_version=EMBEDDED_PYTHON_SHORT_VERSION,
                    python_install_prefix=PYTHON_INSTALL_PREFIX,
                    pip_version=EMBEDDED_PYTHON_PIP_VERSION,
                    run_in_remote_docker=run_in_remote_docker

                )

            build_python_with_openssl_1_step = create_python_step(
                build_openssl_step=build_openssl_1_step,
                openssl_major_version=1,
            )
            build_python_with_openssl_3_step = create_python_step(
                build_openssl_step=build_openssl_3_step,
                openssl_major_version=3
            )

            build_dev_requirements_step = build_dev_requirements.create_step(
                name_suffix=steps_name_suffix,
                install_build_environment_step=install_build_environment_step,
                build_python_dependencies_step=build_python_dependencies_step,
                build_openssl_step=build_openssl_1_step,
                build_python_step=build_python_with_openssl_1_step,
                rust_version=RUST_VERSION,
                python_install_prefix=PYTHON_INSTALL_PREFIX,
                run_in_remote_docker=run_in_remote_docker,
            )

            prepare_c_runtime_environment_with_python_step = prepare_c_runtime_environment_with_python.create_step(
                name_suffix=steps_name_suffix,
                base_image=base_image,
                build_openssl_step=build_openssl_1_step,
                build_python_step=build_python_with_openssl_1_step,
                build_dev_requirements_step=build_dev_requirements_step,
                python_install_prefix=PYTHON_INSTALL_PREFIX,
            )

            glibc_toolchain = DependencyToolchain(
                c_runtime=c_runtime,
                architecture=architecture,
                install_build_environment=install_build_environment_step,
                openssl_1=build_openssl_1_step,
                openssl_3=build_openssl_3_step,
                python_with_openssl_1=build_python_with_openssl_1_step,
                python_with_openssl_3=build_python_with_openssl_3_step,
                dev_requirements=build_dev_requirements_step,
                c_runtime_environment_with_python=prepare_c_runtime_environment_with_python_step
            )

            result_toolchains[c_runtime][architecture] = glibc_toolchain

    return result_toolchains


ALL_DEPENDENCY_TOOLCHAINS: Dict[CRuntime, Dict[Architecture, DependencyToolchain]] = create_all_toolchains()


GLIBC_X86_64_TOOLCHAIN = ALL_DEPENDENCY_TOOLCHAINS[CRuntime.GLIBC][Architecture.X86_64]

PREPARE_TOOLSET_STEP_GLIBC_X86_64 = prepare_toolset.create_step(
    name_suffix=f"{GLIBC_X86_64_TOOLCHAIN.c_runtime.value}-{GLIBC_X86_64_TOOLCHAIN.architecture.value}",
    base_image=DockerImageSpec(
        name=UBUNTU_22_04,
        platform=GLIBC_X86_64_TOOLCHAIN.architecture.as_docker_platform.value
    ),
    build_openssl_step=GLIBC_X86_64_TOOLCHAIN.openssl_3,
    build_python_step=GLIBC_X86_64_TOOLCHAIN.python_with_openssl_3,
    build_dev_requirements_step=GLIBC_X86_64_TOOLCHAIN.dev_requirements,
    python_install_prefix=PYTHON_INSTALL_PREFIX
)


def create_new_steps_for_all_toolchains(
    create_step_fn: Callable[[DependencyToolchain], RunnerStep],
):
    """
    Create new steps for each toolchain defined in this module.
    :param create_step_fn: Callable that creates a step. It accepts DependencyToolchain
        instance as argument. The resulting step will be based on this toolchain.
    :return: Dict with new steps for each architecture for each C runtime.
    """
    result_steps = collections.defaultdict(dict)
    for c_runtime, architectures in ALL_DEPENDENCY_TOOLCHAINS.items():
        for architecture, toolchain in architectures.items():
            step = create_step_fn(
                toolchain
            )
            if step is None:
                continue

            result_steps[c_runtime][architecture] = step

    return result_steps


def create_python_files(
        build_python_step_output: pl.Path,
        output: pl.Path,
        additional_ld_library_paths: str = None
):

    output.mkdir(parents=True)
    shutil.copytree(
        build_python_step_output,
        output,
        dirs_exist_ok=True,
        symlinks=True
    )

    # Rename main Python executable to be 'python3-original' and copy our wrapper script instead of it
    opt_dir = output / AGENT_OPT_DIR.relative_to("/")
    python_dir = opt_dir / "python3"
    python_bin_dir = python_dir / "bin"

    python_executable_full_name = python_bin_dir / f"python{EMBEDDED_PYTHON_SHORT_VERSION}"
    python_original_executable = python_bin_dir / "python3-original"
    python_executable_full_name.rename(python_original_executable)

    render_python_wrapper_executable(
        executable_path=AGENT_OPT_DIR / "python3/bin/python3-original",
        output_file=python_executable_full_name,
        additional_ld_library_paths=additional_ld_library_paths,
    )

    remove_python_unused_files(install_prefix=python_dir)


def render_python_wrapper_executable(
        executable_path: pl.Path,
        output_file: pl.Path,
        additional_ld_library_paths: str = None
):
    template_path = FILES_DIR / "bin/python3_template.sh"

    content = template_path.read_text()

    content = content.replace(
        "%{{ REPLACE_PYTHON_EXECUTABLE }}", str(executable_path)
    )

    final_additional_ld_library_paths = f"{AGENT_OPT_DIR}/python3/lib"

    if additional_ld_library_paths:
        final_additional_ld_library_paths = f"{final_additional_ld_library_paths}:{additional_ld_library_paths}"

    content = content.replace(
        "%{{ REPLACE_ADDITIONAL_LD_LIBRARY_PATH }}", str(final_additional_ld_library_paths)
    )

    output_file.write_text(content)

    output_file.chmod(output_file.stat().st_mode | stat.S_IEXEC)


def remove_python_unused_files(
        install_prefix: pl.Path
):
    bin_dir = install_prefix / "bin"
    stdlib_dir = install_prefix / "lib" / f"python{EMBEDDED_PYTHON_SHORT_VERSION}"
    # Remove other executables
    for _glob in ["pip*", "2to3*", "pydoc*", "idle*"]:
        for path in bin_dir.glob(_glob):
            path.unlink()

    # Remove some unneeded libraries
    shutil.rmtree(stdlib_dir / "ensurepip")
    shutil.rmtree(stdlib_dir / "unittest")
    shutil.rmtree(stdlib_dir / "turtledemo")
    shutil.rmtree(stdlib_dir / "tkinter")

    # These standard libraries are marked as deprecated and will be removed in future versions.
    # https://peps.python.org/pep-0594/
    # We do not wait for it and remove them now in order to reduce overall size.
    # When deprecated libs are removed, this code can be removed as well.

    if EMBEDDED_PYTHON_VERSION < "3.12":
        os.remove(stdlib_dir / "asynchat.py")
        os.remove(stdlib_dir / "smtpd.py")

        # TODO: Do not remove the asyncore library because it is a requirement for our pysnmp monitor.
        #  We have to update the pysnmp library before the asyncore is removed from Python.
        # os.remove(package_python_lib_dir / "asyncore.py")

    if EMBEDDED_PYTHON_VERSION < "3.13":
        lib_bindings_dir = stdlib_dir / "lib-dynload"

        os.remove(stdlib_dir / "aifc.py")
        list(lib_bindings_dir.glob("audioop.*.so"))[0].unlink()
        os.remove(stdlib_dir / "cgi.py")
        os.remove(stdlib_dir / "cgitb.py")
        os.remove(stdlib_dir / "chunk.py")
        os.remove(stdlib_dir / "crypt.py")
        os.remove(stdlib_dir / "imghdr.py")
        os.remove(stdlib_dir / "mailcap.py")
        os.remove(stdlib_dir / "nntplib.py")
        list(lib_bindings_dir.glob("nis.*.so"))[0].unlink()
        list(lib_bindings_dir.glob("ossaudiodev.*.so"))[0].unlink()
        os.remove(stdlib_dir / "pipes.py")
        os.remove(stdlib_dir / "sndhdr.py")
        list(lib_bindings_dir.glob("spwd.*.so"))[0].unlink()
        os.remove(stdlib_dir / "sunau.py")
        os.remove(stdlib_dir / "telnetlib.py")
        os.remove(stdlib_dir / "uu.py")
        os.remove(stdlib_dir / "xdrlib.py")


def create_agent_libs_venv_files(
    build_libs_venv_step_output: pl.Path,
    output: pl.Path
):
    output.mkdir(parents=True)
    shutil.copytree(
        build_libs_venv_step_output / "venv",
        output,
        dirs_exist_ok=True,
        symlinks=True,
    )

    # Recreate Python executables in venv and delete everything except them, since they are not needed.
    venv_bin_dir = output / "bin"
    shutil.rmtree(venv_bin_dir)
    venv_bin_dir.mkdir()
    venv_bin_dir_original_executable = (
            venv_bin_dir / "python3-original"
    )
    venv_bin_dir_original_executable.symlink_to(
        AGENT_OPT_DIR / "python3/bin/python3-original"
    )

    venv_bin_python3_executable = venv_bin_dir / "python3"

    render_python_wrapper_executable(
        executable_path=pl.Path("/var/opt/scalyr-agent-2/venv/bin/python3-original"),
        output_file=venv_bin_python3_executable,
        additional_ld_library_paths=f"{AGENT_OPT_DIR}/lib/openssl/current/libs"
    )

    venv_bin_python_executable = venv_bin_dir / "python"
    venv_bin_python_executable.symlink_to("python3")

    venv_bin_python_full_executable = (
            venv_bin_dir / f"python{EMBEDDED_PYTHON_SHORT_VERSION}"
    )
    venv_bin_python_full_executable.symlink_to("python3")