# Copyright 2014-2022 Scalyr Inc.
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


"""
This module is responsible for building Python agent for Linux distributions with package managers.

It defines builder classes that are responsible for the building of the Linux agent deb and rpm packages that are
    managed by package managers such as apt and yum.

There are two variants of packages that can be built:
    1. All in one (aio) package named "scalyr-agent-2-aio", that contains all required dependencies, so it can run basically on any Linux
        glibc-based distribution.
    2. Package that depends on some system packages, such as Python or OpenSLL, named "scalyr-agent-2". Probably will be
        discontinued in the future in favour of the first one.

The aio package provides the "embedded" Python interpreter that is specially built to be used by the agent.
    It is built against the oldest possible version of gLibc, so it has to be enough to maintain
    only one build of the package in order to support all target systems.

    One of the features on the package, is that is can use system's OpenSSL if it has appropriate version, or
    fallback to the OpenSSL library which is shipped with the package. To achieve that, the Python interpreter from the
    package contains multiple versions of OpenSSL (1.1.1 and 3) and Python's 'OpenSSL-related' C bindings - _ssl.cpython*.so and _hashlib.cpython.so.
    On each new installation/upgrade of the package (or user's manual run of the command
    `/opt/scalyr-agent-2/bin/agent-python3-config initialize`), the package follows next steps in order to
    resolve OpenSSL library to use:
        - 1: First it tries to find system's OpenSSL 3+. It creates a symlink '/opt/scalyr-agent-2/lib/openssl/current'
            that points to the directory `/opt/scalyr-agent-2/lib/openssl/3`. This directory contains directory
            named 'bindings' that, in turn, contains Python's C bindings - '_ssl' and '_hashlib' that are compiled
            against OpenSSL 3. The Python's OpenSSL-related C bindings in '/opt/scalyr-agent-2/python3/lib/pythonX.Y/lib-dynload'
            are also linked to the bindings in the `current` directory, so by changing the target of the `current` symlink
            we also change OpenSSL version of the Python's C bindings.
            Then the package will try "probe" the system's OpenSSL. That is done basically just by running new
            process of the interpreter and importing the 'ssl' module. If there's no exception, then appropriate
            OpenSSL 3 is presented in the system and Python can use it. If there is an exception, then
            OpenSSL 3 can not be found and we go to the step 2.

        - 2: If first step is not successful and system does not have appropriate OpenSSL 3, then we re-create the
            `current` symlink and link it with the `/opt/scalyr-agent-2/lib/openssl/1_1_1` which has bindings for
            OpenSSL 1.1.1+, so we can repeat the same "probing", but now for OpenSSL 1.1.1+.

        - 3: If OpenSSL 1.1.1+ is also not presented in a system, then we fallback to the 'embedded' OpenSSL library that
            is shipped with the package. This is achieved by making the `current` symlink to target the
            '/opt/scalyr-agent-2/lib/openssl/embedded' directory. This directory, as in previous steps, contains
            C bindings for OpenSSL (for now we use 1.1.1 for the embedded OpenSSL), but it also has another
            subdirectory named 'libs', and this subdirectory contains shared objects of the embedded OpenSSL.
            Agent, when starts new process of the Python interpreter, adds '/opt/scalyr-agent-2/lib/openssl/current' to
            the 'LD_LIBRARY_PATH' environment variable, so when the `current` directory is linked with the `embedded`
            directory, system's dynamic linker has to find the shared objects of the embedded OpenSSL earlier that
            anything else that may be presented in a system.

The package also provides requirement libraries for the agent, for example Python 'requests' or 'orjson' libraries.
    Agent requirements are shipped in form of virtualenv (or just venv). The venv with agent's 'core' requirements is shipped with this packages.
    User can also install their own additional requirements by specifying them in the package's config file -
    /opt/scalyr-agent-2/etc/additional-requirements.txt.
    The original venv that is shipped with the package is never used directly by the agent. Instead of that, the package
    follows the next steps:
        - 1: The original venv is copied to the `/var/opt/scalyr-agent/venv` directory, the path that is
               expected to be used by the agent.
        - 2: The requirements from the additional-requirements.txt file are installed to a copied venv. The core
                requirements are already there, so it has to install only additional ones.

    This new venv initialization process is triggered every time by the package's 'postinstall' script, guaranteeing
    that venv is up to date on each install/upgrade. For the same purpose, the `additional-requirements.txt` file is
    set as package's config file, to be able to 'survive' upgrades. User also can 're-initialize' agent requirements
    manually by running the command `/opt/scalyr-agent-2/bin/agent-libs-config initialize`


The structure of the package has to guarantee that files of these packages does not interfere with
    files of local system Python interpreter. To achieve that, Python interpreter files are installed in the
    '/opt/scalyr-agent-2/python3' directory.


"""

import abc
import collections
import concurrent.futures
import dataclasses
import functools
import hashlib
import json
import logging
import operator
import os
import shutil
import subprocess
import argparse
import pathlib as pl
import re
from typing import List, Tuple, Optional, Dict, Type, Union


from agent_build_refactored.tools.builder import Builder

from agent_build_refactored.tools.constants import (
    SOURCE_ROOT,
    DockerPlatform,
    Architecture,
    CpuArch,
    REQUIREMENTS_AGENT_COMMON,
    REQUIREMENTS_AGENT_COMMON_PLATFORM_DEPENDENT,
    CURRENT_MACHINE_CPU_ARCHITECTURE,
)

from agent_build_refactored.tools.docker.common import delete_container


from agent_build_refactored.prepare_agent_filesystem import (
    build_linux_fhs_agent_files,
    add_config,
    create_change_logs,
)

from agent_build_refactored.tools.toolset_image import build_toolset_image
from agent_build_refactored.tools.docker.buildx.build import BuildOutput, LocalDirectoryBuildOutput, DockerImageBuildOutput, \
    buildx_build
from agent_build_refactored.tools.constants import AGENT_REQUIREMENTS

logger = logging.getLogger(__name__)

_PARENT_DIR = pl.Path(__file__).parent
_DEPENDENCIES_DIR = _PARENT_DIR / "dependencies"

# Name of the subdirectory of the agent packages.
AGENT_SUBDIR_NAME = "scalyr-agent-2"

# Name of the dependency package with Python interpreter.
PYTHON_PACKAGE_NAME = "scalyr-agent-python3"

# name of the dependency package with agent requirement libraries.
AGENT_LIBS_PACKAGE_NAME = "scalyr-agent-libs"

AGENT_AIO_PACKAGE_NAME = "scalyr-agent-2-aio"
AGENT_NON_AIO_AIO_PACKAGE_NAME = "scalyr-agent-2"

AGENT_OPT_DIR = pl.Path("/opt") / AGENT_SUBDIR_NAME

PYTHON_INSTALL_PREFIX = pl.Path(f"{AGENT_OPT_DIR}/python3")
PYTHON_DEPENDENCIES_INSTALL_PREFIX = pl.Path("/usr/local")

PYTHON_VERSION = "3.11.2"

PYTHON_X_Y = ".".join(PYTHON_VERSION.split(".")[:2])


# Versions of OpenSSL libraries to build for Python.
OPENSSL_1_VERSION = "1.1.1s"
OPENSSL_3_VERSION = "3.0.7"

# Integer (hex) representation of the OpenSSL version.
EMBEDDED_OPENSSL_VERSION_NUMBER = 0x30000070

PYTHON_VERSION = "3.11.2"
OPENSSL_1_VERSION = "1.1.1s"
OPENSSL_3_VERSION = "3.0.7"

PYTHON_INSTALL_PREFIX = pl.Path("/opt/scalyr-agent-2/python3")
DEPENDENCIES_INSTALL_PREFIX = pl.Path("/usr/local")

PORTABLE_PYTEST_RUNNER_NAME = "portable_runner"

# Version of Rust to use in order to build some of agent's requirements, e.g. orjson.
RUST_VERSION = "1.63.0"

EMBEDDED_PYTHON_PIP_VERSION = "23.0"

#EMBEDDED_OPENSSL_VERSION = BUILD_PYTHON_WITH_OPENSSL_3_STEPS[LibC.GNU][CpuArch.x86_64].openssl_version


def _get_openssl_version_number(version: str):
    version_parts = version.split(".")
    major = version_parts[0]
    minor = version_parts[1]
    patch = version_parts[2]
    hex_str = f"0x{major}{minor.zfill(2)}00{patch.zfill(2)}0"
    return int(hex_str, 16)


#EMBEDDED_OPENSSL_VERSION_NUMBER = _get_openssl_version_number(version=EMBEDDED_OPENSSL_VERSION)

AGENT_LIBS_REQUIREMENTS_CONTENT = (
    f"{REQUIREMENTS_AGENT_COMMON}\n" f"{REQUIREMENTS_AGENT_COMMON_PLATFORM_DEPENDENT}"
)

SUPPORTED_ARCHITECTURES = {
    CpuArch.x86_64,
    CpuArch.AARCH64
}


def cpu_arch_as_fpm_arch(arch: CpuArch):
    if arch == CpuArch.x86_64:
        return "amd64"

    if arch == CpuArch.AARCH64:
        return "arm64"

    raise Exception(f"Unknown cpu architecture: {arch.value}")


class LinuxPackageBuilder(Builder):
    """
    This is a base class that is responsible for the building of the Linux agent deb and rpm packages that are managed
        by package managers such as apt and yum.
    """

    def __init__(
        self,
        packages_types: List[str] = None,
    ):

        super(LinuxPackageBuilder, self).__init__()
        self.package_types = packages_types or ["deb", "rpm"]

    @property
    def common_agent_package_build_args(self) -> List[str]:
        """
        Set of common arguments for the final fpm command.
        """
        version = (SOURCE_ROOT / "VERSION").read_text().strip()
        return [
                # fmt: off
                "fpm",
                "--license", "Apache 2.0",
                "--vendor", "Scalyr",
                "--depends", "bash >= 3.2",
                "--url", "https://www.scalyr.com",
                "--deb-user", "root",
                "--deb-group", "root",
                "--rpm-user", "root",
                "--rpm-group", "root",
                "--deb-no-default-config-files",
                "--no-deb-auto-config-files",
                "-v", version,
                "--config-files", f"/etc/{AGENT_SUBDIR_NAME}/agent.json",
                "--config-files", f"/etc/{AGENT_SUBDIR_NAME}/agent.d",
                "--config-files", f"/usr/share/{AGENT_SUBDIR_NAME}/monitors",
                "--directories", f"/usr/share/{AGENT_SUBDIR_NAME}",
                "--directories", f"/var/lib/{AGENT_SUBDIR_NAME}",
                "--directories", f"/var/log/{AGENT_SUBDIR_NAME}",
                "--rpm-use-file-permissions",
                "--deb-use-file-permissions",
                "--verbose",
                # fmt: on
            ]

    @staticmethod
    def _build_packages_common_files(package_root_path: pl.Path):
        """
        Build files that are common for all types of linux packages.
        :param package_root_path: Path with package root.
        """
        build_linux_fhs_agent_files(
            output_path=package_root_path, copy_agent_source=True
        )

        # remove Python cache directories from agent's source code.
        for path in package_root_path.rglob("__pycache__/"):
            if path.is_file():
                continue
            shutil.rmtree(path)

        # Copy init.d folder.
        shutil.copytree(
            SOURCE_ROOT
            / "agent_build_refactored/managed_packages/files/init.d",
            package_root_path / "etc/init.d",
            dirs_exist_ok=True,
        )

        # Add config file
        add_config(SOURCE_ROOT / "config", package_root_path / "etc/scalyr-agent-2")

    def _build_package(
        self,
        package_type: str,
        cmd_args: List[str],
        fpm_image_name: str,
    ):

        package_dir = self.result_dir / package_type
        package_dir.mkdir()
        in_docker_package_dir = self.to_in_docker_path(package_dir)

        in_docker_source_root = self.to_in_docker_path(SOURCE_ROOT)

        container_name = f"{fpm_image_name}_{package_type}"
        delete_container(
            container_name=container_name,
        )

        try:
            result = subprocess.run(
                [
                    # fmt: off
                    "docker",
                    "run",
                    "-i",
                    "--rm",
                    f"--name={container_name}",
                    f"--workdir={in_docker_package_dir}",
                    f"--volume={SOURCE_ROOT}:{in_docker_source_root}",
                    fpm_image_name,
                    *cmd_args,
                    "-t",
                    package_type,
                    # fmt: on
                ],
                check=True,
                stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            logger.info(f"Fpm process has ended with error. Output: {e.stdout.decode()}")
            raise

        return result.stdout.decode()

    def _build_all_packages(
        self,
        cmd_args: List[str],
    ):

        toolset_image_name = build_toolset_image()

        parallel_builds_count = os.cpu_count()
        if parallel_builds_count is None:
            parallel_builds_count = 1

        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=parallel_builds_count
        )

        futures = collections.OrderedDict()
        for package_type in self.package_types:
            logger.info(f"Start build of the {package_type} package.")
            future = executor.submit(
                self._build_package,
                package_type=package_type,
                cmd_args=cmd_args,
                fpm_image_name=toolset_image_name,

            )
            futures[package_type] = future

        for package_type, future in futures.items():
            output = future.result()
            logger.info(f"The {package_type} package build is finished.\n{output}")



class LinuxNonAIOPackageBuilder(LinuxPackageBuilder):
    """
    This class builds non-aio (all in one) version of the package, meaning that this package has some system dependencies,
    such as Python and OpenSSL.
    """

    @staticmethod
    def _create_non_aio_package_scriptlets(output_dir: pl.Path):
        """Copy three scriptlets required by the RPM and Debian non-aio packages.

        These are the preinstall.sh, preuninstall.sh, and postuninstall.sh scripts.
        """

        source_scriptlets_path = SOURCE_ROOT / "agent_build_refactored/managed_packages/non-aio/install-scriptlets"

        pre_install_scriptlet = output_dir / "preinstall.sh"
        post_install_scriptlet = output_dir / "postinstall.sh"
        pre_uninstall_scriptlet = output_dir / "preuninstall.sh"

        shutil.copy(source_scriptlets_path / "preinstall.sh", pre_install_scriptlet)
        shutil.copy(source_scriptlets_path / "postinstall.sh", post_install_scriptlet)
        shutil.copy(source_scriptlets_path / "preuninstall.sh", pre_uninstall_scriptlet)

        check_python_script_path = source_scriptlets_path / "check-python.sh"
        check_python_file_content = check_python_script_path.read_text()

        code_to_paste = re.search(
            r"# {{ start }}\n(.+)# {{ end }}", check_python_file_content, re.S
        ).group(1)

        def replace_code(script_path: pl.Path):
            """
            Replace placeholders in the package install scripts with the common code that checks python version.
            This is needed to avoid duplication of the python check code in the pre and post install scripts.
            """
            content = script_path.read_text()

            final_content = re.sub(
                r"# {{ check-python }}[^\n]*",
                code_to_paste,
                content,
            )

            if "\\n" in code_to_paste:
                raise Exception(
                    "code_to_paste (%s) shouldn't contain new line character since re.sub "
                    "will replace it with actual new line character"
                    % (check_python_script_path)
                )

            script_path.write_text(final_content)

        replace_code(pre_install_scriptlet)
        replace_code(post_install_scriptlet)

    def _build(self):

        agent_package_root = self.work_dir / "agent_package_root"

        self._build_packages_common_files(package_root_path=agent_package_root)

        # Copy switch python executable script to package's bin
        switch_python_source = SOURCE_ROOT / "agent_build_refactored/managed_packages/non-aio/files/bin/scalyr-switch-python.sh"

        switch_python_executable_name = "scalyr-switch-python"
        package_bin_path = agent_package_root / f"usr/share/{AGENT_SUBDIR_NAME}/bin"
        package_switch_python_executable = package_bin_path / switch_python_executable_name
        shutil.copy(
            switch_python_source,
            package_switch_python_executable
        )
        sbin_python_switch_executable = agent_package_root / "usr/sbin" / switch_python_executable_name
        sbin_python_switch_executable.symlink_to(f"/usr/share/{AGENT_SUBDIR_NAME}/bin/{switch_python_executable_name}")

        # Create copies of the agent_main.py with python2 and python3 shebang.
        agent_main_path = SOURCE_ROOT / "scalyr_agent/agent_main.py"
        agent_package_path = agent_package_root / f"usr/share/{AGENT_SUBDIR_NAME}/py/scalyr_agent"
        agent_main_py2_path = agent_package_path / "agent_main_py2.py"
        agent_main_py3_path = agent_package_path / "agent_main_py3.py"

        agent_main_content = agent_main_path.read_text()
        agent_main_py2_path.write_text(
            agent_main_content.replace("#!/usr/bin/env python", "#!/usr/bin/env python2")
        )
        agent_main_py3_path.write_text(
            agent_main_content.replace("#!/usr/bin/env python", "#!/usr/bin/env python3")
        )
        main_permissions = os.stat(agent_main_path).st_mode
        os.chmod(agent_main_py2_path, main_permissions)
        os.chmod(agent_main_py3_path, main_permissions)

        # Create package installation scriptlets
        scriptlets_path = self.work_dir / "scriptlets"
        scriptlets_path.mkdir()
        self._create_non_aio_package_scriptlets(output_dir=scriptlets_path)

        description = (
            "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics"
            " and log files and transmit them to Scalyr."
        )

        # prepare packages changelogs
        changelogs_path = self.work_dir / "changelogs"
        changelogs_path.mkdir()
        create_change_logs(output_dir=changelogs_path)

        in_docker_package_root = self.to_in_docker_path(agent_package_root)
        in_docker_scriptlets_path = self.to_in_docker_path(scriptlets_path)
        in_docker_changelogs_dir = self.to_in_docker_path(changelogs_path)

        cmd_args = [
            # fmt: off
            *self.common_agent_package_build_args,
            "-s", "dir",
            "-a", "all",
            "-C", str(in_docker_package_root),
            "-n", AGENT_NON_AIO_AIO_PACKAGE_NAME,
            "--provides", AGENT_NON_AIO_AIO_PACKAGE_NAME,
            "--description", description,
            "--before-install", str(in_docker_scriptlets_path / "preinstall.sh"),
            "--after-install", str(in_docker_scriptlets_path / "postinstall.sh"),
            "--before-remove", str(in_docker_scriptlets_path / "preuninstall.sh"),
            "--deb-changelog", str(in_docker_changelogs_dir / "changelog-deb"),
            "--rpm-changelog", str(in_docker_changelogs_dir / "changelog-rpm"),
            "--conflicts", AGENT_AIO_PACKAGE_NAME
            # fmt: on
        ]

        self._build_all_packages(
            cmd_args=cmd_args,
        )


class LinuxAIOPackagesBuilder(LinuxPackageBuilder):
    """
    This builder creates "all in one" (aio) version of the agent package.
    That means that this package does not have any system dependencies, except glibc.
    """

    # package architecture, for example: amd64 for deb.
    ARCHITECTURE: CpuArch

    @classmethod
    def build_dependencies(
        cls,
        output: BuildOutput,
    ):

        rust_platform = f"{cls.ARCHITECTURE.value}-unknown-linux-gnu"

        python_x_y_version = ".".join(PYTHON_VERSION.split(".")[:2])

        build_args = {
            "ARCH": cls.ARCHITECTURE.value,
            "PYTHON_VERSION": PYTHON_VERSION,
            "PYTHON_X_Y_VERSION": python_x_y_version,
            "PYTHON_INSTALL_PREFIX": str(PYTHON_INSTALL_PREFIX),
            "DEPENDENCIES_INSTALL_PREFIX": str(DEPENDENCIES_INSTALL_PREFIX),
            "REQUIREMENTS_FILE_CONTENT": AGENT_REQUIREMENTS,
            "PORTABLE_RUNNER_NAME": PORTABLE_PYTEST_RUNNER_NAME,
            "RUST_VERSION": "1.63.0",
            "RUST_PLATFORM": rust_platform,
            "BZIP_VERSION": "1.0.8",
            "LIBEDIT_VERSION_COMMIT": "0cdd83b3ebd069c1dee21d81d6bf716cae7bf5da",  # tag - "upstream/3.1-20221030",
            "LIBFFI_VERSION": "3.4.2",
            "NCURSES_VERSION": "6.3",
            "OPENSSL_1_VERSION": OPENSSL_1_VERSION,
            "OPENSSL_3_VERSION": OPENSSL_3_VERSION,
            "TCL_VERSION_COMMIT": "338c6692672696a76b6cb4073820426406c6f3f9",  # tag - "core-8-6-13",
            "SQLITE_VERSION_COMMIT": "e671c4fbc057f8b1505655126eaf90640149ced6",  # tag - "version-3.41.2",
            "UTIL_LINUX_VERSION": "2.38",
            "XZ_VERSION": "5.2.6",
            "ZLIB_VERSION": "1.2.13",
        }

        cache_scope = f"packages_python_{cls.ARCHITECTURE.value}"

        fallback_to_remote_builder = cls.ARCHITECTURE != CURRENT_MACHINE_CPU_ARCHITECTURE

        buildx_build(
            dockerfile_path=_DEPENDENCIES_DIR / "Dockerfile",
            context_path=SOURCE_ROOT,
            architecture=cls.ARCHITECTURE,
            build_args=build_args,
            output=output,
            cache_name=cache_scope,
            fallback_to_remote_builder=True
        )

    def _prepare_package_python_and_libraries_files(self, package_root: pl.Path):
        """
        Prepare package files of the Python interpreter and agent libraries.
        :param package_root: Path to the package root.
        """

        dependencies_dir = self.work_dir / "dependencies"
        self.build_dependencies(
            output=LocalDirectoryBuildOutput(
                dest=dependencies_dir,
            )
        )

        python_dependency_dir = dependencies_dir / "python"

        shutil.copytree(
            python_dependency_dir,
            package_root,
            dirs_exist_ok=True,
            symlinks=True,
        )

        relative_python_install_prefix = pl.Path(PYTHON_INSTALL_PREFIX).relative_to("/")
        package_opt_dir = package_root / AGENT_OPT_DIR.relative_to("/")
        package_openssl_dir = package_opt_dir / "lib/openssl"

        python_ssl_bindings_glob = "_ssl.cpython-*-*-*-*.so"
        python_hashlib_bindings_glob = "_hashlib.cpython-*-*-*-*.so"

        def copy_openssl_files(
                python_dir: pl.Path,
                openssl_major_version: str,
        ):
            """# This function copies Python's ssl module related files."""
            python_step_bindings_dir = python_dir / relative_python_install_prefix / f"lib/python{PYTHON_X_Y}/lib-dynload"

            ssl_binding_path = list(python_step_bindings_dir.glob(python_ssl_bindings_glob))[0]
            hashlib_binding_path = list(python_step_bindings_dir.glob(python_hashlib_bindings_glob))[0]

            bindings_dir = package_openssl_dir / openssl_major_version / "bindings"
            bindings_dir.mkdir(parents=True)

            shutil.copy(ssl_binding_path, bindings_dir)
            shutil.copy(hashlib_binding_path, bindings_dir)

        # Copy ssl modules which are compiled for OpenSSL 1.1.1
        python_with_openssl_1_dependency_dir = dependencies_dir / "python_with_openssl_1"

        copy_openssl_files(
            python_dir=python_with_openssl_1_dependency_dir,
            openssl_major_version="1"
        )

        # Copy ssl modules which are compiled for OpenSSL 3
        copy_openssl_files(
            python_dir=python_dependency_dir,
            openssl_major_version="3"
        )

        # Create directory for the embedded OpenSSL files.
        embedded_openssl_dir = package_openssl_dir / "embedded"
        embedded_openssl_dir.mkdir()
        # Since we use OpenSSL 3 for embedded, we link to the previously created C bindings of the OpenSSL 3.
        embedded_openssl_bindings = embedded_openssl_dir / "bindings"
        embedded_openssl_bindings.symlink_to("../3/bindings")
        # Copy shared libraries of the embedded OpenSSL 1 from the step that builds it.
        embedded_openssl_libs_dir = embedded_openssl_dir / "libs"
        embedded_openssl_libs_dir.mkdir(parents=True)

        openssl_3_dependency_dir = dependencies_dir / "openssl_3"

        rel_dependencies_install_prefix = DEPENDENCIES_INSTALL_PREFIX.relative_to(
            "/"
        )
        build_openssl_libs_dir = openssl_3_dependency_dir / rel_dependencies_install_prefix / "lib"
        openssl_3_shared_object_to_copy = list(build_openssl_libs_dir.glob("*.so.*"))
        assert openssl_3_shared_object_to_copy, "No shared object files are found"
        for path in openssl_3_shared_object_to_copy:
            shutil.copy(path, embedded_openssl_libs_dir)

        # Create the `current` symlink which by default targets the embedded OpenSSL.
        package_current_openssl_dir = package_openssl_dir / "current"
        package_current_openssl_dir.symlink_to("./embedded")

        # Remove original bindings from Python interpreter and replace them with symlinks.
        package_python_dir = package_root / relative_python_install_prefix
        package_python_lib_dir = package_python_dir / f"lib/python{PYTHON_X_Y}"
        package_python_bindings_dir = package_python_lib_dir / "lib-dynload"
        ssl_binding_path = list(package_python_bindings_dir.glob(python_ssl_bindings_glob))[0]
        hashlib_binding_path = list(package_python_bindings_dir.glob(python_hashlib_bindings_glob))[0]
        ssl_binding_path.unlink()
        hashlib_binding_path.unlink()
        ssl_binding_path.symlink_to(f"../../../../lib/openssl/current/bindings/{ssl_binding_path.name}")
        hashlib_binding_path.symlink_to(f"../../../../lib/openssl/current/bindings/{hashlib_binding_path.name}")

        # Rename main Python executable to be 'python3-original' and copy our wrapper script instead of it
        source_bin_dir = SOURCE_ROOT / "agent_build_refactored/managed_packages/files/bin"
        package_python_bin_dir = package_python_dir / "bin"
        package_python_bin_executable_full_name = package_python_bin_dir / f"python{PYTHON_X_Y}"
        package_python_bin_original_executable = package_python_bin_dir / "python3-original"
        package_python_bin_executable_full_name.rename(package_python_bin_original_executable)
        shutil.copy(source_bin_dir / "python3", package_python_bin_executable_full_name)

        # Copy executables that allows to configure the Python interpreter.
        package_opt_bin_dir = package_opt_dir / "bin"
        package_opt_bin_dir.mkdir(parents=True)
        shutil.copy(source_bin_dir / "agent-python3-config", package_opt_bin_dir)

        # Copy Python interpreter's configuration files.
        package_opt_etc_dir = package_opt_dir / "etc"
        package_opt_etc_dir.mkdir()
        preferred_openssl_file = package_opt_etc_dir / "preferred_openssl"
        preferred_openssl_file.write_text("auto")

        package_python_bin_dir = package_python_dir / "bin"

        # Remove other executables
        for _glob in ["pip*", "2to3*", "pydoc*", "idle*"]:
            for path in package_python_bin_dir.glob(_glob):
                path.unlink()

        # Remove some unneeded libraries
        shutil.rmtree(package_python_lib_dir / "ensurepip")
        shutil.rmtree(package_python_lib_dir / "unittest")
        shutil.rmtree(package_python_lib_dir / "turtledemo")
        shutil.rmtree(package_python_lib_dir / "tkinter")

        # These standard libraries are marked as deprecated and will be removed in future versions.
        # https://peps.python.org/pep-0594/
        # We do not wait for it and remove them now in order to reduce overall size.
        # When deprecated libs are removed, this code can be removed as well.

        if PYTHON_VERSION < "3.12":
            os.remove(package_python_lib_dir / "asynchat.py")
            os.remove(package_python_lib_dir / "smtpd.py")

            # TODO: Do not remove the asyncore library because it is a requirement for our pysnmp monitor.
            #  We have to update the pysnmp library before the asyncore is removed from Python.
            # os.remove(package_python_lib_dir / "asyncore.py")

        if PYTHON_VERSION < "3.13":
            os.remove(package_python_lib_dir / "aifc.py")
            list(package_python_bindings_dir.glob("audioop.*.so"))[0].unlink()
            os.remove(package_python_lib_dir / "cgi.py")
            os.remove(package_python_lib_dir / "cgitb.py")
            os.remove(package_python_lib_dir / "chunk.py")
            os.remove(package_python_lib_dir / "crypt.py")
            os.remove(package_python_lib_dir / "imghdr.py")
            os.remove(package_python_lib_dir / "mailcap.py")
            os.remove(package_python_lib_dir / "nntplib.py")
            list(package_python_bindings_dir.glob("nis.*.so"))[0].unlink()
            list(package_python_bindings_dir.glob("ossaudiodev.*.so"))[0].unlink()
            os.remove(package_python_lib_dir / "pipes.py")
            os.remove(package_python_lib_dir / "sndhdr.py")
            list(package_python_bindings_dir.glob("spwd.*.so"))[0].unlink()
            os.remove(package_python_lib_dir / "sunau.py")
            os.remove(package_python_lib_dir / "telnetlib.py")
            os.remove(package_python_lib_dir / "uu.py")
            os.remove(package_python_lib_dir / "xdrlib.py")

        # Copy agent libraries venv
        venv_dependency_dir = dependencies_dir / "venv"

        package_venv_dir = package_opt_dir / "venv"
        package_venv_dir.mkdir()
        shutil.copytree(
            venv_dependency_dir,
            package_venv_dir,
            dirs_exist_ok=True,
            symlinks=True
        )

        # Recreate Python executables in venv and delete everything except them, since they are not needed.
        package_venv_bin_dir = package_venv_dir / "bin"
        shutil.rmtree(package_venv_bin_dir)
        package_venv_bin_dir.mkdir()
        package_venv_bin_dir_original_executable = package_venv_bin_dir / "python3-original"
        package_venv_bin_dir_original_executable.symlink_to(AGENT_OPT_DIR / "python3/bin/python3-original")

        package_venv_bin_python3_executable = package_venv_bin_dir / "python3"
        shutil.copy(
            SOURCE_ROOT / "agent_build_refactored/managed_packages/files/bin/venv-python3",
            package_venv_bin_python3_executable
        )

        package_venv_bin_python_executable = package_venv_bin_dir / "python"
        package_venv_bin_python_executable.symlink_to("python3")

        package_venv_bin_python_full_executable = package_venv_bin_dir / f"python{PYTHON_X_Y}"
        package_venv_bin_python_full_executable.symlink_to("python3")

        # Create core requirements file.
        core_requirements_file = package_opt_dir / "core-requirements.txt"
        core_requirements_file.write_text(AGENT_LIBS_REQUIREMENTS_CONTENT)

        # Copy additional requirements file.
        shutil.copy(
            SOURCE_ROOT / "agent_build_refactored/managed_packages/files/additional-requirements.txt",
            package_opt_etc_dir
        )

        # Copy script that allows configuring of the agent requirements.
        shutil.copy(
            SOURCE_ROOT / "agent_build_refactored/managed_packages/files/bin/agent-libs-config",
            package_opt_bin_dir
        )

        # Create /var/opt/ directory where agent's generated venv is stored.
        var_opt_dir = package_root / f"var/opt/{AGENT_SUBDIR_NAME}"
        var_opt_dir.mkdir(parents=True)

    def _build(self):

        agent_package_root = self.work_dir / "agent_package_root"

        self._prepare_package_python_and_libraries_files(
            package_root=agent_package_root
        )

        self._build_packages_common_files(
            package_root_path=agent_package_root
        )

        install_root_executable_path = (
            agent_package_root
            / f"usr/share/{AGENT_SUBDIR_NAME}/bin/scalyr-agent-2-new"
        )
        # Add agent's executable script.
        shutil.copy(
            SOURCE_ROOT
            / "agent_build_refactored/managed_packages/files/bin/scalyr-agent-2",
            install_root_executable_path,
        )

        # Also link agent executable to usr/sbin
        usr_sbin_executable = agent_package_root / "usr/sbin/scalyr-agent-2"
        usr_sbin_executable.unlink()
        usr_sbin_executable.symlink_to("../share/scalyr-agent-2/bin/scalyr-agent-2-new")

        # Also remove third party libraries except tcollector.
        agent_module_path = (
            agent_package_root / "usr/share/scalyr-agent-2/py/scalyr_agent"
        )
        third_party_libs_dir = agent_module_path / "third_party"
        shutil.rmtree(agent_module_path / "third_party_python2")
        shutil.rmtree(agent_module_path / "third_party_tls")
        shutil.rmtree(third_party_libs_dir)

        shutil.copytree(
            SOURCE_ROOT / "scalyr_agent/third_party/tcollector",
            third_party_libs_dir / "tcollector",
        )
        shutil.copy2(
            SOURCE_ROOT / "scalyr_agent/third_party/__init__.py",
            third_party_libs_dir / "__init__.py",
        )

        scriptlets_path = (
            SOURCE_ROOT
            / "agent_build_refactored/managed_packages/install-scriptlets"
        )

        description = (
            'Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics'
            ' and log files and transmit them to Scalyr. This is also the "All in one" package, that means that all '
            'dependencies that are required by the package bundled with it.'
        )

        # prepare packages changelogs
        changelogs_path = self.work_dir / "changelogs"
        changelogs_path.mkdir()
        create_change_logs(output_dir=changelogs_path)

        in_docker_package_root = self.to_in_docker_path(agent_package_root)
        in_docker_scriptlets_path = self.to_in_docker_path(scriptlets_path)
        in_docker_changelogs_dir = self.to_in_docker_path(changelogs_path)

        fpm_cmd_args = [
            # fmt: off
            *self.common_agent_package_build_args,
            "-s", "dir",
            "-a", cpu_arch_as_fpm_arch(arch=self.__class__.ARCHITECTURE),
            "-C", str(in_docker_package_root),
            "-n", AGENT_AIO_PACKAGE_NAME,
            "--provides", AGENT_AIO_PACKAGE_NAME,
            "--description", description,
            "--after-install", str(in_docker_scriptlets_path / "postinstall.sh"),
            "--before-remove", str(in_docker_scriptlets_path / "preuninstall.sh"),
            "--config-files", f"/opt/{AGENT_SUBDIR_NAME}/etc/preferred_openssl",
            "--config-files", f"/opt/{AGENT_SUBDIR_NAME}/etc/additional-requirements.txt",
            "--directories", f"/opt/{AGENT_SUBDIR_NAME}",
            "--directories", f"/var/opt/{AGENT_SUBDIR_NAME}",
            "--deb-changelog", str(in_docker_changelogs_dir / "changelog-deb"),
            "--rpm-changelog", str(in_docker_changelogs_dir / "changelog-rpm"),
            "--conflicts", AGENT_NON_AIO_AIO_PACKAGE_NAME
            # fmt: on
        ]

        self._build_all_packages(
            cmd_args=fpm_cmd_args,
        )




ALL_PACKAGE_BUILDERS: Dict[str, Union[Type[LinuxAIOPackagesBuilder], Type[LinuxNonAIOPackageBuilder]]] = {}

non_aio_builder_name = "non-aio"


class _LinuxNonAIOPackagesBuilder(LinuxNonAIOPackageBuilder):
    NAME = non_aio_builder_name


ALL_PACKAGE_BUILDERS[non_aio_builder_name] = _LinuxNonAIOPackagesBuilder

ALL_AIO_PACKAGE_BUILDERS: Dict[str, Type[LinuxAIOPackagesBuilder]] = {}

for package_arch in SUPPORTED_ARCHITECTURES:
    aio_builder_name = f"aio-{package_arch.value}"

    class _LinuxAIOPackagesBuilder(LinuxAIOPackagesBuilder):
        NAME = aio_builder_name
        ARCHITECTURE = package_arch

    ALL_PACKAGE_BUILDERS[aio_builder_name] = _LinuxAIOPackagesBuilder
    ALL_AIO_PACKAGE_BUILDERS[aio_builder_name] = _LinuxAIOPackagesBuilder


def get_package_builder_by_name(name: str):
    return ALL_PACKAGE_BUILDERS[name]