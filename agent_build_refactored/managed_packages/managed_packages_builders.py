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
import logging
import os
import shutil
import subprocess
import argparse
import pathlib as pl
import re
from typing import List, Tuple, Optional, Dict, Type

from agent_build_refactored.managed_packages.build_dependencies_versions import (
    EMBEDDED_PYTHON_VERSION,
)


from agent_build_refactored.tools import UniqueDict

from agent_build_refactored.tools.runner import (
    Runner,
    RunnerStep,
    EnvironmentRunnerStep,
    IN_DOCKER,
)
from agent_build_refactored.tools.constants import (
    SOURCE_ROOT,
    Architecture,
    REQUIREMENTS_COMMON,
    REQUIREMENTS_COMMON_PLATFORM_DEPENDENT,
)
from agent_build_refactored.tools import check_call_with_log
from agent_build_refactored.prepare_agent_filesystem import (
    build_agent_linux_fhs_common_files,
    add_config,
    create_change_logs,
    render_agent_executable_script,
)

from agent_build_refactored.build_python.steps import build_agent_libs_venv

from agent_build_refactored.build_python.build_python_steps import (
    SUPPORTED_ARCHITECTURES,
    AGENT_SUBDIR_NAME,
    AGENT_OPT_DIR,
    PYTHON_INSTALL_PREFIX,
    EMBEDDED_PYTHON_SHORT_VERSION,
    EMBEDDED_PYTHON_PIP_VERSION,
    create_python_files,
    create_agent_libs_venv_files,
    ALL_DEPENDENCY_TOOLCHAINS,
    CRuntime,
    PREPARE_TOOLSET_STEP_GLIBC_X86_64,
    create_new_steps_for_all_toolchains,
    DependencyToolchain
)

logger = logging.getLogger(__name__)

FILES_DIR = pl.Path(__file__).parent.absolute() / "files"

# Name of the dependency package with Python interpreter.
PYTHON_PACKAGE_NAME = "scalyr-agent-python3"

# name of the dependency package with agent requirement libraries.
AGENT_LIBS_PACKAGE_NAME = "scalyr-agent-libs"

AGENT_AIO_PACKAGE_NAME = "scalyr-agent-2-aio"
AGENT_NON_AIO_AIO_PACKAGE_NAME = "scalyr-agent-2"


AGENT_LIBS_REQUIREMENTS_CONTENT = (
    f"{REQUIREMENTS_COMMON}\n" f"{REQUIREMENTS_COMMON_PLATFORM_DEPENDENT}"
)


class LinuxPackageBuilder(Runner):
    """
    This is a base class that is responsible for the building of the Linux agent deb and rpm packages that are managed
        by package managers such as apt and yum.
    """

    # type of the package, aka 'deb' or 'rpm'
    PACKAGE_TYPE: str

    @classmethod
    def get_base_environment(cls) -> EnvironmentRunnerStep:
        """
        Packages should be built inside our "toolset" image, which has toos required for package build, like fpm.
        """
        return PREPARE_TOOLSET_STEP_GLIBC_X86_64

    @property
    def packages_output_path(self) -> pl.Path:
        """
        Directory path with result packages.
        """
        return self.output_path / "packages"

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

    @abc.abstractmethod
    def build_agent_package(self):
        pass

    @staticmethod
    def _build_packages_common_files(
        package_root_path: pl.Path,
        agent_executable_name: str
    ):
        """
        Build files that are common for all types of linux packages.
        :param package_root_path: Path with package root.
        :param agent_executable_name: Name of the agent's executable in its install root.
        """
        build_agent_linux_fhs_common_files(
            output_path=package_root_path,
            agent_executable_name=agent_executable_name
        )

        # remove Python cache directories from agent's source code.
        for path in package_root_path.rglob("__pycache__/"):
            if path.is_file():
                continue
            shutil.rmtree(path)

        # Copy init.d folder.
        shutil.copytree(
            SOURCE_ROOT / "agent_build_refactored/managed_packages/files/init.d",
            package_root_path / "etc/init.d",
            dirs_exist_ok=True,
        )

        # Add config file
        add_config(SOURCE_ROOT / "config", package_root_path / "etc/scalyr-agent-2")

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(LinuxPackageBuilder, cls).add_command_line_arguments(parser=parser)

        subparsers = parser.add_subparsers(dest="command")

        subparsers.add_parser("build", help="Build needed packages.")

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(LinuxPackageBuilder, cls).handle_command_line_arguments(args=args)

        work_dir = pl.Path(args.work_dir)

        builder = cls(work_dir=work_dir)

        if args.command == "build":
            builder.build_agent_package()
            if not IN_DOCKER:
                output_path = SOURCE_ROOT / "build"
                if output_path.exists():
                    shutil.rmtree(output_path)
                shutil.copytree(
                    builder.packages_output_path,
                    output_path,
                    dirs_exist_ok=True,
                )

        else:
            logging.error(f"Unknown command {args.command}.")
            exit(1)


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

        source_scriptlets_path = (
            SOURCE_ROOT
            / "agent_build_refactored/managed_packages/non-aio/install-scriptlets"
        )

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

    def build_agent_package(self):
        self.prepare_runer()

        # Run inside the docker if needed.
        if self.runs_in_docker:
            command_args = ["build"]
            self.run_in_docker(command_args=command_args)
            return

        agent_package_root = self.output_path / "agent_package_root"

        self._build_packages_common_files(
            package_root_path=agent_package_root,
            agent_executable_name="scalyr-agent-2"
        )

        agent_install_root = agent_package_root / f"usr/share" / AGENT_SUBDIR_NAME
        bin_path = agent_install_root / "bin"
        agent_main_executable_path = bin_path / "scalyr-agent-2"
        agent_main_executable_path.symlink_to(
            pl.Path("..", "py", "scalyr_agent", "agent_main.py")
        )

        # Copy switch python executable script to package's bin
        switch_python_source = (
            SOURCE_ROOT
            / "agent_build_refactored/managed_packages/non-aio/files/bin/scalyr-switch-python.sh"
        )

        switch_python_executable_name = "scalyr-switch-python"
        package_switch_python_executable = bin_path / switch_python_executable_name
        shutil.copy(switch_python_source, package_switch_python_executable)
        sbin_python_switch_executable = (
            agent_package_root / "usr/sbin" / switch_python_executable_name
        )
        sbin_python_switch_executable.symlink_to(
            f"/usr/share/{AGENT_SUBDIR_NAME}/bin/{switch_python_executable_name}"
        )

        # Create copies of the agent_main.py with python2 and python3 shebang.
        agent_main_path = SOURCE_ROOT / "scalyr_agent/agent_main.py"
        agent_package_path = agent_install_root / "py/scalyr_agent"

        agent_main_py2_path = agent_package_path / "agent_main_py2.py"
        agent_main_py3_path = agent_package_path / "agent_main_py3.py"

        agent_main_content = agent_main_path.read_text()
        agent_main_py2_path.write_text(
            agent_main_content.replace(
                "#!/usr/bin/env python", "#!/usr/bin/env python2"
            )
        )
        agent_main_py3_path.write_text(
            agent_main_content.replace(
                "#!/usr/bin/env python", "#!/usr/bin/env python3"
            )
        )
        main_permissions = os.stat(agent_main_path).st_mode
        os.chmod(agent_main_py2_path, main_permissions)
        os.chmod(agent_main_py3_path, main_permissions)

        # Create package installation scriptlets
        scriptlets_path = self.output_path / "scriptlets"
        scriptlets_path.mkdir()
        self._create_non_aio_package_scriptlets(output_dir=scriptlets_path)

        description = (
            "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics"
            " and log files and transmit them to Scalyr."
        )

        # prepare packages changelogs
        changelogs_path = self.output_path / "changelogs"
        changelogs_path.mkdir()
        create_change_logs(output_dir=changelogs_path)

        package_output_dir = self.packages_output_path / self.PACKAGE_TYPE
        package_output_dir.mkdir(parents=True, exist_ok=True)

        subprocess.check_call(
            [
                # fmt: off
                *self.common_agent_package_build_args,
                "-s", "dir",
                "-a", "all",
                "-t", self.PACKAGE_TYPE,
                "-C", str(agent_package_root),
                "-n", AGENT_NON_AIO_AIO_PACKAGE_NAME,
                "--provides", AGENT_NON_AIO_AIO_PACKAGE_NAME,
                "--description", description,
                # NOTE: We leave those two files in place since they are symlinks which might have been
                # updated by scalyr-switch-python and we want to leave this in place - aka make sure
                # selected Python version is preserved on upgrade
                "--config-files", f"/usr/share/{AGENT_SUBDIR_NAME}/bin/scalyr-agent-2",
                "--before-install", scriptlets_path / "preinstall.sh",
                "--after-install", scriptlets_path / "postinstall.sh",
                "--before-remove", scriptlets_path / "preuninstall.sh",
                "--deb-changelog", str(changelogs_path / "changelog-deb"),
                "--rpm-changelog", str(changelogs_path / "changelog-rpm"),
                "--conflicts", AGENT_AIO_PACKAGE_NAME
                # fmt: on
            ],
            cwd=str(package_output_dir),
        )


class LinuxAIOPackagesBuilder(LinuxPackageBuilder):
    # C runtime which has to be used to ompile package dependencies.
    C_RUNTIME = CRuntime.GLIBC
    """
    This builder creates "all in one" (aio) version of the agent package.
    That means that this package does not have any system dependencies, except glibc.
    """

    # package architecture, for example: amd64 for deb.
    DEPENDENCY_PACKAGES_ARCHITECTURE: Architecture

    @classmethod
    def get_all_required_steps(cls) -> List[RunnerStep]:

        toolchain = cls._get_toolchain()
        return [
            toolchain.openssl_1,
            toolchain.openssl_3,
            toolchain.python_with_openssl_1,
            toolchain.python_with_openssl_3,
            cls._get_agent_libs_step(),
        ]

    @classmethod
    def _get_toolchain(cls):
        return ALL_DEPENDENCY_TOOLCHAINS[cls.C_RUNTIME][cls.DEPENDENCY_PACKAGES_ARCHITECTURE]

    @classmethod
    def _get_agent_libs_step(cls):
        return BUILD_AGENT_LIBS_VENV_STEPS[cls.C_RUNTIME][cls.DEPENDENCY_PACKAGES_ARCHITECTURE]

    def _prepare_package_python_and_libraries_files(self, package_root: pl.Path):
        """
        Prepare package files of the Python interpreter and agent libraries.
        :param package_root: Path to the package root.
        """

        toolchain = self._get_toolchain()

        python_with_openssl_1_step = toolchain.python_with_openssl_1
        python_with_openssl_3_step = toolchain.python_with_openssl_3

        build_python_with_openssl_3_step_output = toolchain.python_with_openssl_3.get_output_directory(
            work_dir=self.work_dir
        )

        relative_python_install_prefix = pl.Path(PYTHON_INSTALL_PREFIX).relative_to("/")
        package_opt_dir = package_root / AGENT_OPT_DIR.relative_to("/")

        package_python_dir = package_root / relative_python_install_prefix

        create_python_files(
            build_python_step_output=build_python_with_openssl_3_step_output,
            output=package_root,
            additional_ld_library_paths=f"{AGENT_OPT_DIR}/lib/openssl/current/libs"
        )

        package_openssl_dir = package_opt_dir / "lib/openssl"

        python_ssl_bindings_glob = "_ssl.cpython-*-*-*-*.so"
        python_hashlib_bindings_glob = "_hashlib.cpython-*-*-*-*.so"

        def copy_openssl_binding_files(
            build_python_step: RunnerStep,
            openssl_major_version: int,
        ):
            """# This function copies Python's ssl module related files."""

            # Copy _ssl and _hashlib modules.
            build_python_step_dir = build_python_step.get_output_directory(
                work_dir=self.work_dir
            )
            python_step_bindings_dir = (
                build_python_step_dir
                / relative_python_install_prefix
                / f"lib/python{EMBEDDED_PYTHON_SHORT_VERSION}/lib-dynload"
            )

            ssl_binding_path = list(
                python_step_bindings_dir.glob(python_ssl_bindings_glob)
            )[0]
            hashlib_binding_path = list(
                python_step_bindings_dir.glob(python_hashlib_bindings_glob)
            )[0]

            bindings_dir = package_openssl_dir / str(openssl_major_version) / "bindings"
            bindings_dir.mkdir(parents=True)

            shutil.copy(ssl_binding_path, bindings_dir)
            shutil.copy(hashlib_binding_path, bindings_dir)

        # Copy ssl modules which are compiled for OpenSSL 1.1.1
        copy_openssl_binding_files(
            build_python_step=python_with_openssl_1_step,
            openssl_major_version=1,
        )

        # Copy ssl modules which are compiled for OpenSSL 3
        copy_openssl_binding_files(
            build_python_step=python_with_openssl_3_step,
            openssl_major_version=3
        )

        # Create directory for the embedded OpenSSL files.
        embedded_openssl_dir = package_openssl_dir / "embedded"
        embedded_openssl_dir.mkdir()
        # Since we use OpenSSL 3 for embedded, we link to the previously created C bindings of the OpenSSL 3.
        embedded_openssl_bindings = embedded_openssl_dir / "bindings"
        embedded_openssl_bindings.symlink_to("../3/bindings")
        # Copy shared libraries of the embedded OpenSSL 3 from the step that builds it.
        embedded_openssl_3_libs_dir = embedded_openssl_dir / "libs"
        embedded_openssl_3_libs_dir.mkdir(parents=True)

        build_openssl_3_step = toolchain.openssl_3
        build_openssl_3_step_dir = build_openssl_3_step.get_output_directory(
            work_dir=self.work_dir
        )


        build_openssl_3_libs_dir = build_openssl_3_step_dir / "usr/local/lib"
        for path in build_openssl_3_libs_dir.glob("*.so.*"):
            shutil.copy(path, embedded_openssl_3_libs_dir)

        # Create the `current` symlink which by default targets the embedded OpenSSL.
        package_current_openssl_dir = package_openssl_dir / "current"
        package_current_openssl_dir.symlink_to("./embedded")

        # Remove original bindings from Python interpreter and replace them with symlinks.
        package_python_lib_dir = (
            package_python_dir / f"lib/python{EMBEDDED_PYTHON_SHORT_VERSION}"
        )
        package_python_bindings_dir = package_python_lib_dir / "lib-dynload"
        ssl_binding_path = list(
            package_python_bindings_dir.glob(python_ssl_bindings_glob)
        )[0]
        hashlib_binding_path = list(
            package_python_bindings_dir.glob(python_hashlib_bindings_glob)
        )[0]
        ssl_binding_path.unlink()
        hashlib_binding_path.unlink()
        ssl_binding_path.symlink_to(
            f"../../../../lib/openssl/current/bindings/{ssl_binding_path.name}"
        )
        hashlib_binding_path.symlink_to(
            f"../../../../lib/openssl/current/bindings/{hashlib_binding_path.name}"
        )

        # Copy executables that allows to configure the Python interpreter.
        package_opt_bin_dir = package_opt_dir / "bin"
        package_opt_bin_dir.mkdir(parents=True)
        shutil.copy(
            FILES_DIR / "bin/agent-python3-config",
            package_opt_bin_dir
        )

        # Copy Python interpreter's configuration files.
        package_opt_etc_dir = package_opt_dir / "etc"
        package_opt_etc_dir.mkdir()
        preferred_openssl_file = package_opt_etc_dir / "preferred_openssl"
        preferred_openssl_file.write_text("auto")

        # Copy agent libraries venv
        build_agent_libs_venv_step = self._get_agent_libs_step()
        build_agent_libs_venv_step_output = build_agent_libs_venv_step.get_output_directory(
            work_dir=self.work_dir
        )
        create_agent_libs_venv_files(
            build_libs_venv_step_output=build_agent_libs_venv_step_output,
            output=package_opt_dir / "venv"
        )

        # Create core requirements file.
        core_requirements_file = package_opt_dir / "core-requirements.txt"
        core_requirements_file.write_text(AGENT_LIBS_REQUIREMENTS_CONTENT)

        # Copy additional requirements file.
        shutil.copy(
            FILES_DIR / "additional-requirements.txt",
            package_opt_etc_dir,
        )

        # Copy script that allows configuring of the agent requirements.
        shutil.copy(
            FILES_DIR / "bin/agent-libs-config",
            package_opt_bin_dir,
        )

        # Create /var/opt/ directory where agent's generated venv is stored.
        var_opt_dir = package_root / f"var/opt/{AGENT_SUBDIR_NAME}"
        var_opt_dir.mkdir(parents=True)

    def build_agent_package(self):
        self.prepare_runer()

        # Run inside the docker if needed.
        if self.runs_in_docker:
            command_args = ["build"]
            self.run_in_docker(command_args=command_args)
            return

        agent_package_root = self.output_path / "agent_package_root"

        self._prepare_package_python_and_libraries_files(
            package_root=agent_package_root
        )

        agent_executable_name = "scalyr-agent-2-new"
        self._build_packages_common_files(
            package_root_path=agent_package_root,
            agent_executable_name=agent_executable_name
        )

        install_root_executable_path = (
            agent_package_root / f"usr/share/{AGENT_SUBDIR_NAME}/bin/{agent_executable_name}"
        )

        # Create agent's executable script.
        render_agent_executable_script(
            python_executable=pl.Path("/var/opt/scalyr-agent-2/venv/bin/python3"),
            agent_main_script_path=pl.Path("/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py"),
            output_file=install_root_executable_path
        )

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
            SOURCE_ROOT / "agent_build_refactored/managed_packages/install-scriptlets"
        )

        description = (
            "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics"
            ' and log files and transmit them to Scalyr. This is also the "All in one" package, that means that all '
            "dependencies that are required by the package bundled with it."
        )

        package_arch = self.DEPENDENCY_PACKAGES_ARCHITECTURE.get_package_arch(
            package_type=self.PACKAGE_TYPE
        )

        # prepare packages changelogs
        changelogs_path = self.output_path / "changelogs"
        changelogs_path.mkdir()
        create_change_logs(output_dir=changelogs_path)

        package_output_dir = self.packages_output_path / self.PACKAGE_TYPE
        package_output_dir.mkdir(parents=True, exist_ok=True)

        subprocess.check_call(
            [
                # fmt: off
                *self.common_agent_package_build_args,
                "-s", "dir",
                "-a", package_arch,
                "-t", self.PACKAGE_TYPE,
                "-C", str(agent_package_root),
                "-n", AGENT_AIO_PACKAGE_NAME,
                "--provides", AGENT_AIO_PACKAGE_NAME,
                "--description", description,
                "--after-install", scriptlets_path / "postinstall.sh",
                "--before-remove", scriptlets_path / "preuninstall.sh",
                "--config-files", f"/opt/{AGENT_SUBDIR_NAME}/etc/preferred_openssl",
                "--config-files", f"/opt/{AGENT_SUBDIR_NAME}/etc/additional-requirements.txt",
                "--directories", f"/opt/{AGENT_SUBDIR_NAME}",
                "--directories", f"/var/opt/{AGENT_SUBDIR_NAME}",
                "--deb-changelog", str(changelogs_path / "changelog-deb"),
                "--rpm-changelog", str(changelogs_path / "changelog-rpm"),
                "--conflicts", AGENT_NON_AIO_AIO_PACKAGE_NAME
                # fmt: on
            ],
            cwd=str(package_output_dir),
        )


# Create steps that build agent requirement libs inside venv.
def create_build_agent_libs_venv_step_for_linux_packages(
        toolchain: DependencyToolchain
):

    name_suffix = f"{toolchain.c_runtime.value}_{toolchain.architecture.value}"
    return build_agent_libs_venv.create_step(
        name_suffix=name_suffix,
        install_build_environment_step=toolchain.install_build_environment,
        build_openssl_step=toolchain.openssl_1,
        build_python_step=toolchain.python_with_openssl_1,
        build_dev_requirements_step=toolchain.dev_requirements,
        python_install_prefix=PYTHON_INSTALL_PREFIX,
        agent_subdir_name=AGENT_SUBDIR_NAME,
        pip_version=EMBEDDED_PYTHON_PIP_VERSION,
        requirements_file_content=AGENT_LIBS_REQUIREMENTS_CONTENT,
        run_in_remote_docker=toolchain.architecture != Architecture.X86_64
    )


BUILD_AGENT_LIBS_VENV_STEPS = create_new_steps_for_all_toolchains(
    create_step_fn=create_build_agent_libs_venv_step_for_linux_packages
)

ALL_MANAGED_PACKAGE_BUILDERS: Dict[str, Type[LinuxPackageBuilder]] = UniqueDict()


for package_type in ["deb", "rpm"]:
    # Iterate through all supported architectures and create package builders classes for each.
    for arch in SUPPORTED_ARCHITECTURES:
        class _LinuxAIOPackagesBuilder(LinuxAIOPackagesBuilder):
            PACKAGE_TYPE = package_type
            DEPENDENCY_PACKAGES_ARCHITECTURE = arch
            CLASS_NAME_ALIAS = f"{package_type}LinuxAIOPackagesBuilder{arch.value}"
            ADD_TO_GLOBAL_RUNNER_COLLECTION = True

        builder_name = f"{package_type}-aio-{arch.value}"
        ALL_MANAGED_PACKAGE_BUILDERS[builder_name] = _LinuxAIOPackagesBuilder

    # Also create non-aio package builder for each package type
    class _LinuxNonAIOPackageBuilder(LinuxNonAIOPackageBuilder):
        PACKAGE_TYPE = package_type
        CLASS_NAME_ALIAS = f"{package_type}LinuxNonAIOPackagesBuilder"
        ADD_TO_GLOBAL_RUNNER_COLLECTION = True

    ALL_MANAGED_PACKAGE_BUILDERS[f"{package_type}-non-aio"] = _LinuxNonAIOPackageBuilder
