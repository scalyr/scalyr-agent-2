import json
import pathlib as pl
import shutil
import subprocess
from typing import List

from agent_build_refactored.tools.toolset_image import build_toolset_image
from agent_build_refactored.tools.builder import Builder


from agent_build_refactored.tools.constants import SOURCE_ROOT, CpuArch
from agent_build_refactored.tools.docker.common import delete_container
from agent_build_refactored.tools.docker.buildx.build import DockerImageBuildOutput, buildx_build

_PARENT_DIR = pl.Path(__file__).parent


class RepoBuilder(Builder):
    """
    This runner class is responsible for creating deb/rpm repositories from provided packages.
    The result repo is used as a mock repository for testing.
    """

    def __init__(
        self,
        packages_dir: pl.Path
    ):

        super(RepoBuilder, self).__init__()
        self.packages_dir = packages_dir
        self.container_name = f"{self.__class__.NAME}_container"

    def _build_repo_files(
            self,
            repo_output_dir: pl.Path,
            sign_key_id: str
    ):
        pass

    @property
    def docker_exec_args(self) -> List[str]:
        return [
            "docker",
            "exec",
            "-i",
            self.container_name,
        ]

    def _build(self):

        toolset_image_name = build_toolset_image()

        delete_container(
            container_name=self.container_name,
        )

        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                f"--name={self.container_name}",
                f"-v={SOURCE_ROOT}:{self.to_in_docker_path(SOURCE_ROOT)}",
                toolset_image_name,
                "/bin/bash",
                "-c",
                "while true; do sleep 86400; done"
            ],
            check=True
        )

        try:
            get_key_id_cmd = "gpg2 --with-colons --fingerprint test | awk -F: '$1 == \"pub\" {{print $5;}}'"
            result = subprocess.run(
                [
                    *self.docker_exec_args,
                    "/bin/bash",
                    "-c",
                    get_key_id_cmd,
                ],
                check=True,
                capture_output=True
            )

            sign_key_id = result.stdout.decode().strip()

            repo_public_key_file = self.result_dir / "repo_public_key.gpg"

            in_docker_repo_public_key_file = self.to_in_docker_path(repo_public_key_file)
            subprocess.run(
                [
                    *self.docker_exec_args,
                    "gpg2",
                    "--output",
                    str(in_docker_repo_public_key_file),
                    "--armor",
                    "--export",
                    sign_key_id,
                ],
                check=True,
            )

            repo_output_dir = self.result_dir / "repo"
            repo_output_dir.mkdir(parents=True)

            self._build_repo_files(
                repo_output_dir=repo_output_dir,
                sign_key_id=sign_key_id,
            )

        finally:
            delete_container(
                self.container_name
            )


class AptRepoBuilder(RepoBuilder):
    NAME = "apt_repo_builder"

    def _build_repo_files(
        self,
        repo_output_dir: pl.Path,
        sign_key_id: str
    ):
        # Create deb repository using 'aptly'.
        aptly_root = self.work_dir / "aptly"
        in_docker_aptly_root = self.to_in_docker_path(aptly_root)

        aptly_config_path = self.work_dir / "aptly.conf"
        in_docker_aptly_config_path = self.to_in_docker_path(aptly_config_path)

        aptly_config = {"rootDir": str(in_docker_aptly_root)}

        aptly_config_path.write_text(json.dumps(aptly_config))
        subprocess.run(
            [
                *self.docker_exec_args,
                "aptly",
                "-config",
                str(in_docker_aptly_config_path),
                "repo",
                "create",
                "-distribution=scalyr",
                "scalyr",
            ],
            check=True,
        )

        for package_path in self.packages_dir.glob("*.deb"):
            in_docker_package_path = self.to_in_docker_path(package_path)
            subprocess.check_call(
                [
                    *self.docker_exec_args,
                    "aptly",
                    "-config",
                    str(in_docker_aptly_config_path),
                    "repo",
                    "add",
                    "scalyr",
                    str(in_docker_package_path),
                ]
            )

        subprocess.run(
            [
                *self.docker_exec_args,
                "aptly",
                "-config",
                str(in_docker_aptly_config_path),
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
            repo_output_dir: pl.Path,
            sign_key_id: str,
    ):
        # Create rpm repository using 'createrepo_c'.
        for package_path in self.packages_dir.glob("*.rpm"):
            shutil.copy(package_path, repo_output_dir)

        in_docker_repo_output_dir = self.to_in_docker_path(repo_output_dir)
        subprocess.run(
            [
                *self.docker_exec_args,
                "createrepo_c",
                str(in_docker_repo_output_dir)
            ]
        )

        # Sign repository's metadata
        metadata_path = repo_output_dir / "repodata/repomd.xml"
        in_docker_metadata_path = self.to_in_docker_path(metadata_path)
        subprocess.check_call(
            [
                *self.docker_exec_args,
                "gpg2",
                "--local-user",
                sign_key_id,
                "--output",
                f"{in_docker_metadata_path}.asc",
                "--detach-sign",
                "--armor",
                str(in_docker_metadata_path),
            ]
        )
