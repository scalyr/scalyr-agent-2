import json
import pathlib as pl
import shutil
import subprocess

from agent_build_refactored.build_dependencies.ubuntu_toolset import UBUNTU_TOOLSET_X86_64
from agent_build_refactored.tools.builder import Builder, BuilderArg


class RepoBuilder(Builder):
    """
    This runner class is responsible for creating deb/rpm repositories from provided packages.
    The result repo is used as a mock repository for testing.
    """

    PACKAGES_DIR_ARG = BuilderArg(
        name="packages_dir",
        cmd_line_name="--packages-dir",
        type=pl.Path,
    )

    def __init__(
        self,
    ):
        super(RepoBuilder, self).__init__(
            base=UBUNTU_TOOLSET_X86_64,
        )

    def _build_repo_files(
            self,
            packages_dir: pl.Path,
            repo_output_dir: pl.Path,
            sign_key_id: str
    ):
        pass

    def build(self):

        packages_dir = self.get_builder_arg_value(self.PACKAGES_DIR_ARG)

        sign_key_id = (
            subprocess.check_output(
                "gpg2 --with-colons --fingerprint test | awk -F: '$1 == \"pub\" {{print $5;}}'",
                shell=True,
            )
            .strip()
            .decode()
        )

        repo_public_key_file = self.output_dir / "repo_public_key.gpg"

        subprocess.check_call(
            [
                "gpg2",
                "--output",
                str(repo_public_key_file),
                "--armor",
                "--export",
                sign_key_id,
            ]
        )

        print("!!!!!!!!")
        for p in packages_dir.iterdir():
            print(str(p))

        self._build_repo_files(
            packages_dir=packages_dir,
            repo_output_dir=self.output_dir / "repo",
            sign_key_id=sign_key_id,
        )

    def build_repo(
        self,
        output_dir: pl.Path,
        packages_dir: pl.Path,
        verbose: bool = True,
    ):
        self.run_builder(
            output_dir=output_dir,
            **{
                self.PACKAGES_DIR_ARG.name: packages_dir,
                self.VERBOSE_ARG.name: verbose,
            },
        )


class AptRepoBuilder(RepoBuilder):
    NAME = "apt_repo_builder"

    def _build_repo_files(
        self,
        packages_dir: pl.Path,
        repo_output_dir: pl.Path,
        sign_key_id: str
    ):
        # Create deb repository using 'aptly'.
        aptly_root = self.work_dir / "aptly"
        aptly_config_path = self.work_dir / "aptly.conf"

        aptly_config = {"rootDir": str(aptly_root)}

        aptly_config_path.write_text(json.dumps(aptly_config))
        subprocess.run(
            [
                "aptly",
                "-config",
                str(aptly_config_path),
                "repo",
                "create",
                "-distribution=scalyr",
                "scalyr",
            ],
            check=True,
        )

        for package_path in packages_dir.glob("*.deb"):
            subprocess.check_call(
                [
                    "aptly",
                    "-config",
                    str(aptly_config_path),
                    "repo",
                    "add",
                    "scalyr",
                    str(package_path),
                ]
            )

        subprocess.run(
            [
                "aptly",
                "-config",
                str(aptly_config_path),
                "publish",
                "-architectures=amd64,arm64,all",
                "-distribution=scalyr",
                "repo",
                "scalyr",
            ],
            check=True,
        )
        shutil.copytree(aptly_root / "public", repo_output_dir, dirs_exist_ok=True)


class YumRepoBuilder(RepoBuilder):
    NAME = "yum_repo_builder"

    def _build_repo_files(
            self,
            packages_dir: pl.Path,
            repo_output_dir: pl.Path,
            sign_key_id: str,
    ):
        # Create rpm repository using 'createrepo_c'.
        for package_path in packages_dir.glob("*.rpm"):
            shutil.copy(package_path, repo_output_dir)
        subprocess.check_call(["createrepo_c", str(repo_output_dir)])

        # Sign repository's metadata
        metadata_path = repo_output_dir / "repodata/repomd.xml"
        subprocess.check_call(
            [
                "gpg2",
                "--local-user",
                sign_key_id,
                "--output",
                f"{metadata_path}.asc",
                "--detach-sign",
                "--armor",
                str(metadata_path),
            ]
        )
