import pathlib as pl
import platform
import os
import json
import sys
import subprocess
import shutil
import stat

from agent_build.tools.runner import ShellScriptRunnerStep, Runner
from agent_build.tools.constants import Architecture, PackageType,SOURCE_ROOT
from agent_build.prepare_agent_filesystem import get_install_info

PYTHON_BASE = ShellScriptRunnerStep(
    name="python_glibc_2_12_base",
    script_path=pl.Path("agent_build/tools/environment_deployments/steps/frozen_binaries_prepare_base.sh"),
    architecture=Architecture.X86_64,
    base_step="centos:6",
    cacheable=True,
    cache_as_image=True
)

BUILD_PYTHON_GLIBC = ShellScriptRunnerStep(
    name="python_glibc_2_12_build_python",
    architecture=Architecture.X86_64,
    script_path=pl.Path("agent_build/tools/environment_deployments/steps/frozen_binaries_build_python.sh"),
    base_step=PYTHON_BASE,
    cacheable=True
)

INSTALL_AGENT_REQUIREMENTS = ShellScriptRunnerStep(
    name="python_glibc_2_12_build_agent_deps",
    architecture=Architecture.X86_64,
    script_path=pl.Path("agent_build/tools/environment_deployments/steps/frozen_binaries_build_python_dependencies.sh"),
    tracked_file_globs=[
        pl.Path("agent_build/requirement-files/main-requirements.txt"),
        pl.Path("agent_build/requirement-files/compression-requirements.txt"),
        pl.Path("agent_build/requirement-files/testing-requirements.txt"),
    ],
    environment_variables={
        "PYINSTALLER_VERSION": "4.7"
    },
    required_steps={
        "PYTHON_BUILD": BUILD_PYTHON_GLIBC,
    },
    base_step=PYTHON_BASE
)

PYTHON_GLIBC_WITH_AGENT_DEPS = ShellScriptRunnerStep(
    name="python_glibc_2_12_with_deps",
    architecture=Architecture.X86_64,
    script_path=pl.Path("agent_build/tools/environment_deployments/steps/frozen_binaries_python_with_agent_deps.sh"),
    required_steps={
        "PYTHON_BUILD": BUILD_PYTHON_GLIBC,
        "AGENT_DEPS": INSTALL_AGENT_REQUIREMENTS,
    },
    base_step=PYTHON_BASE,
    cacheable=True,
    cache_as_image=True
)
# ======

class FrozenBinaryAgentBuilder(Runner):
    NAME = "frozen_binary_agent_builder"
    BASE_ENVIRONMENT = PYTHON_GLIBC_WITH_AGENT_DEPS
    FROZEN_BINARY_FILENAME = "scalyr-agent-2"

    def __init__(
        self,
        install_type: str
    ):

        self.install_type = install_type

        super(FrozenBinaryAgentBuilder, self).__init__()

    @property
    def frozen_binary_filename(self):
        filename = type(self).FROZEN_BINARY_FILENAME
        if platform.system().lower().startswith("win"):
            filename = f"{filename}.exe"
        return filename

    @property
    def frozen_binary_path(self):
        return self.frozen_binaries_dir_path / self.frozen_binary_filename

    @property
    def frozen_binaries_dir_path(self):
        return self.output_path / "frozen_binaries"

    def _build(self):
        scalyr_agent_package_path = SOURCE_ROOT / "scalyr_agent"

        # Add monitor modules as hidden imports, since they are not directly imported in the agent's code.
        all_builtin_monitor_module_names = [
            f"scalyr_agent.builtin_monitors.{mod_path.stem}"
            for mod_path in pl.Path(
                SOURCE_ROOT, "scalyr_agent", "builtin_monitors"
            ).glob("*.py")
            if mod_path.stem != "__init__"
        ]

        # Define builtin monitors that have to be excluded from particular platform.
        if platform.system().lower().startswith("linux"):
            monitors_to_exclude = [
                "scalyr_agent.builtin_monitors.windows_event_log_monitor",
                "scalyr_agent.builtin_monitors.windows_system_metrics",
                "scalyr_agent.builtin_monitors.windows_process_metrics",
            ]
        elif platform.system().lower().startswith("win"):
            monitors_to_exclude = [
                "scalyr_agent.builtin_monitors.linux_process_metrics.py",
                "scalyr_agent.builtin_monitors.linux_system_metrics.py"
            ]
        else:
            monitors_to_exclude = []

        monitors_to_import = set(all_builtin_monitor_module_names) - set(monitors_to_exclude)

        # Add packages to frozen binary paths.
        paths_to_include = [
            str(scalyr_agent_package_path),
            str(scalyr_agent_package_path / "builtin_monitors"),
        ]

        agent_package_path = os.path.join(SOURCE_ROOT, "scalyr_agent")

        instalL_info_path = self.output_path / "install_info.json"

        install_info = get_install_info(
            install_type=self.install_type
        )

        instalL_info_path.write_text(json.dumps(install_info))

        version_file_path = SOURCE_ROOT / "VERSION"
        add_data = {
            instalL_info_path: "scalyr_agent",
            version_file_path: "scalyr_agent"
        }

        # Add platform specific things.
        if platform.system().lower().startswith("linux"):
            tcollectors_path = pl.Path(
                SOURCE_ROOT,
                "scalyr_agent",
                "third_party",
                "tcollector",
                "collectors",
            )
            paths_to_include.append(tcollectors_path)
            add_data[tcollectors_path] = "scalyr_agent/third_party/tcollector/collectors"

        hidden_imports = [*monitors_to_import, "win32timezone"]

        # Create --add-data options from previously added files.
        add_data_options = []
        for src, dest in add_data.items():
            add_data_options.append("--add-data")
            add_data_options.append("{}{}{}".format(src, os.path.pathsep, dest))

        # Create --hidden-import options from previously created hidden imports list.
        hidden_import_options = []
        for h in hidden_imports:
            hidden_import_options.append("--hidden-import")
            hidden_import_options.append(str(h))

        paths_options = []
        for p in paths_to_include:
            paths_options.extend(["--paths", p])

        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            #"--onefile",
            "-n",
            "scalyr-agent-2",
            os.path.join(agent_package_path, "agent_main_arg_parse.py"),
        ]
        command.extend(add_data_options)
        command.extend(hidden_import_options)
        command.extend(paths_options)
        command.extend(
            [
                "--exclude-module",
                "asyncio",
                "--exclude-module",
                "FixTk",
                "--exclude-module",
                "tcl",
                "--exclude-module",
                "tk",
                "--exclude-module",
                "_tkinter",
                "--exclude-module",
                "tkinter",
                "--exclude-module",
                "Tkinter",
                "--exclude-module",
                "sqlite",
            ]
        )

        pyinstaller_output = self.output_path / "pyinstaller"
        pyinstaller_output.mkdir(parents=True)

        subprocess.check_call(
            command,
            cwd=str(pyinstaller_output)
        )

        frozen_binaries_path = pyinstaller_output / "dist/scalyr-agent-2"
        agent_frozen_binary_path = frozen_binaries_path / self.frozen_binary_filename
        # Make frozen binary executable.
        agent_frozen_binary_path.chmod(
            agent_frozen_binary_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
        )

        shutil.copytree(
            frozen_binaries_path,
            self.frozen_binaries_dir_path
        )

        subprocess.check_call(
            f"ls {self.output_path}", shell=True
        )


PREPARE_FPM_BUILDER = ShellScriptRunnerStep(
    name="fpm_builder",
    architecture=Architecture.X86_64,
    script_path=pl.Path("agent_build/tools/environment_deployments/steps/prepare_fpm_builder.sh"),
    tracked_file_globs=[
        pl.Path("agent_build/requirement-files/requirements.txt")
    ],
    required_steps={
        "PYTHON_BUILD": BUILD_PYTHON_GLIBC,
        "AGENT_DEPS": INSTALL_AGENT_REQUIREMENTS,
    },
    base_step="ubuntu:20.04",
    cacheable=True,
    cache_as_image=True
)


class FpmBasedPackageBuilder(Runner):
    ARCHITECTURE: Architecture
    PACKAGE_TYPE: PackageType
    REQUIRED_RUNNERS_CLASSES = [FrozenBinaryAgentBuilder]
    BASE_ENVIRONMENT = PREPARE_FPM_BUILDER
    RESULT_FILENAME_GLOB_FORMAT: str

    _FPM_PACKAGE_TYPES = {
        PackageType.DEB: "deb",
        PackageType.RPM: "rpm"
    }
    _FPM_ARCHITECTURES = {
        PackageType.DEB: {
            Architecture.X86_64: "amd64",
            Architecture.ARM64: "arm64"
        },
        PackageType.RPM: {
            Architecture.X86_64: "x86_64",
            Architecture.ARM64: "aarch64"
        }
    }

    def __init__(
            self,
            version: str = None,
            variant: str = None
    ):
        self.version = version
        if not self.version:
            version_file_path = SOURCE_ROOT / "VERSION"
            self.version = version_file_path.read_text().strip()

        self.variant = variant

        self.build_frozen_binary = FrozenBinaryAgentBuilder(
            install_type="package",
        )

        super(FpmBasedPackageBuilder, self).__init__(
            required_runners=[self.build_frozen_binary]
        )

    @property
    def result_file_path(self):
        cls = type(self)
        package_architectures = cls._FPM_ARCHITECTURES[cls.PACKAGE_TYPE]
        glob = cls.RESULT_FILENAME_GLOB_FORMAT.format(
            version=self.version,
            arch=package_architectures[cls.ARCHITECTURE]
        )

        print(glob)
        files = list(self.output_path.glob(glob))
        print(list(files))
        print(list(self.output_path.iterdir()))
        assert len(files) == 1, "Only one result package file is expected."
        result_path = files[0]
        assert result_path.is_file(), "Result is not a file."
        return result_path

    def _build(self):

        build_linux_lfs_agent_files(
            output_path=self._package_root_path,
            version=self.version,
            config_path=SOURCE_ROOT / "config",
            frozen_binary_path=self.build_frozen_binary.frozen_binaries_dir_path
        )

        # Add init.d script.
        init_d_path = self._package_root_path / "etc/init.d"
        init_d_path.mkdir()
        shutil.copy2(
            _AGENT_BUILD_PATH / "linux/deb_or_rpm/files/init.d/scalyr-agent-2",
            init_d_path
        )

        if self.variant is not None:
            iteration_arg = "--iteration 1.%s" % self.variant
        else:
            iteration_arg = ""

        install_scripts_path = SOURCE_ROOT / "installer/scripts"

        # generate changelogs
        changelogs_path = self.output_path / "package_changelogs"
        create_change_logs(
            output_directory=changelogs_path
        )

        description = (
            "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics and "
            "log files and transmit them to Scalyr."
        )

        # filename = f"scalyr-agent-2_{self._package_version}_{arch}.{ext}"

        cls = type(self)
        fpm_architectures = cls._FPM_ARCHITECTURES[cls.PACKAGE_TYPE]
        # fmt: off
        fpm_command = [
            "fpm",
            "-s", "dir",
            "-a", fpm_architectures[cls.ARCHITECTURE],
            "-t", cls._FPM_PACKAGE_TYPES[cls.PACKAGE_TYPE],
            "-n", "scalyr-agent-2",
            "-v", self.version,
            "--chdir", str(self._package_root_path),
            "--license", "Apache 2.0",
            "--vendor", f"Scalyr {iteration_arg}",
            "--maintainer", "czerwin@scalyr.com",
            "--provides", "scalyr-agent-2",
            "--description", description,
            "--depends", 'bash >= 3.2',
            "--url", "https://www.scalyr.com",
            "--deb-user", "root",
            "--deb-group", "root",
            "--deb-changelog", str(changelogs_path / 'changelog-deb'),
            "--rpm-changelog", str(changelogs_path / 'changelog-rpm'),
            "--rpm-user", "root",
            "--rpm-group", "root",
            "--after-install", str(install_scripts_path / 'postinstall.sh'),
            "--before-remove", str(install_scripts_path / 'preuninstall.sh'),
            "--deb-no-default-config-files",
            "--no-deb-auto-config-files",
            "--config-files", "/etc/scalyr-agent-2/agent.json",
            "--directories", "/usr/share/scalyr-agent-2",
            "--directories", "/var/lib/scalyr-agent-2",
            "--directories", "/var/log/scalyr-agent-2",
            # NOTE 1: By default fpm won't preserve all the permissions we set on the files so we need
            # to use those flags.
            # If we don't do that, fpm will use 77X for directories and we don't really want 7 for
            # "group" and it also means config file permissions won't be correct.
            # NOTE 2: This is commented out since it breaks builds produced on builder VM where
            # build_package.py runs as rpmbuilder user (uid 1001) and that uid is preserved as file
            # owner for the package tarball file which breaks things.
            # On Circle CI uid of the user under which the package job runs is 0 aka root so it works
            # fine.
            # We don't run fpm as root on builder VM which means we can't use any other workaround.
            # Commenting this flag out means that original file permissions (+ownership) won't be
            # preserved which means we will also rely on postinst step fixing permissions for fresh /
            # new installations since those permissions won't be correct in the package artifact itself.
            # Not great.
            # Once we move all the build steps to Circle CI and ensure build_package.py runs as uid 0
            # we should uncomment this.
            # In theory it should work wth --*-user fpm flag, but it doesn't. Keep in mind that the
            # issue only applies to deb packages since --rpm-user and --rpm-root flag override the user
            # even if the --rpm-use-file-permissions flag is used.
            # "  --rpm-use-file-permissions "
            "--rpm-use-file-permissions",
            "--deb-use-file-permissions",
            # NOTE: Sadly we can't use defattrdir since it breakes permissions for some other
            # directories such as /etc/init.d and we need to handle that in postinst :/
            # "  --rpm-auto-add-directories "
            # "  --rpm-defattrfile 640"
            # "  --rpm-defattrdir 751"
            # "  -C root usr etc var",
        ]
        # fmt: on

        # Run fpm command and build the package.
        subprocess.check_call(
            fpm_command,
            cwd=str(self.output_path),
        )


BUILDERS_BUILDERS = {}

for arch in [
    Architecture.X86_64
]:
    class DebPackageBuilder(FpmBasedPackageBuilder):
        NAME = f"deb_{arch.value}"
        ARCHITECTURE = arch
        PACKAGE_TYPE = PackageType.DEB
        INSTALL_TYPE = "package"
        RESULT_FILENAME_GLOB_FORMAT = "scalyr-agent-2_{version}_{arch}.deb"

    class RpmPackageBuilder(FpmBasedPackageBuilder):
        NAME = f"rpm_{arch.value}"
        ARCHITECTURE = arch
        PACKAGE_TYPE = PackageType.RPM
        INSTALL_TYPE = "package"
        RESULT_FILENAME_GLOB_FORMAT = "scalyr-agent-2-{version}-1.{arch}.rpm"

    BUILDERS_BUILDERS.update({
        DebPackageBuilder.NAME: DebPackageBuilder,
        RpmPackageBuilder.NAME: RpmPackageBuilder
    })
