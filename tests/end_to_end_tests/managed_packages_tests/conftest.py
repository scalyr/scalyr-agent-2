import json
import pathlib as pl
import shutil
import subprocess
import argparse
import http.server
import socketserver
import tarfile
import threading
import time
from typing import Optional

import pytest
import requests

from agent_build_refactored.tools.constants import (
    Architecture,
    AGENT_VERSION,
    SOURCE_ROOT,
)
from agent_build_refactored.tools.runner import Runner, RunnerMappedPath, EnvironmentRunnerStep
from agent_build_refactored.managed_packages.managed_packages_builders import (
    ALL_MANAGED_PACKAGE_BUILDERS,
    PREPARE_TOOLSET_STEPS,
    PYTHON_PACKAGE_NAME,
    AGENT_LIBS_PACKAGE_NAME,
    AGENT_AIO_PACKAGE_NAME,
    AGENT_NON_AIO_AIO_PACKAGE_NAME,
)
from tests.end_to_end_tests.run_in_remote_machine import DISTROS


def pytest_addoption(parser):
    parser.addoption("--builder-name", dest="builder_name", required=True)

    parser.addoption(
        "--packages-source",
        dest="packages_source",
        required=False,
        help="Depending on the '--packages-source-type' option, directory or repo tarball with packages to test. "
        "If not specified, packages will be built inplace.",
    )

    parser.addoption(
        "--packages-source-type",
        dest="packages_source_type",
        choices=["dir", "repo-tarball"],
        default="dir",
        required=False,
    )

    parser.addoption(
        "--remote-machine-type",
        required=True,
        choices=["ec2", "docker"],
        help="Type of the remote machine for the test. For 'ec2' - run in AWS ec2 instance,"
        "'docker' - run in docker container, 'local', run locally.",
    )

    parser.addoption(
        "--runs-locally",
        action="store_true",
        help="If set, then tests run inside local machine, not in remote one.",
    )

    parser.addoption(
        "--distro-name",
        dest="distro_name",
        required=True,
        choices=DISTROS.keys(),
        help="Distribution to test.",
    )


def pytest_collection_modifyitems(config, items):
    """
    This pytest hook modifies test cases according to input config options.
    """
    names = [item.name for item in items]
    index = names.index("test_remotely")
    test_remotely = items[index]

    # If tests have to be run in remote machine then we remove all test cases
    # and leave only the 'test_remotely' case, which has to run all tests remotely.
    if not config.option.runs_locally:
        del items[:]
        items.append(test_remotely)
    # Or remove the 'test_remotely' case if tests have to be run locally.
    else:
        items.pop(index)

    # make sure that the 'test_packages' test case runs first to test packages
    # on the cleanest machine possible.
    if "test_packages" in items:
        index = names.index("test_packages")
        test = items.pop(index)
        items.insert(0, test)


@pytest.fixture(scope="session")
def package_builder_name(request):
    """Name of the builder that build tested packages."""
    return request.config.option.builder_name


@pytest.fixture(scope="session")
def package_builder(package_builder_name):
    """Builder class that builds tested packges."""
    return ALL_MANAGED_PACKAGE_BUILDERS[package_builder_name]


@pytest.fixture(scope="session")
def remote_machine_type(request):
    """
    Fixture with time of the remote machine where tests can run. For now that's ec2 or docker.
    """
    return request.config.option.remote_machine_type


@pytest.fixture(scope="session")
def distro_name(request):
    return request.config.option.distro_name


@pytest.fixture(scope="session")
def target_distro(distro_name):
    return DISTROS[distro_name]


@pytest.fixture(scope="session")
def use_aio_package(package_builder_name):
    """Fixture flag that tells that a tested package is AIO"""
    return "non-aio" not in package_builder_name


@pytest.fixture(scope="session")
def agent_package_name(use_aio_package):
    if use_aio_package:
        return AGENT_AIO_PACKAGE_NAME
    else:
        return AGENT_NON_AIO_AIO_PACKAGE_NAME


class RepoBuilder(Runner):
    """
    This runner class is responsible for creating deb/rpm repositories from provided packages.
    The result repo is used as a mock repository for testing.
    """

    @classmethod
    def get_base_environment(cls) -> Optional[EnvironmentRunnerStep]:
        return  PREPARE_TOOLSET_STEPS[Architecture.X86_64]

    def build(
        self,
        package_type: str,
        packages_dir_path: pl.Path,
    ):

        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker(
                command_args=[
                    "build",
                    "--package-type",
                    package_type,
                    "--packages-dir",
                    RunnerMappedPath(packages_dir_path),
                ]
            )
            return

        repo_path = self.output_path / "repo"
        repo_path.mkdir()
        repo_public_key_file = self.output_path / "repo_public_key.gpg"

        sign_key_id = (
            subprocess.check_output(
                "gpg2 --with-colons --fingerprint test | awk -F: '$1 == \"pub\" {{print $5;}}'",
                shell=True,
            )
            .strip()
            .decode()
        )

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

        if package_type == "deb":
            # Create deb repository using 'aptly'.
            workdir = self.output_path / "aptly"
            workdir.mkdir(parents=True)
            aptly_root = workdir / "aptly"
            aptly_config_path = workdir / "aptly.conf"

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

            for package_path in packages_dir_path.glob("*.deb"):
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
            shutil.copytree(aptly_root / "public", repo_path, dirs_exist_ok=True)

        elif package_type == "rpm":
            # Create rpm repository using 'createrepo_c'.
            for package_path in packages_dir_path.glob("*.rpm"):
                shutil.copy(package_path, repo_path)
            subprocess.check_call(["createrepo_c", str(repo_path)])

            # Sign repository's metadata
            metadata_path = repo_path / "repodata/repomd.xml"
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

    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):
        super(RepoBuilder, cls).add_command_line_arguments(parser)

        subparser = parser.add_subparsers(dest="command")

        build_parser = subparser.add_parser("build")

        build_parser.add_argument("--package-type", dest="package_type", required=True)
        build_parser.add_argument(
            "--packages-dir",
            dest="packages_dir",
            required=True,
        )

    @classmethod
    def handle_command_line_arguments(
        cls,
        args,
    ):
        super(RepoBuilder, cls).handle_command_line_arguments(args)

        if args.command == "build":
            builder = cls()
            builder.build(
                package_type=args.package_type, packages_dir_path=pl.Path(args.packages_dir)
            )


@pytest.fixture(scope="session")
def stable_agent_package_version():
    # TODO: For now we just hardcode the particular version, when first release is done
    # it has to be changed to version in the repository.
    return "2.1.40"


@pytest.fixture(scope="session")
def stable_version_packages(
    package_builder, tmp_path_factory, stable_agent_package_version
):
    """
    Fixture directory with packages of the current stable version of the agent.
    Stable packages are needed to perform upgrade test and to verify that release stable
    packages can be upgraded by current packages.
    """

    stable_repo_url = "https://scalyr-repo.s3.amazonaws.com/stable"
    if package_builder.PACKAGE_TYPE == "deb":
        file_name = f"scalyr-agent-2_{stable_agent_package_version}_all.deb"
        package_url = f"{stable_repo_url}/apt/pool/main/s/scalyr-agent-2/{file_name}"
    elif package_builder.PACKAGE_TYPE == "rpm":
        file_name = f"scalyr-agent-2-{stable_agent_package_version}-1.noarch.rpm"
        package_url = f"{stable_repo_url}/yum/binaries/noarch/{file_name}"
    else:
        raise Exception(f"Unknown package type: {package_builder.PACKAGE_TYPE}")

    packages_path = tmp_path_factory.mktemp("packages")
    agent_package_path = packages_path / file_name
    with requests.Session() as s:
        resp = s.get(url=package_url)
        resp.raise_for_status()

        agent_package_path.write_bytes(resp.content)

    return packages_path


@pytest.fixture(scope="session")
def server_root(request, tmp_path_factory, package_builder, stable_version_packages):
    """
    Root directory which is served by the mock web server.
    The mock repo is located in ./repo folder, the public key is located in ./repo_public_key.gpg
    :return:
    """
    package_source_type = request.config.option.packages_source_type

    server_root = tmp_path_factory.mktemp("server_root")
    if package_source_type == "repo-tarball":
        # Extract repo directory from tarball.
        with tarfile.open(request.config.option.packages_source) as tf:
            tf.extractall(server_root)

    elif package_source_type == "dir":
        if request.config.option.packages_source is None:
            # Build packages now.
            builder = package_builder()
            builder.build_agent_package()
            builder_output = builder.packages_output_path
        else:
            builder_output = pl.Path(request.config.option.packages_source)

        packages_dir = builder_output / package_builder.PACKAGE_TYPE
        repo_packages = tmp_path_factory.mktemp("repo_packages")
        shutil.copytree(packages_dir, repo_packages, dirs_exist_ok=True)
        shutil.copytree(stable_version_packages, repo_packages, dirs_exist_ok=True)

        # Build mock repo from packages.
        repo_builder = RepoBuilder()
        repo_builder.build(
            package_type=package_builder.PACKAGE_TYPE, packages_dir_path=repo_packages
        )
        shutil.copytree(repo_builder.output_path, server_root, dirs_exist_ok=True)

    return server_root


@pytest.fixture(scope="session")
def repo_root(server_root):
    """Root directory of the mock repository."""
    return server_root / "repo"


@pytest.fixture(scope="session")
def server_url(server_root):
    """
    This fixture prepares http server with package repository and other needed files.
    """

    # Create web server which serves repo and public key file.
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(server_root), **kwargs)

    with socketserver.TCPServer(("", 0), Handler) as httpd:
        repo_server_thread = threading.Thread(target=httpd.serve_forever)
        repo_server_thread.start()

        time.sleep(1)

        yield f"http://localhost:{httpd.socket.getsockname()[1]}"

        httpd.shutdown()
        repo_server_thread.join()


@pytest.fixture(scope="session")
def repo_url(server_url):
    """Url to package repository"""

    return f"{server_url}/repo"


@pytest.fixture(scope="session")
def repo_public_key_url(server_url):
    return f"{server_url}/repo_public_key.gpg"


@pytest.fixture(scope="session")
def convenience_script_path(
    server_url, repo_url, repo_public_key_url, tmp_path_factory
):
    """
    Path to the convenience install script.
    We also start web server that serves mock repo with packages that have to be installed by the
    convenience script.
    """

    # Build convenience script with current repo and public key urls.
    render_install_script_path = (
        SOURCE_ROOT
        / "agent_build_refactored/managed_packages/convenience_install_script/render_install_agent_script.sh"
    )

    install_script_path = (
        tmp_path_factory.mktemp("install_script") / "install-scalyr-agent-2.sh"
    )

    subprocess.run(
        [
            "bash",
            str(render_install_script_path),
            repo_url,
            repo_url,
            repo_public_key_url,
            str(install_script_path),
        ],
        check=True,
    )

    yield install_script_path


def _get_package_path_from_repo(
    package_filename_glob: str, package_type: str, repo_root: pl.Path
):
    """Helper function that finds package inside repo root."""
    if package_type == "deb":
        packages_dir = repo_root / "pool/main/s"
    elif package_type == "rpm":
        packages_dir = repo_root
    else:
        raise Exception(f"Unknown package type: '{package_type}'")

    found = list(packages_dir.rglob(package_filename_glob))
    assert len(found) == 1
    return found[0]


@pytest.fixture(scope="session")
def python_package_path(repo_root, package_builder):
    if repo_root is None:
        return None

    return _get_package_path_from_repo(
        package_filename_glob=f"{PYTHON_PACKAGE_NAME}*.{package_builder.PACKAGE_TYPE}",
        package_type=package_builder.PACKAGE_TYPE,
        repo_root=repo_root,
    )


@pytest.fixture(scope="session")
def agent_libs_package_path(repo_root, package_builder):
    if repo_root is None:
        return None

    return _get_package_path_from_repo(
        package_filename_glob=f"{AGENT_LIBS_PACKAGE_NAME}*.{package_builder.PACKAGE_TYPE}",
        package_type=package_builder.PACKAGE_TYPE,
        repo_root=repo_root,
    )


@pytest.fixture(scope="session")
def agent_package_path(repo_root, package_builder, agent_package_name, use_aio_package):
    if repo_root is None:
        return None

    if use_aio_package:
        package_arch = (
            package_builder.DEPENDENCY_PACKAGES_ARCHITECTURE.get_package_arch(
                package_type=package_builder.PACKAGE_TYPE
            )
        )
    else:
        package_arch = Architecture.UNKNOWN.get_package_arch(
            package_type=package_builder.PACKAGE_TYPE
        )

    if package_builder.PACKAGE_TYPE == "deb":
        package_filename_glob = f"{agent_package_name}_{AGENT_VERSION}_{package_arch}.{package_builder.PACKAGE_TYPE}"
    elif package_builder.PACKAGE_TYPE == "rpm":
        package_filename_glob = f"{agent_package_name}-{AGENT_VERSION}-1.{package_arch}.{package_builder.PACKAGE_TYPE}"
    else:
        raise Exception(f"Unknown package type: {package_builder.PACKAGE_TYPE}")

    return _get_package_path_from_repo(
        package_filename_glob=package_filename_glob,
        package_type=package_builder.PACKAGE_TYPE,
        repo_root=repo_root,
    )
