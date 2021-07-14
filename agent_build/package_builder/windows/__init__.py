import os
import pathlib as pl
import shutil
import subprocess
from typing import Union
import uuid

from agent_build.package_builder import builder
from agent_build import common

# A GUID representing Scalyr products, used to generate a per-version guid for each version of the Windows
# Scalyr Agent.  DO NOT MODIFY THIS VALUE, or already installed software on clients machines will not be able
# to be upgraded.
_scalyr_guid_ = uuid.UUID("{0b52b8a0-22c7-4d50-92c1-8ea3b258984e}")

_PARENT_DIR = pl.Path(__file__).absolute().parent

_PREPARE_ENVIRONMENT_SCRIPT = _PARENT_DIR / "prepare_environment.ps1"


class WindowsMsiPackageBuilder(builder.PackageBuilder):
    PACKAGE_TYPE_NAME = "msi"

    @classmethod
    def _get_used_files(cls):
        return [
            _PREPARE_ENVIRONMENT_SCRIPT,
            _PARENT_DIR / "requirements.txt",
            common.SOURCE_ROOT / "agent_build" / "requirements.txt"
        ]

    def prepare_dependencies(
            self,
            cache_dir:
            Union[str, pl.Path] = None,
    ):
        subprocess.check_call(
            f"powershell {_PREPARE_ENVIRONMENT_SCRIPT} {cache_dir}", shell=True
        )

    def _build(
            self,
            build_info: common.PackageBuildInfo,
            output_path: Union[str, pl.Path]
    ):
        self._package_filesystem_root = self._package_filesystem_root / "Scalyr"
        self.build_base_files(
            output_path=self._package_filesystem_root
        )

        certs_path = self._package_filesystem_root / "certs"
        certs_path.mkdir()
        builder.add_certs(
            certs_path,
            intermediate_certs=False,
            copy_other_certs=False
        )

        # Write a special file to specify the type of the package.
        package_type_file = self._package_filesystem_root / "install_type"
        package_type_file.write_text("package")

        self._build_frozen_binary()

        bin_path = self._package_filesystem_root / "bin"

        shutil.copytree(self._frozen_binary_output, bin_path)

        shutil.copy(
            _PARENT_DIR / "ScalyrShell.cmd",
            bin_path
        )
        # b = os.getcwd()
        # os.chdir(bin_path)
        # for binary_name in ["scalyr-agent-2.exe", "scalyr-agent-2-config", "ScalyrAgentService"]:
        #     symlink_path = pl.Path(frozen_bin_path / binary_name)
        #     print(symlink_path)
        #
        #
        #     os.symlink(pl.Path("frozen", binary_name), binary_name)
        #
        #     #symlink_path.symlink_to()
        # os.chdir(b)

        config_templates_dir_path = pl.Path(self._package_filesystem_root / "config" / "templates")
        config_templates_dir_path.mkdir(parents=True)
        config_template_path = config_templates_dir_path / "agent_config.tmpl"
        shutil.copy2(common.SOURCE_ROOT / "config" / "agent.json", config_template_path)

        config_template_path.write_text(config_template_path.read_text().replace("\n", "\r\n"))


        if build_info.variant is None:
            variant = "main"

        # Generate a unique identifier used to identify this version of the Scalyr Agent to windows.
        product_code = uuid.uuid3(_scalyr_guid_, "ProductID:%s:%s" % (build_info.variant, self.package_version))
        # The upgrade code identifies all families of versions that can be upgraded from one to the other.  So, this
        # should be a single number for all Scalyr produced ones.
        upgrade_code = uuid.uuid3(_scalyr_guid_, "UpgradeCode:%s" % build_info.variant)

        # For prereleases, we use weird version numbers like 4.0.4.pre5.1 .  That does not work for Windows which
        # requires X.X.X.X.  So, we convert if necessary.
        if len(self.package_version.split(".")) == 5:
            parts = self.package_version.split(".")
            del parts[3]
            version = ".".join(parts)

        wix_package_output = self._package_output_path / "wix"

        wixobj_file_path = wix_package_output / "ScalyrAgent.wixobj"

        wxs_file_path = _PARENT_DIR / "scalyr_agent.wxs"

        subprocess.check_call(
            f'candle -nologo -out {wixobj_file_path} -dVERSION="{self.package_version}" -dUPGRADECODE="{upgrade_code}" '
            f'-dPRODUCTCODE="{product_code}" {wxs_file_path}',
            shell=True
        )

        installer_name = f"ScalyrAgentInstaller-{self.package_version}.msi"
        installer_path =  self._package_output_path / installer_name

        subprocess.check_call(
            f"light -nologo -ext WixUtilExtension.dll -ext WixUIExtension -out {installer_path} {wixobj_file_path} -v",
            cwd=str(self._package_filesystem_root.absolute().parent),
            shell=True
        )


