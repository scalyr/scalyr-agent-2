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

    @property
    def _install_type_name(self):
        return "package"

    @property
    def _package_type_name(self) -> str:
        return "msi"

    @property
    def package_version(self) -> str:
        # For prereleases, we use weird version numbers like 4.0.4.pre5.1 .  That does not work for Windows which
        # requires X.X.X.X.  So, we convert if necessary.
        base_version = super(WindowsMsiPackageBuilder, self).package_version
        if len(base_version.split(".")) == 5:
            parts = base_version.split(".")
            del parts[3]
            version = ".".join(parts)
            return version

        return base_version



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
            output_path: Union[str, pl.Path]
    ):
        scalyr_dir = self._package_filesystem_root / "Scalyr"

        # Build common package files.
        self._build_base_files(
            output_path=scalyr_dir
        )

        # Add root certificates.
        certs_path = scalyr_dir / "certs"
        certs_path.mkdir()
        builder.add_certs(
            certs_path,
            intermediate_certs=False,
            copy_other_certs=False
        )

        # Build frozen binaries and copy them into bin folder.
        self._build_frozen_binary()
        bin_path = scalyr_dir / "bin"
        shutil.copytree(self._frozen_binary_output, bin_path)

        shutil.copy(
            _PARENT_DIR / "files/ScalyrShell.cmd",
            bin_path
        )

        # Copy config template.
        config_templates_dir_path = pl.Path(scalyr_dir / "config" / "templates")
        config_templates_dir_path.mkdir(parents=True)
        config_template_path = config_templates_dir_path / "agent_config.tmpl"
        shutil.copy2(common.SOURCE_ROOT / "config" / "agent.json", config_template_path)
        config_template_path.write_text(config_template_path.read_text().replace("\n", "\r\n"))

        if self._variant is None:
            variant = "main"
        else:
            variant = self._variant

        # Generate a unique identifier used to identify this version of the Scalyr Agent to windows.
        product_code = uuid.uuid3(_scalyr_guid_, "ProductID:%s:%s" % (variant, self.package_version))
        # The upgrade code identifies all families of versions that can be upgraded from one to the other.  So, this
        # should be a single number for all Scalyr produced ones.
        upgrade_code = uuid.uuid3(_scalyr_guid_, "UpgradeCode:%s" % variant)

        wix_package_output = self._build_output_path / "wix"

        wixobj_file_path = wix_package_output / "ScalyrAgent.wixobj"

        wxs_file_path = _PARENT_DIR / "scalyr_agent.wxs"

        # Compile WIX .wxs file.
        subprocess.check_call(
            f'candle -nologo -out {wixobj_file_path} -dVERSION="{self.package_version}" -dUPGRADECODE="{upgrade_code}" '
            f'-dPRODUCTCODE="{product_code}" {wxs_file_path}',
            shell=True
        )

        installer_name = f"ScalyrAgentInstaller-{self.package_version}.msi"
        installer_path = self._build_output_path / installer_name

        # Link compiled WIX files into msi installer.
        subprocess.check_call(
            f"light -nologo -ext WixUtilExtension.dll -ext WixUIExtension -out {installer_path} {wixobj_file_path} -v",
            cwd=str(scalyr_dir.absolute().parent),
            shell=True
        )


