# Copyright 2014-2022 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This test module preforms end to end testing of the Linux agent package and its dependency packages.
Since we perform testing for multiple distributions, those tests are mainly run inside another remote machines,
such as ec2 instance or docker container. If needed, it can be run locally, but you have to be aware that those tests
are changing system state and must be aware of risks.
"""

import json
import pathlib as pl
import re
import shlex
import subprocess
import logging
import functools
import time
from typing import List, Dict

import pytest

from agent_build_refactored.tools.constants import SOURCE_ROOT

from agent_build_refactored.managed_packages.build_dependencies_versions import (
    PYTHON_PACKAGE_SSL_3_VERSION,
)

from agent_build_refactored.managed_packages.managed_packages_builders import (
    AGENT_SUBDIR_NAME,
    AGENT_AIO_PACKAGE_NAME,
)
from tests.end_to_end_tests.tools import AgentPaths, AgentCommander, TimeoutTracker
from tests.end_to_end_tests.verify import (
    verify_logs,
    write_counter_messages_to_test_log,
    verify_agent_status,
)
from tests.end_to_end_tests.run_in_remote_machine import TargetDistro

logger = logging.getLogger(__name__)

DISTROS_WITH_PYTHON_2 = {"centos7", "ubuntu1404", "ubuntu1604"}


def _verify_package_paths(
    package_path: pl.Path,
    package_type: str,
    package_name: str,
    output_dir: pl.Path,
    expected_paths: List[str],
):
    """
    Verify structure if the agent's dependency packages.
    First,  we have to ensure that all package files are located inside special subdirectory and nothing has leaked
    outside.
    :param package_type: Type of the package, e.g. deb, rpm.
    :param package_name: Name of the package.
    :param output_dir: Directory where to extract a package.
    :param expected_paths: List of paths that are expected to be in this package.
    """

    package_root = output_dir / package_name
    package_root.mkdir()

    _extract_package(
        package_type=package_type,
        package_path=package_path,
        output_path=package_root,
    )

    remaining_paths = set(package_root.glob("**/*"))

    for expected in expected_paths:
        expected_path = package_root / expected
        for path in list(remaining_paths):
            if str(path).startswith(str(expected_path)) or str(path) in str(
                expected_path
            ):
                remaining_paths.remove(path)

    assert (
        len(remaining_paths) == 0
    ), "Something remains outside if the expected package structure."


def test_dependency_packages(
    package_builder, tmp_path, target_distro, agent_package_path, use_aio_package
):
    if not use_aio_package:
        pytest.skip("Only AIO packages are tested.")

    if target_distro.name not in ["ubuntu2204", "amazonlinux2"]:
        pytest.skip("No need to check on all distros.")

    package_type = package_builder.PACKAGE_TYPE
    _verify_package_paths(
        package_path=agent_package_path,
        package_type=package_builder.PACKAGE_TYPE,
        package_name=AGENT_AIO_PACKAGE_NAME,
        output_dir=tmp_path,
        expected_paths=[
            f"opt/{AGENT_SUBDIR_NAME}/",
            f"etc/{AGENT_SUBDIR_NAME}/",
            "etc/init.d/scalyr-agent-2",
            f"usr/share/{AGENT_SUBDIR_NAME}/",
            "usr/sbin/scalyr-agent-2",
            "usr/sbin/scalyr-agent-2-config",
            f"var/lib/{AGENT_SUBDIR_NAME}/",
            f"var/log/{AGENT_SUBDIR_NAME}/",
            f"var/opt/{AGENT_SUBDIR_NAME}/",
            # Depending on its type, a package also may install its own "metadata", so we have to take it into
            # account too.
            f"usr/share/doc/{AGENT_SUBDIR_NAME}/"
            if package_type == "deb"
            else "usr/lib/.build-id/",
        ],
    )


LINUX_PACKAGE_AGENT_PATHS = AgentPaths(
    configs_dir=pl.Path(f"/etc/{AGENT_SUBDIR_NAME}"),
    logs_dir=pl.Path(f"/var/log/{AGENT_SUBDIR_NAME}"),
    install_root=pl.Path(f"/usr/share/{AGENT_SUBDIR_NAME}"),
)


def test_packages(
    package_builder_name,
    package_builder,
    remote_machine_type,
    convenience_script_path,
    target_distro,
    scalyr_api_key,
    scalyr_api_read_key,
    scalyr_server,
    test_session_suffix,
    agent_version,
    tmp_path,
    use_aio_package,
    agent_package_name,
):
    if "x86_64" not in package_builder_name:
        timeout_tracker = TimeoutTracker(800)
    else:
        timeout_tracker = TimeoutTracker(400)

    _print_system_information()
    _prepare_environment(
        package_type=package_builder.PACKAGE_TYPE,
        remote_machine_type=remote_machine_type,
        target_distro=target_distro,
        timeout_tracker=timeout_tracker,
        use_aio_package=use_aio_package,
    )

    logger.info("Install agent from install script.")
    _install_from_convenience_script(
        script_path=convenience_script_path,
        target_distro=target_distro,
        use_aio_package=use_aio_package,
    )

    if use_aio_package:
        _verify_python_and_libraries()

    logger.info("Verifying install_info.json file exists")
    install_info_path = (
        LINUX_PACKAGE_AGENT_PATHS.install_root / "py/scalyr_agent/install_info.json"
    )
    assert install_info_path.is_file(), f"The {install_info_path} file is missing."

    logger.info("Verifying rc.d symlinks exist")
    _run_shell("ls -la /etc/rc*.d/ | grep scalyr-agent")
    _run_shell("ls -la /etc/rc*.d/ | grep scalyr-agent | wc -l | grep 7")

    server_host = f"package-{package_builder_name}-{target_distro.name}-test-{test_session_suffix}-{int(time.time())}"

    upload_test_log_path = LINUX_PACKAGE_AGENT_PATHS.logs_dir / "test.log"

    config = {
        "api_key": scalyr_api_key,
        "server_attributes": {"serverHost": server_host},
        "logs": [{"path": str(upload_test_log_path), "attributes": {"parser": "json"}}],
    }

    agent_commander = AgentCommander(
        executable_args=["scalyr-agent-2"], agent_paths=LINUX_PACKAGE_AGENT_PATHS
    )

    agent_commander.agent_paths.agent_config_path.write_text(json.dumps(config))

    logger.info("Start agent")

    agent_commander.start_and_wait(env=_ADDITIONAL_ENVIRONMENT, logger=logger)

    verify_agent_status(
        agent_version=agent_version,
        agent_commander=agent_commander,
        timeout_tracker=timeout_tracker,
    )

    logger.info("Verify agent log uploads.")
    verify_logs(
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        get_agent_log_content=agent_commander.agent_paths.agent_log_path.read_text,
        counters_verification_query_filters=[
            f"$logfile=='{upload_test_log_path}'",
            f"$serverHost=='{server_host}'",
        ],
        counter_getter=lambda e: e["attributes"]["count"],
        write_counter_messages=functools.partial(
            write_counter_messages_to_test_log,
            upload_test_log_path=upload_test_log_path,
        ),
        verify_ssl=True,
        timeout_tracker=timeout_tracker,
    )

    logger.info(
        "Look in to the agent's log to verify that correct version of the OpenSSL is used by the package"
    )
    agent_log = agent_commander.agent_paths.agent_log_path.read_text()
    for line in agent_log.splitlines():
        if "Starting scalyr agent..." in line:
            starting_agent_message = line
            break
    else:
        raise Exception("Starting agent message is not found.")

    if use_aio_package:
        logger.info(
            "Verify which version of OpenSSL has been picked up by the AIO package."
        )

        m = re.search(r"OpenSSL version_number=(\d+)", starting_agent_message)
        openssl_version = int(m.group(1))

        if isinstance(target_distro.expected_openssl_version_number, list):
            expected_openssl_versions = target_distro.expected_openssl_version_number
        else:
            expected_openssl_versions = [target_distro.expected_openssl_version_number]

        assert openssl_version in expected_openssl_versions

    _stop_agent_and_remove_logs_and_data(
        agent_commander=agent_commander,
    )

    _perform_ssl_checks(
        default_config=config,
        agent_commander=agent_commander,
        agent_paths=LINUX_PACKAGE_AGENT_PATHS,
        timeout_tracker=timeout_tracker,
    )

    logger.info("Verify that custom monitors are not gone after package removal")
    monitor_file_path = (
        LINUX_PACKAGE_AGENT_PATHS.install_root / "monitors" / "dummy.txt"
    )
    monitor_file_path.write_text("test")

    logger.info("Cleanup")
    _remove_all_agent_files(
        package_name=agent_package_name, package_type=package_builder.PACKAGE_TYPE
    )

    assert monitor_file_path.exists()
    assert monitor_file_path.read_text() == "test"


def test_agent_package_config_ownership(package_builder, agent_package_path, tmp_path):
    """
    Test ownership and permissions of the config files.
    """

    logger.info("Verifying agent.json and agent.d permissions")
    _extract_package(
        package_type=package_builder.PACKAGE_TYPE,
        package_path=agent_package_path,
        output_path=tmp_path,
    )

    agent_etc_path = tmp_path / "etc/scalyr-agent-2"

    # Check owner of the /etc/scalyr-agent-2
    assert (
        agent_etc_path.stat().st_uid == 0
    ), f"Owner user id of the file '{agent_etc_path}' has to be 0 (root)"
    assert (
        agent_etc_path.stat().st_gid == 0
    ), f"Owner group id of the file '{agent_etc_path}' has to be 0 (root)"

    agent_json_path = agent_etc_path / "agent.json"
    # Check owner of the config file
    assert (
        agent_json_path.stat().st_uid == 0
    ), f"Owner user id of the file '{agent_json_path}' has to be 0 (root)"
    assert (
        agent_json_path.stat().st_gid == 0
    ), f"Owner group id of the file '{agent_json_path}' has to be 0 (root)"

    agent_d_path = agent_etc_path / "agent.d"
    # Check owner of the agent.d directory
    assert (
        agent_d_path.stat().st_uid == 0
    ), f"Owner user id of the file '{agent_d_path}' has to be 0 (root)"
    assert (
        agent_d_path.stat().st_gid == 0
    ), f"Owner group id of the file '{agent_d_path}' has to be 0 (root)"

    # Check permissions if agent.json
    oct_mode = str(oct(agent_json_path.stat().st_mode))[-3:]
    assert (
        oct_mode == "640"
    ), f"Expected permissions of the 'agent.json' is 640, got {oct_mode}"

    # Check permissions if agent.d
    oct_mode = str(oct(agent_d_path.stat().st_mode))[-3:]
    assert (
        oct_mode == "751"
    ), f"Expected permissions of the 'agent.d' is 751, got {oct_mode}"


def test_upgrade(
    package_builder,
    package_builder_name,
    repo_url,
    repo_public_key_url,
    remote_machine_type,
    distro_name,
    stable_agent_package_version,
    scalyr_api_key,
    test_session_suffix,
    agent_version,
    use_aio_package,
    agent_package_name,
):
    """
    Perform an upgrade from the current stable release. The stable version of the package also has to be in the same
    repository as the tested packages.
    """

    if use_aio_package:
        # TODO: Remove this skip when we have first stable AIO package.
        pytest.skip(
            "We only test the upgrade process of the non AIO packages, because there are no stable packages for AIO."
        )

    if distro_name == "centos6":
        pytest.skip(
            "Can not upgrade from CentOS 6 because our previous variant of packages does not support it."
        )

    if "x86_64" not in package_builder_name:
        timeout_tracker = TimeoutTracker(400)
    else:
        timeout_tracker = TimeoutTracker(200)

    logger.info("Install stable version of the agent")
    if distro_name in DISTROS_WITH_PYTHON_2:
        system_python_package_name = "python"
    else:
        system_python_package_name = "python3"

    if package_builder.PACKAGE_TYPE == "deb":
        repo_source_list_path = pl.Path("/etc/apt/sources.list.d/scalyr.list")
        repo_source_list_path.write_text(
            f"deb [allow-insecure=yes] {repo_url} scalyr main"
        )
        _call_apt(["update"])

        _call_apt(["install", "-y", system_python_package_name])
        _call_apt(
            [
                "install",
                "-y",
                "--allow-unauthenticated",
                f"{agent_package_name}={stable_agent_package_version}",
            ]
        )
    elif package_builder.PACKAGE_TYPE == "rpm":
        yum_repo_file_path = pl.Path("/etc/yum.repos.d/scalyr.repo")
        yum_repo_file_content = f"""
[scalyr]
name=Scalyr packages.
baseurl={repo_url}
enabled=1
gpgcheck=0
repo_gpgcheck=0
"""
        yum_repo_file_path.write_text(yum_repo_file_content)
        _call_yum(["install", "-y", system_python_package_name])
        _call_yum(
            ["install", "-y", f"{agent_package_name}-{stable_agent_package_version}-1"]
        )
    else:
        raise Exception(f"Unknown package type: {package_builder.PACKAGE_TYPE}")

    # Write config
    server_host = (
        f"package-{package_builder_name}-test-{test_session_suffix}-{int(time.time())}"
    )

    config = {
        "api_key": scalyr_api_key,
        "server_attributes": {"serverHost": server_host},
    }

    agent_commander = AgentCommander(
        executable_args=["scalyr-agent-2"], agent_paths=LINUX_PACKAGE_AGENT_PATHS
    )

    agent_commander.agent_paths.agent_config_path.write_text(json.dumps(config))

    logger.info("Upgrade agent")
    if package_builder.PACKAGE_TYPE == "deb":
        _call_apt(
            [
                "install",
                "-y",
                "--only-upgrade",
                "--allow-unauthenticated",
                f"{agent_package_name}",
            ]
        )
    elif package_builder.PACKAGE_TYPE == "rpm":
        _call_yum(["install", "-y", f"{agent_package_name}"])
    else:
        raise Exception(f"Unknown package type: {package_builder.PACKAGE_TYPE}")

    logger.info("Verify that agent config remains after upgrade.")
    assert LINUX_PACKAGE_AGENT_PATHS.agent_config_path.exists()
    assert server_host in LINUX_PACKAGE_AGENT_PATHS.agent_config_path.read_text()

    agent_commander.start_and_wait(logger=logger)

    verify_agent_status(
        agent_version=agent_version,
        agent_commander=agent_commander,
        timeout_tracker=timeout_tracker,
    )

    agent_commander.stop()

    logger.info("Cleanup")
    _remove_all_agent_files(
        package_name=agent_package_name, package_type=package_builder.PACKAGE_TYPE
    )


def _perform_ssl_checks(
    default_config: Dict,
    agent_commander: AgentCommander,
    agent_paths: AgentPaths,
    timeout_tracker: TimeoutTracker,
):

    """
    Perform various checks of the ssl connection.
    """

    def _add_config(config):
        agent_paths.agent_config_path.write_text(json.dumps(config))

    # 1. Configure invalid path for "ca_cert_path" and verify agent throws and fails to start
    logger.info("Performing invalid ca_cert path config option checks")
    invalid_ca_cert_path_config = default_config.copy()
    invalid_ca_cert_path_config["ca_cert_path"] = "/tmp/invalid/ca_certs.crt"
    _add_config(invalid_ca_cert_path_config)

    agent_commander.start()

    with pytest.raises(subprocess.CalledProcessError) as err_info:
        agent_commander.get_status()

    assert b"The agent does not appear to be running." in err_info.value.stdout

    agent_log = agent_paths.agent_log_path.read_text()
    assert "ca_cert_path: /tmp/invalid/ca_certs.crt" in agent_log
    assert "failedAgentMain" in agent_log
    assert (
        'Invalid path "/tmp/invalid/ca_certs.crt" specified for the "ca_cert_path"'
        in agent_log
    )
    _clear_agent_dirs_and_print_log(agent_commander)

    # 2. Configure agent to use system CA bundle to verify the server cert and verify it works
    logger.info("Performing system CA bundle checks")
    system_ca_bundle_config = default_config.copy()
    system_ca_bundle_config["ca_cert_path"] = "/etc/ssl/system-ca-bundle.crt"
    _add_config(system_ca_bundle_config)
    ubuntu_certs = pl.Path("/etc/ssl/certs/ca-certificates.crt")
    fedora_certs = pl.Path("/etc/ssl/certs/ca-bundle.crt")
    if ubuntu_certs.is_file():
        system_ca_bundle_path = ubuntu_certs
    elif fedora_certs.is_file():
        system_ca_bundle_path = fedora_certs
    else:
        raise Exception("No system CA bundle found")

    # NOTE: We create a symlink so we can re-use config with a fixed value for ca_cert_path
    logger.info(f"Using system ca bundle: ${system_ca_bundle_path}")

    system_ca_bundle_path_symlink_path = pl.Path("/etc/ssl/system-ca-bundle.crt")
    system_ca_bundle_path_symlink_path.symlink_to(system_ca_bundle_path)
    agent_commander.start()

    def _wait_for_string_in_log(text):
        while text not in agent_paths.agent_log_path.read_text():
            timeout_tracker.sleep(1, f"Can't wait for a text '{text}' in the agent log")

    _wait_for_string_in_log("HttpConnection uses native os ssl")
    agent_log = agent_paths.agent_log_path.read_text()
    assert "ca_cert_path: /etc/ssl/system-ca-bundle.crt" in agent_log
    assert "HttpConnection uses native os ssl" in agent_log

    agent_status = agent_commander.get_status()
    assert "Last successful communication with Scalyr:" in agent_status
    assert "Last successful communication with Scalyr: Never" not in agent_status
    assert "Last copy response status:                 success" in agent_status
    _stop_agent_and_remove_logs_and_data(agent_commander=agent_commander)

    # 3. Mimic MITM attack by pointing a random domain to agent.scalyr.com and verify hostname
    # check post SSL handshake and cert validation fails
    logger.info("Performing MITM and hostname verification checks")
    agent_scalyr_ip = _run_shell(
        "getent hosts agent.scalyr.com | awk '{ print $1 }' | tail -n 1 | tr -d \"\n\"",
        return_output=True,
    )
    mock_host = "invalid.mitm.should.fail.test.agent.scalyr.com"
    hosts_file = pl.Path("/etc/hosts")
    hosts_file_orig = hosts_file.read_text()
    invalid_host_mitm_config = default_config.copy()
    invalid_host_mitm_config[
        "scalyr_server"
    ] = "https://invalid.mitm.should.fail.test.agent.scalyr.com:443"
    _add_config(invalid_host_mitm_config)
    try:
        hosts_file.write_text(f"{agent_scalyr_ip} {mock_host}")
        agent_commander.start()
        _wait_for_string_in_log("Failed to connect to")
    finally:
        hosts_file.write_text(hosts_file_orig)

    agent_log = agent_paths.agent_log_path.read_text()
    assert f'Failed to connect to "https://{mock_host}:443"' in agent_log
    assert "because of server certificate validation error" in agent_log
    assert "This likely indicates a MITM attack" in agent_log

    agent_status = agent_commander.get_status()
    assert "Last successful communication with Scalyr: Never" in agent_status
    assert "Bytes uploaded successfully:               0" in agent_status
    assert "Last copy request size:                    0" in agent_status
    assert "Last copy response size:                   0" in agent_status
    assert (
        "Last copy response status:                 client/connectionFailedCertHostnameValidationFailed"
        in agent_status
    )
    _stop_agent_and_remove_logs_and_data(agent_commander)

    # 4. Verify that CA validation fail if we connect to a server with certificate issues by CA
    logger.info("Performing cert signed by CA we dont trust checks")
    invalid_bad_cert_config = default_config.copy()
    invalid_bad_cert_config["scalyr_server"] = "https://example.com:443"
    # Note: We can't really on example.com using self-signed cert, so we use a CA which
    # doesn't trust that cert.
    # Long term we could spawn test HTTP server locally and use that, but that's more
    # involved.
    bad_ca_cert_path = (
        SOURCE_ROOT
        / "tests/end_to_end_tests/managed_packages_tests/fixtures/bad_ca_certs.crt"
    )
    invalid_bad_cert_config["ca_cert_path"] = str(bad_ca_cert_path)
    _add_config(invalid_bad_cert_config)
    agent_commander.start()
    _wait_for_string_in_log("Failed to connect to")

    agent_log = agent_paths.agent_log_path.read_text()
    print(agent_log)
    assert 'Failed to connect to "https://example.com:443"' in agent_log
    assert "due to some SSL error" in agent_log
    assert "certificate verify failed" in agent_log

    agent_status = agent_commander.get_status()
    assert "Last successful communication with Scalyr: Never" in agent_status
    assert "Bytes uploaded successfully:               0" in agent_status
    assert "Last copy request size:                    0" in agent_status
    assert "Last copy response size:                   0" in agent_status
    assert (
        "Last copy response status:                 client/connectionFailedSSLError"
        in agent_status
    )
    _stop_agent_and_remove_logs_and_data(agent_commander)


def _verify_python_and_libraries():
    """Verify agent python and libs dependency packages installation."""

    logger.info("Check installation of the additional requirements")
    additional_requirements_path = pl.Path(
        "/opt/scalyr-agent-2/etc/additional-requirements.txt"
    )

    additional_requirements_content = additional_requirements_path.read_text()
    additional_requirements_content += "\nflask==2.2.2"

    additional_requirements_path.write_text(additional_requirements_content)

    subprocess.run(
        ["/opt/scalyr-agent-2/bin/agent-libs-config", "initialize"],
        check=True,
    )

    venv_python_executable = f"/var/opt/{AGENT_SUBDIR_NAME}/venv/bin/python3"

    result = subprocess.run(
        [
            str(venv_python_executable),
            "-m",
            "pip",
            "freeze",
        ],
        capture_output=True,
        check=True,
    )

    assert "Flask==2.2.2" in result.stdout.decode()

    logger.info(
        "Execute simple sanity test script for the python interpreter and its libraries."
    )
    subprocess.check_call(
        [
            str(venv_python_executable),
            "tests/end_to_end_tests/managed_packages_tests/verify_python_interpreter.py",
        ],
        env={
            # It's important to override the 'LD_LIBRARY_PATH' to be sure that libraries paths from the test runner
            # frozen binary are not leaked to a script's process.
            "LD_LIBRARY_PATH": "/lib",
            "PYTHONPATH": str(SOURCE_ROOT),
        },
    )


# Additional paths to add in case if tests run within "frozen" pytest executable.
_ADDITIONAL_ENVIRONMENT = {
    "LD_LIBRARY_PATH": "/lib:/lib64",
    "PATH": "/bin:/sbin:/usr/bin:/usr/sbin",
}


def _install_from_convenience_script(
    script_path: pl.Path, target_distro: TargetDistro, use_aio_package: bool
):
    """Install agent using convenience script."""

    command_args = ["bash", str(script_path), "--verbose"]

    if use_aio_package:
        command_args.append("--use-aio-package")

    try:
        result = subprocess.run(
            command_args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_ADDITIONAL_ENVIRONMENT,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Install script has failed.\nOutput:\n{e.stdout.decode()}")
        raise

    output = result.stdout.decode()
    logger.info(f"Install script has finished.\nOutput:\n{output}")

    if use_aio_package:
        # Verify which variant of OpenSSL has been chosen by the package, system's one or embedded.
        # NOTE: Expected results of this check may eventually become outdated, because of distribution's EOL
        # or changes in version requirements for OpenSSL in Python.
        # If system's OpenSSL is not used anymore on some distro, it may be due to this distro has become
        # outdated enough, so Python just does not accept its version of OpenSSL and package falls back to
        # embedded OpenSSL.
        if target_distro.name == "ubuntu2204":
            assert "Looking for system OpenSSL >= 3: found OpenSSL 3.0." in output
        elif target_distro.name == "ubuntu2004":
            assert "Looking for system OpenSSL >= 3: Not found" in output
            assert "Looking for system OpenSSL >= 1.1.1: found OpenSSL 1.1.1" in output
        elif target_distro.name in ["ubuntu1404", "centos6"]:
            assert "Looking for system OpenSSL >= 3: Not found" in output
            assert "Looking for system OpenSSL >= 1.1.1: Not found" in output
            assert (
                f"Using embedded OpenSSL == OpenSSL {PYTHON_PACKAGE_SSL_3_VERSION}"
                in output
            )


def _prepare_environment(
    package_type: str,
    remote_machine_type: str,
    target_distro: TargetDistro,
    timeout_tracker: TimeoutTracker,
    use_aio_package: bool,
):
    """
    If needed, do some preparation before agent installation.
    :return:
    """

    logger.info("Preparing test environment")
    packages_to_install = []

    if remote_machine_type == "docker":
        if package_type == "deb":
            packages_to_install.extend(["ca-certificates"])
            if "debian" in target_distro.name:
                packages_to_install.append("procps")
        elif package_type == "rpm":
            if target_distro.name == "amazonlinux2":
                packages_to_install.append("procps")

    if package_type == "deb":
        # In some distributions apt update may be a pretty flaky due to connection and cache issues,
        # so we add some retries.
        while True:
            try:
                _run_shell("apt-get clean")
                _run_shell("apt update")
                break
            except subprocess.CalledProcessError:
                timeout_tracker.sleep(1, "Can not update apt.")

    if target_distro.name == "centos6":
        # for centos 6, we remove repo file for disabled repo, so it could use vault repo.
        pl.Path("/etc/yum.repos.d/CentOS-Base.repo").unlink()
    elif target_distro.name == "centos8":
        # For centos 8 we replace repo urls for vault.
        for repo_name in ["BaseOS", "AppStream"]:
            repo_file = pl.Path(f"/etc/yum.repos.d/CentOS-Linux-{repo_name}.repo")
            content = repo_file.read_text()
            content = content.replace("mirror.centos.org", "vault.centos.org")
            content = content.replace("#baseurl", "baseurl")
            content = content.replace("mirrorlist=", "#mirrorlist=")
            repo_file.write_text(content)

    if not use_aio_package:
        # Install required Python interpreter, if that's not AIO package.
        if target_distro.name in DISTROS_WITH_PYTHON_2:
            system_python_package_name = "python"
        else:
            system_python_package_name = "python3"

        packages_to_install.append(system_python_package_name)

    # Install additional packages if needed.
    if packages_to_install:
        if package_type == "deb":
            _call_apt(["install", "-y", *packages_to_install])
        elif package_type == "rpm":
            _call_yum(["install", "-y", *packages_to_install])


def _clear_agent_dirs_and_print_log(agent_commander: AgentCommander):
    logger.info("Tailing last 50 lines of log after stop before log removal")
    logger.info(
        "\n".join(
            agent_commander.agent_paths.agent_log_path.read_text().splitlines()[50:]
        )
    )
    # Removing logs and other data from previous run
    pl.Path("/var/log/scalyr-agent-2/agent.log").unlink()
    # Remove all checkpoints files.
    for p in pl.Path("/var/lib/scalyr-agent-2").glob("*checkpoints*.json"):
        p.unlink()


def _stop_agent_and_remove_logs_and_data(
    agent_commander: AgentCommander,
):
    agent_commander.stop()
    _clear_agent_dirs_and_print_log(agent_commander=agent_commander)


def _restart_agent_and_clear_dirs(agent_commander: AgentCommander):
    logger.info("Restarting agent.")
    agent_commander.stop()

    agent_commander.start()


def _print_system_information():
    """
    :return:
    """

    output = f"""
===========================
System information
===========================
{_run_shell("uname -a", return_output=True)}
{_run_shell("cat /etc/*-release", return_output=True)}
{_run_shell("cat /etc/passwd", return_output=True)}
{_run_shell("id", return_output=True)}
"""

    logger.info(output)


def _extract_package(package_type: str, package_path: pl.Path, output_path: pl.Path):
    if package_type == "deb":
        subprocess.check_call(["dpkg-deb", "-x", str(package_path), str(output_path)])
    elif package_type == "rpm":
        escaped_package_path = shlex.quote(str(package_path))
        command = f"rpm2cpio {escaped_package_path} | cpio -idm"
        subprocess.check_call(
            command,
            shell=True,
            cwd=output_path,
            env={"LD_LIBRARY_PATH": "/lib64"},
        )
    else:
        raise Exception(f"Unknown package type {package_type}.")


def _remove_all_agent_files(
    package_name: str,
    package_type: str,
):
    """
    Cleanup system from everything that related with agent, trying to bring
    system into state before agent was installed.
    """

    if package_type == "deb":
        _call_apt(["remove", "-y", package_name])
        _call_apt(["purge", "-y", package_name])
        _call_apt(["autoremove", "-y"])
        source_list_path = pl.Path("/etc/apt/sources.list.d/scalyr.list")
        source_list_path.unlink()

        keyring_path = pl.Path("/usr/share/keyrings/scalyr.gpg")
        if keyring_path.exists():
            keyring_path.unlink()
        tmp_keyring_path = pl.Path("/usr/share/keyrings/scalyr.gpg~")
        if tmp_keyring_path.exists():
            tmp_keyring_path.unlink()
        _call_apt(["update"])

    elif package_type == "rpm":
        _call_yum(["remove", "-y", package_name])
    else:
        raise Exception(f"Unknown package type: {package_type}")


def _run_shell(command: str, return_output: bool = False, env=None):
    env = env or {}
    if return_output:
        return subprocess.check_output(command, shell=True, env=env).decode().strip()

    subprocess.check_call(command, shell=True, env=env)


def _call_apt(command: List[str]):
    """Run apt command"""
    subprocess.check_call(
        ["apt-get", *command],
        # Since test may run in "frozen" pytest executable, add missing variables.
        env=_ADDITIONAL_ENVIRONMENT,
    )


def _call_yum(command: List[str]):
    """Run yum command"""
    subprocess.check_call(
        ["yum", *command],
        # Since test may run in "frozen" pytest executable, add missing variables.
        env=_ADDITIONAL_ENVIRONMENT,
    )
