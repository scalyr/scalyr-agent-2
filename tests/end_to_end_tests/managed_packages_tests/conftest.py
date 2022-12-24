import pathlib as pl
import shutil
import subprocess
import argparse
import http.server
import socketserver
import tarfile
import threading
import time
import textwrap

import pytest


from agent_build_refactored.tools.constants import Architecture
from agent_build_refactored.tools.runner import Runner, RunnerMappedPath
from agent_build_refactored.managed_packages.managed_packages_builders import (
    ALL_MANAGED_PACKAGE_BUILDERS,
    PREPARE_TOOLSET_GLIBC_X86_64,
    PREPARE_TOOLSET_GLIBC_ARM64,
    PYTHON_PACKAGE_NAME,
    AGENT_LIBS_PACKAGE_NAME,
    AGENT_PACKAGE_NAME,
)
from agent_build_refactored.managed_packages.convenience_install_script.builder import (
    ConvenienceScriptBuilder,
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


class RepoBuilder(Runner):
    """
    This runner class is responsible for creating deb/rpm repositories from provided packages.
    The result repo is used as a mock repository for testing.
    """

    BASE_ENVIRONMENT = PREPARE_TOOLSET_GLIBC_X86_64

    def build(
        self,
        package_type: str,
        packages_dir_path: pl.Path,
    ):

        self.run_required()

        if self.runs_in_docker:
            self.run_in_docker(
                command_args=[
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
            # Create deb repository using 'reprepro'.
            conf_path = repo_path / "conf"
            conf_path.mkdir(parents=True)

            conf_distributions_path = conf_path / "distributions"
            conf_distributions_path.write_text(
                textwrap.dedent(
                    f"""
                Origin: test_repo
                Label: test_repo
                Codename: scalyr
                Architectures: amd64 arm64 source
                Components: main
                Description: example repo
                SignWith: {sign_key_id}
                """
                )
            )
            subprocess.run('aptly repo create -distribution="scalyr" scalyr', shell=True)

            for package_path in packages_dir_path.glob("*.deb"):
                subprocess.run(f"aptly repo add scalyr {package_path}", shell=True)
                # subprocess.check_call(
                #     [
                #         "reprepro",
                #         "-b",
                #         str(repo_path),
                #         "includedeb",
                #         "scalyr",
                #         str(package_path),
                #     ]
                # )


            subprocess.run(f'aptly publish repo -distribution="scalyr" -gpg-key="{sign_key_id}" scalyr', shell=True)

            shutil.copytree(
                pl.Path.home() / ".aptly/public",
                repo_path,
                dirs_exist_ok=True
            )

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

        parser.add_argument("--package-type", dest="package_type", required=True)
        parser.add_argument(
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
        builder = cls()
        builder.build(
            package_type=args.package_type, packages_dir_path=pl.Path(args.packages_dir)
        )


@pytest.fixture(scope="session")
def server_root(request, tmp_path_factory, package_builder):
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

            packages_dir = tmp_path_factory.mktemp("packages")
            dependencies_builder = package_builder()
            dependencies_builder.build()
            for package_path in dependencies_builder.output_path.glob(f"*.{package_builder.PACKAGE_TYPE}"):
                shutil.copy(package_path, packages_dir)

            # Build agent package.
            agent_builder_name = f"{package_builder.PACKAGE_TYPE}-agent"
            agent_builder_cls = ALL_MANAGED_PACKAGE_BUILDERS[agent_builder_name]
            agent_builder = agent_builder_cls()
            agent_builder.build()
            for package_path in agent_builder.output_path.glob(f"*.{package_builder.PACKAGE_TYPE}"):
                shutil.copy(package_path, packages_dir)
        else:
            packages_dir = pl.Path(request.config.option.packages_source)

        # Build mock repo from packages.
        repo_builder = RepoBuilder()
        repo_builder.build(
            package_type=package_builder.PACKAGE_TYPE, packages_dir_path=packages_dir
        )
        shutil.copytree(repo_builder.output_path, server_root, dirs_exist_ok=True)

    return server_root


@pytest.fixture(scope="session")
def repo_root(server_root):
    """Root directory of the mock repository."""
    return server_root / "repo"


@pytest.fixture(scope="session")
def convenience_script_path(server_root):
    """
    Path to the convenience install script.
    We also start web server that serves mock repo with packages that have to be installed by the
    convenience script.
    """

    # Create web server which serves repo and public key file.
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(server_root), **kwargs)

    with socketserver.TCPServer(("", 0), Handler) as httpd:
        repo_server_thread = threading.Thread(target=httpd.serve_forever)
        repo_server_thread.start()

        time.sleep(1)

        server_url = f"http://localhost:{httpd.socket.getsockname()[1]}"
        repo_url = f"{server_url}/repo"
        public_key_url = f"{server_url}/repo_public_key.gpg"

        # Build convenience script with current repo and public key urls.
        convenience_script_builder = ConvenienceScriptBuilder()
        convenience_script_builder.build(
            repo_url=repo_url,
            public_key_url=public_key_url,
        )

        yield convenience_script_builder.output_path / "install-agent.sh"
        httpd.shutdown()
        repo_server_thread.join()


def _get_package_path_from_repo(
    package_name: str, package_type: str, repo_root: pl.Path
):
    """Helper function that finds package inside repo root."""
    if package_type == "deb":
        package_dir_path = repo_root / f"pool/main/s/{package_name}"
    elif package_type == "rpm":
        package_dir_path = repo_root
    else:
        raise Exception(f"Unknown package type: '{package_type}'")

    found = list(package_dir_path.rglob(f"{package_name}*.{package_type}"))
    assert len(found) == 1
    return found[0]


@pytest.fixture(scope="session")
def python_package_path(repo_root, package_builder):
    if repo_root is None:
        return None

    return _get_package_path_from_repo(
        package_name=PYTHON_PACKAGE_NAME,
        package_type=package_builder.PACKAGE_TYPE,
        repo_root=repo_root,
    )


@pytest.fixture(scope="session")
def agent_libs_package_path(repo_root, package_builder):
    if repo_root is None:
        return None

    return _get_package_path_from_repo(
        package_name=AGENT_LIBS_PACKAGE_NAME,
        package_type=package_builder.PACKAGE_TYPE,
        repo_root=repo_root,
    )


@pytest.fixture(scope="session")
def agent_package_path(repo_root, package_builder):
    if repo_root is None:
        return None

    return _get_package_path_from_repo(
        package_name=AGENT_PACKAGE_NAME,
        package_type=package_builder.PACKAGE_TYPE,
        repo_root=repo_root,
    )
