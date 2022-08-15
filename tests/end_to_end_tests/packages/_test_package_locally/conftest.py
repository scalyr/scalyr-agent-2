import shutil
import pathlib as pl
import subprocess
from socketserver import TCPServer
from http.server import SimpleHTTPRequestHandler
import functools
import threading
import urllib.request
import time
import logging
import os
from typing import List

from tests.end_to_end_tests.tools import AgentPaths

log = logging.getLogger(__name__)

import pytest


def pytest_addoption(parser):

    parser.addoption(
        "--package-type",
        dest="package_type",
        required=True,
        choices=["rpm"],
        help="Type of the package to test.",
    )

    parser.addoption(
        "--packages-archive-path",
        dest="packages_archive_path",
        required=True,
        help="Path to the archive with packages to test. It also may contain package of the previous "
        "version to test upgrade logics of the package. For the packages like deb or rpm, they are"
        "packed into archive in form of the ready apt or yum repository. ",
    )

    parser.addoption(
        "--previous-package-version",
        dest="previous_package_version",
        required=True,
        help="Version of the prior package to perform an upgrade test from this to a new version.",
    )

    parser.addoption(
        "--package-version",
        dest="package_version",
        required=True,
        help="Version of the package to test.",
    )


@pytest.fixture(scope="session")
def package_type(request):
    return request.param


@pytest.fixture(scope="session")
def distro_name(request):
    return request.param


@pytest.fixture(scope="session")
def previous_package_version(request):
    return request.config.option.previous_package_version


@pytest.fixture(scope="session")
def package_version(request):
    return request.config.option.package_version


@pytest.fixture(scope="session")
def repo_host():
    return "127.0.0.1"


@pytest.fixture(scope="session")
def repo_port():
    return 80


@pytest.fixture(scope="session")
def packages_path(tmp_path_factory, request):
    path = tmp_path_factory.mktemp("packages")
    shutil.unpack_archive(
        filename=request.config.option.packages_archive_path, extract_dir=path
    )
    return path


@pytest.fixture(scope="session")
def rpm_repo(repo_host, repo_port, packages_path):

    fixtures_path = pl.Path(__file__).parent / "fixtures"
    yum_repo_config_path = fixtures_path / "scalyr_test_yum.repo"
    yum_repo_config = yum_repo_config_path.read_text().format(
        repo_host=repo_host, repo_port=repo_port
    )

    # Add local repo to yum.
    repo_config_path = pl.Path("/etc/yum.repos.d/") / "scalyr_test_repo.repo"
    repo_config_path.write_text(yum_repo_config)

    with TCPServer(
        ("", repo_port),
        functools.partial(SimpleHTTPRequestHandler, directory=str(packages_path)),
    ) as httpd:
        thread = threading.Thread(target=httpd.serve_forever)
        thread.start()

        logging.info("Wait for successful response from repo server.")
        while True:
            response = urllib.request.urlopen(f"http://{repo_host}:{repo_port}/")

            if response.getcode() == 200:
                break

            time.sleep(1)

        logging.info("Repo server is ready.")
        yield
        httpd.shutdown()
        thread.join()


def _call_yum(args):
    ld_library_path = os.environ["LD_LIBRARY_PATH"]
    subprocess.check_call(
        ["yum", *args],
        env={"LD_LIBRARY_PATH": f"/lib64:{ld_library_path}"},
    )


@pytest.fixture(scope="session")
def package_path(package_type, package_version, packages_path) -> pl.Path:
    """
    path of the package to test. if this is from the package that is supposed to be installed
        from repo (Rpm, Deb), then the target package will be located inside that local repository.
    """

    if package_type == "rpm":
        glob = f"scalyr-agent-2-{package_version}-1.*.rpm"
        # raise RuntimeError(f"{list(packages_path.iterdir())}        {glob}")
        return list(packages_path.glob(glob))[0]


@pytest.fixture(scope="session")
def install_rpm_package_function(rpm_repo):
    def install(version: str = None):
        package_name = "scalyr-agent-2"
        if version:
            package_name = f"{package_name}-{version}"
        _call_yum(["install", "-y", package_name])

    return install


@pytest.fixture(scope="session")
def downgrade_rpm_package_function(rpm_repo):
    def downgrade(version: str = None):
        package_name = "scalyr-agent-2"
        if version:
            package_name = f"{package_name}-{version}"
        _call_yum(["downgrade", "-y", package_name])

    return downgrade


@pytest.fixture(scope="session")
def uninstall_rpm_package_function(rpm_repo):
    def uninstall(version: str):
        package_name = "scalyr-agent-2"
        if version:
            package_name = f"{package_name}-{version}"
        _call_yum(["remove", "-y", package_name])

    return uninstall


@pytest.fixture(scope="session")
def install_package(package_type, request):
    if package_type == "rpm":
        return request.getfixturevalue("install_rpm_package_function")


@pytest.fixture(scope="session")
def upgrade_package(package_type, request):
    if package_type == "rpm":
        # upgrade command for yum is the same is install.
        return request.getfixturevalue("install_rpm_package_function")


@pytest.fixture(scope="session")
def downgrade_package(package_type, request):
    if package_type == "rpm":
        return request.getfixturevalue("downgrade_rpm_package_function")


@pytest.fixture(scope="session")
def uninstall_package(package_type, request):
    if package_type == "rpm":
        return request.getfixturevalue("uninstall_rpm_package_function")


@pytest.fixture(scope="session")
def agent_test_configs_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("test_configs")

    shutil.copytree(
        pl.Path(__file__).parent.parent.parent.parent / "ami/configs/.",
        path,
        dirs_exist_ok=True,
    )
    return path


@pytest.fixture(scope="session")
def bad_cert_path(tmp_path_factory):
    cert_source_path = (
        pl.Path(__file__).parent.parent.parent.parent / "ami/files/ca_certs.crt"
    )
    dir_path = tmp_path_factory.mktemp("certs")
    cert_path = dir_path / cert_source_path.name

    shutil.copy2(
        cert_source_path,
        cert_path,
    )

    return cert_path


@pytest.fixture(scope="session")
def agent_paths(package_type):
    if package_type in ["rpm"]:
        return AgentPaths(
            configs_dir=pl.Path("/etc/scalyr-agent-2"),
            logs_dir=pl.Path("/var/log/scalyr-agent-2"),
            install_root=pl.Path("/usr/share/scalyr-agent-2"),
        )

    raise ValueError(f"Unknown package type {package_type}")


# @pytest.fixture(scope="session")
# def install_additional_packages(package_type):
#
#     def install(package_names: List[str]):
#         if package_type == "rpm":
#             _call_yum([
#                 "install", "-y", " ".join(package_names)
#             ])
#
#     return install
