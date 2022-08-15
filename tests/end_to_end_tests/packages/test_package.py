import subprocess
import os
import shutil
import pathlib as pl
from typing import Union

import pytest

from agent_build.tools.environment_deployments.deployments import CacheableBuilder, ShellScriptDeploymentStep
from agent_build.tools.constants import SOURCE_ROOT, Architecture


class FrozenBinaryTestRunnerBuilder(CacheableBuilder):
    DEPLOYMENT_STEP = PYTHON_GLIBC_WITH_AGENT_DEPS

    def __init__(self, a=None):
        super(FrozenBinaryTestRunnerBuilder, self).__init__()

    def _build(self):
        full_script_path = SOURCE_ROOT / "tests/end_to_end_tests/packages/_test_package_locally/frozen_pytest_runner.py"

        # Since we bundle pytest as frozen binary, it still has to be provided with source code of needed tests,
        # so we also bundle `tests` module to frozen binary.

        subprocess.check_call(
            [
                "python3",
                "-m",
                "PyInstaller",
                "--onefile",
                "--distpath", self.output_path / "dist",
                "--workpath", self.output_path / "build",
                "--hidden-import", "six",
                "--hidden-import", "tests.end_to_end_tests",
                "--hidden-import", "py",
                "--hidden-import", "py._vendored_packages",
                "--hidden-import", "py._vendored_packages.iniconfig",
                "--add-data",
                f"{SOURCE_ROOT / 'tests/end_to_end_tests'}{os.pathsep}./tests/end_to_end_tests",
                # Add test configs
                "--add-data",
                f"{SOURCE_ROOT / 'tests/ami/configs'}{os.pathsep}./tests/ami/configs",
                # Add other test related files.
                "--add-data",
                f"{SOURCE_ROOT / 'tests/ami/files'}{os.pathsep}./tests/ami/files",
                "--add-data",
                f"{SOURCE_ROOT / 'agent_build'}{os.pathsep}./agent_build",
                full_script_path,
            ],
            cwd=SOURCE_ROOT
        )


@pytest.fixture(scope="session")
def frozen_pytest_runner_path():
    builder = FrozenBinaryTestRunnerBuilder()

    builder.build()

    return builder.output_path / "dist/frozen_pytest_runner"


@pytest.fixture(scope="session")
def previous_package_version():
    return "2.0.1"


@pytest.fixture(scope="session")
def prior_package(tmpdir_factory, previous_package_version):
    return pl.Path("/Users/arthur/work/agents/scalyr-agent-2/scalyr-agent-2-2.0.1-1.x86_64.rpm")
    builder = RpmPackageBuilder(
        version="2.0.1"
    )
    builder.build()

    tmp_dir = tmpdir_factory.mktemp("build_output-")
    result_path = pl.Path(tmp_dir) / builder.result_file_path.name
    shutil.copy2(
        builder.result_file_path, result_path
    )
    return result_path


@pytest.fixture(scope="session")
def package_version():
    return pl.Path(SOURCE_ROOT, "VERSION").read_text().strip()


@pytest.fixture(scope="session")
def package(tmpdir_factory):
    builder = RpmPackageBuilder()
    builder.build()

    tmp_dir = tmpdir_factory.mktemp("build_output-")
    result_path = pl.Path(tmp_dir) / builder.result_file_path.name
    shutil.copy2(
        builder.result_file_path, result_path
    )
    return result_path


class RpmRepoBuilder(CacheableBuilder):

    def __init__(
            self,
            packages_dir: Union[str, pl.Path]
    ):
        self.packages_dir = pl.Path(packages_dir)

        super(RpmRepoBuilder, self).__init__()

    DEPLOYMENT_STEP = ShellScriptDeploymentStep(
        name="test_rpm_repo_builder",
        architecture=Architecture.X86_64,
        script_path="tests/end_to_end_tests/packages/prepare_test_rpm_repo.sh",
        required_steps={
            "PYTHON_BUILD": BUILD_PYTHON_GLIBC,
            "AGENT_DEPS": INSTALL_AGENT_REQUIREMENTS,
        },
        previous_step="rockylinux:9",
        cacheable=True,
        cache_as_image=True
    )

    def _build(self):
        repo_dir = self.output_path / "repo"
        shutil.copytree(
            self.packages_dir,
            repo_dir,
            dirs_exist_ok=True
        )

        subprocess.check_call([
            "createrepo", str(repo_dir)
        ])

        original_cwd = os.getcwd()
        os.chdir(self.output_path)
        try:
            shutil.make_archive(
                base_name="repo",
                format="zip",
                root_dir=repo_dir
            )
        finally:
            os.chdir(original_cwd)

        pass


@pytest.fixture(scope="session")
def rpm_repo_archive(package, prior_package, tmp_path_factory):
    packages_dir = tmp_path_factory.mktemp("rpm_packages_dir")

    shutil.copy2(
        package,
        packages_dir
    )
    shutil.copy2(
        prior_package,
        packages_dir
    )

    builder = RpmRepoBuilder(
        packages_dir=packages_dir
    )

    builder.build()

    return builder.output_path / "repo.zip"

def test_in_docker(
        # package_testing_script_frozen_binary,
        # rpm_package,
        frozen_pytest_runner_path,
        scalyr_api_key,
        scalyr_api_read_key,
        rpm_repo_archive,
        test_session_name,
        previous_package_version,
        package_version

):
    docker_repo_archive_path = pl.Path("/tmp") / rpm_repo_archive.name
    process = subprocess.Popen(
        [
            "docker",
            "run",
            "-i",
            "--rm",
            "-v",
            f"{frozen_pytest_runner_path}:/test_runner",
            "-v",
            f"{rpm_repo_archive}:{docker_repo_archive_path}",
            # "-p",
            # "8080:80",
            #"centos:7",
            "rl",
            "/test_runner",
            "tests/end_to_end_tests/packages/_test_package_locally/test_locally.py",
            "-s",
            "--scalyr-api-key",
            scalyr_api_key,
            "--scalyr-api-read-key",
            scalyr_api_read_key,
            "--server-host",
            test_session_name,
            "--package-type",
            "rpm",
            "--distro-name",
            "centos:7",
            "--packages-archive-path",
            str(docker_repo_archive_path),
            "--previous-package-version",
            previous_package_version,
            "--package-version",
            package_version
        ],
    )

    process.communicate()
    process.wait()

    assert process.returncode == 0, "The test run inside the docker container has failed. " \
                                    "Please see the output above to find real cause. " \
                                    f"Exit code: {process.returncode}"

    a = 10
