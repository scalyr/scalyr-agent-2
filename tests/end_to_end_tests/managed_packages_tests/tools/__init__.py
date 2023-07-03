import pathlib as pl
import shutil
import tarfile

import requests

from agent_build_refactored.tools.constants import SOURCE_ROOT
from tests.end_to_end_tests.managed_packages_tests.tools.repo_builder import AptRepoBuilder, YumRepoBuilder
from tests.end_to_end_tests.run_in_remote_machine import DISTROS

_STABLE_REPO_URL = "https://scalyr-repo.s3.amazonaws.com/stable"

WORK_DIR = SOURCE_ROOT / "agent_build_output/tests_work_dirs/packages_tests"


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
    package_builder,
    packages_version: str,
    output_dir: pl.Path,
):
    """
    Fixture directory with packages of the current stable version of the agent.
    Stable packages are needed to perform upgrade test and to verify that release stable
    packages can be upgraded by current packages.
    """

    if package_builder.PACKAGE_TYPE == "deb":
        file_name = f"scalyr-agent-2_{packages_version}_all.deb"
        package_url = f"{_STABLE_REPO_URL}/apt/pool/main/s/scalyr-agent-2/{file_name}"
    elif package_builder.PACKAGE_TYPE == "rpm":
        file_name = f"scalyr-agent-2-{packages_version}-1.noarch.rpm"
        package_url = f"{_STABLE_REPO_URL}/yum/binaries/noarch/{file_name}"
    else:
        raise Exception(f"Unknown package type: {package_builder.PACKAGE_TYPE}")

    output_dir.mkdir(parents=True, exist_ok=True)
    agent_package_path = output_dir / file_name
    with requests.Session() as s:
        resp = s.get(url=package_url)
        resp.raise_for_status()

        agent_package_path.write_bytes(resp.content)


def create_server_root(
        packages_source_type: str,
        packages_source: str,
        package_builder,
        stable_packages_version: str,
):

    work_dir = WORK_DIR / "build_server_root"

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    server_root = work_dir / "server_root"
    server_root.mkdir()

    if packages_source_type == "repo-tarball":
        # Extract repo directory from tarball.
        with tarfile.open(packages_source) as tf:
            tf.extractall(server_root)

    elif packages_source_type == "dir":
        if packages_source is None:
            # Build packages now.
            builder = package_builder()
            builder.run_package_builder()
            builder_output = builder.output_dir
        else:
            builder_output = pl.Path(packages_source)

        packages_dir = builder_output / package_builder.PACKAGE_TYPE
        repo_packages = work_dir / "repo_packages"
        repo_packages.mkdir(parents=True)
        shutil.copytree(packages_dir, repo_packages, dirs_exist_ok=True)

        download_stable_packages(
            package_builder=package_builder,
            packages_version=stable_packages_version,
            output_dir=repo_packages,
        )
        #shutil.copytree(stable_version_packages, repo_packages, dirs_exist_ok=True)

        # Build mock repo from packages.
        if package_builder.PACKAGE_TYPE == "deb":
            repo_builder = AptRepoBuilder()
        elif package_builder.PACKAGE_TYPE == "rpm":
            repo_builder = YumRepoBuilder()
        else:
            raise Exception(f"Unknown package type: {package_builder.PACKAGE_TYPE}")

        repo_builder.build_repo(
            output_dir=server_root,
            packages_dir=packages_dir,
        )
        shutil.copytree(repo_builder.output_dir, server_root, dirs_exist_ok=True)

    return server_root


def is_builder_creates_aio_package(package_builder_name: str):
    """Tells whether builder given name produces AIO package or not"""
    return "non-aio" not in package_builder_name