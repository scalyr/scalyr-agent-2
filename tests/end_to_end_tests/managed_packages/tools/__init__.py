import pathlib as pl
import shutil
import tarfile
from typing import Union, Type

import requests

from agent_build_refactored.managed_packages.managed_packages_builders import (
    LinuxAIOPackagesBuilder,
    LinuxNonAIOPackageBuilder,
)
from tests.end_to_end_tests.managed_packages_tests.tools.repo_builder import AptRepoBuilder, YumRepoBuilder

_STABLE_REPO_URL = "https://scalyr-repo.s3.amazonaws.com/stable"


def get_packages_stable_version(version: str = None):

    if version:
        return version

    version_file_url = f"{_STABLE_REPO_URL}/latest/VERSION.txt"

    with requests.Session() as session:
        resp = session.get(url=version_file_url)
        resp.raise_for_status()

        version = resp.content.decode().strip()

    return version


def download_stable_packages(
    package_type: str,
    packages_version: str,
    output_dir: pl.Path,
):
    """
    Fixture directory with packages of the current stable version of the agent.
    Stable packages are needed to perform upgrade test and to verify that release stable
    packages can be upgraded by current packages.
    """

    if package_type == "deb":
        file_name = f"scalyr-agent-2_{packages_version}_all.deb"
        package_url = f"{_STABLE_REPO_URL}/apt/pool/main/s/scalyr-agent-2/{file_name}"
    elif package_type == "rpm":
        file_name = f"scalyr-agent-2-{packages_version}-1.noarch.rpm"
        package_url = f"{_STABLE_REPO_URL}/yum/binaries/noarch/{file_name}"
    else:
        raise Exception(f"Unknown package type: {package_type}")

    output_dir.mkdir(parents=True, exist_ok=True)
    agent_package_path = output_dir / file_name
    with requests.Session() as s:
        resp = s.get(url=package_url)
        resp.raise_for_status()

        agent_package_path.write_bytes(resp.content)


def create_packages_repo_root(
        packages_source_type: str,
        packages_source: str,
        package_builder: Union[Type[LinuxAIOPackagesBuilder], Type[LinuxNonAIOPackageBuilder]],
        package_type: str,
        stable_packages_version: str,
        output_dir: pl.Path
):

    output_dir.mkdir(parents=True, exist_ok=True)

    packages_repo_root = output_dir / "packages_repo_root"
    packages_repo_root.mkdir()

    if packages_source_type == "repo-tarball":
        # Extract repo directory from tarball.
        with tarfile.open(packages_source) as tf:
            tf.extractall(packages_repo_root)

    elif packages_source_type == "dir":
        if packages_source is None:
            # Build packages now.
            builder = package_builder(
                packages_types=[package_type]
            )
            builder.build()
            packages_dir = builder.result_dir / package_type
        else:
            packages_dir = pl.Path(packages_source)

        repo_packages_dir = output_dir / "repo_packages"
        repo_packages_dir.mkdir(parents=True)
        shutil.copytree(packages_dir, repo_packages_dir, dirs_exist_ok=True)

        download_stable_packages(
            package_type=package_type,
            packages_version=stable_packages_version,
            output_dir=repo_packages_dir,
        )

        # Build mock repo from packages.
        if package_type == "deb":
            repo_builder = AptRepoBuilder(
                packages_dir=repo_packages_dir
            )
        elif package_type == "rpm":
            repo_builder = YumRepoBuilder(
                packages_dir=repo_packages_dir
            )
        else:
            raise Exception(f"Unknown package type: {package_type}")

        repo_builder.build(
            output_dir=packages_repo_root,
        )
        shutil.copytree(repo_builder.result_dir, packages_repo_root, dirs_exist_ok=True)

    return packages_repo_root


def is_builder_creates_aio_package(package_builder_name: str):
    """Tells whether builder given name produces AIO package or not"""
    return "non-aio" not in package_builder_name