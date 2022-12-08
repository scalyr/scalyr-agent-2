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

import json
import os
import pathlib as pl
import shlex
import subprocess
import logging
import functools
import time
from typing import List, Dict

import pytest

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.managed_packages.managed_packages_builders import (
    PYTHON_PACKAGE_NAME,
    AGENT_LIBS_PACKAGE_NAME,
    AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME,
)
from tests.end_to_end_tests.tools import AgentPaths, AgentCommander, TimeoutTracker
from tests.end_to_end_tests.verify import (
    verify_logs,
    write_counter_messages_to_test_log,
    verify_agent_status,
)

logger = logging.getLogger(__name__)

"""
This test module preforms end to end testing of the Linux agent package and its dependency packages.
Since we perform testing for multiple distributions, those tests are mainly run inside another remote machines,
such as ec2 instance or docker container. If needed, it can be run locally, but you have to be aware that those tests
are changing system state and must be aware of risks.
"""


def _verify_package_subdirectories(
    package_path: pl.Path,
    package_type: str,
    package_name: str,
    output_dir: pl.Path,
    expected_folders: List[str],
):
    """
    Verify structure if the agent's dependency packages.
    First,  we have to ensure that all package files are located inside special subdirectory and nothing has leaked
    outside.
    :param package_type: Type of the package, e.g. deb, rpm.
    :param package_name: Name of the package.
    :param output_dir: Directory where to extract a package.
    :param expected_folders: List of paths that are expected to be in this package.
    """

    package_root = output_dir / package_name
    package_root.mkdir()

    # Extract package.
    if package_type == "deb":
        subprocess.check_call(["dpkg-deb", "-x", str(package_path), str(package_root)])
    elif package_type == "rpm":
        escaped_package_path = shlex.quote(str(package_path))
        command = f"rpm2cpio {escaped_package_path} | cpio -idm"
        subprocess.check_call(
            command,
            shell=True,
            cwd=package_root,
            env={"LD_LIBRARY_PATH": "/lib64"},
        )
    else:
        raise Exception(f"Unknown package type {package_type}.")

    remaining_paths = set(package_root.glob("**/*"))

    for expected in expected_folders:
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
    package_builder,
    tmp_path,
    distro_name,
    python_package_path,
    agent_libs_package_path,
):

    if distro_name not in ["ubuntu2204", "amazonlinux2"]:
        pytest.skip("No need to check on all distros.")

    package_type = package_builder.PACKAGE_TYPE

    _verify_package_subdirectories(
        package_path=python_package_path,
        package_type=package_builder.PACKAGE_TYPE,
        package_name=PYTHON_PACKAGE_NAME,
        output_dir=tmp_path,
        expected_folders=[
            f"usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            f"usr/share/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            # Depending on its type, a package also may install its own "metadata", so we have to take it into
            # account too.
            f"usr/share/doc/{PYTHON_PACKAGE_NAME}/"
            if package_type == "deb"
            else "usr/lib/.build-id/",
        ],
    )

    # Verify structure of the agent_libs package and make sure there's no any file outside it.
    _verify_package_subdirectories(
        package_path=agent_libs_package_path,
        package_type=package_builder.PACKAGE_TYPE,
        package_name=AGENT_LIBS_PACKAGE_NAME,
        output_dir=tmp_path,
        expected_folders=[
            f"usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            f"usr/share/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/",
            # Depending on its type, a package also may install its own "metadata", so we have to take it into
            # account too.
            f"usr/share/doc/{AGENT_LIBS_PACKAGE_NAME}/"
            if package_type == "deb"
            else "usr/lib/.build-id/",
        ],
    )


def test_packages(
    package_builder_name,
    package_builder,
    remote_machine_type,
    convenience_script_path,
    distro_name,
    scalyr_api_key,
    scalyr_api_read_key,
    scalyr_server,
    test_session_suffix,
    agent_version,
    tmp_path,
):
    timeout_tracker = TimeoutTracker(300)
    _print_system_information()
    _prepare_environment(
        package_type=package_builder.PACKAGE_TYPE,
        remote_machine_type=remote_machine_type,
        distro_name=distro_name
    )

    try:
        _install_from_convenience_script(
            script_path=convenience_script_path,
        )
    except subprocess.CalledProcessError:
        install_log_path = pl.Path("scalyr_install.log")
        if install_log_path.exists():
            logger.error(
                f"Install log:\n{install_log_path.read_text()}\n"
            )

        logger.exception(
            f"Install script has failed."
        )
        raise

    logger.info(
        "Execute simple sanity test script for the python interpreter and its libraries."
    )
    subprocess.check_call(
        [
            f"/usr/lib/{AGENT_DEPENDENCY_PACKAGE_SUBDIR_NAME}/bin/python3",
            "tests/end_to_end_tests/managed_packages_tests/verify_python_interpreter.py",
        ],
        env={
            # It's important to override the 'LD_LIBRARY_PATH' to be sure that libraries paths from the test runner
            # frozen binary are not leaked to a script's process.
            "LD_LIBRARY_PATH": "",
            "PYTHONPATH": str(SOURCE_ROOT),
        },
    )

    agent_paths = AgentPaths(
        configs_dir=pl.Path("/etc/scalyr-agent-2"),
        logs_dir=pl.Path("/var/log/scalyr-agent-2"),
        install_root=pl.Path("/usr/share/scalyr-agent-2"),
    )

    logger.info("Verifying agent.json and agent.d permissions")
    _verify_agent_package_config_permissions(agent_paths=agent_paths)

    logger.info("Verifying install_info.json file exists")
    install_info_path = agent_paths.install_root / "py/scalyr_agent/install_info.json"
    assert install_info_path.is_file(), f"The {install_info_path} file is missing."

    logger.info("Verifying rc.d symlinks exist")
    _run_shell("ls -la /etc/rc*.d/ | grep scalyr-agent")
    _run_shell("ls -la /etc/rc*.d/ | grep scalyr-agent | wc -l | grep 7")

    server_host = (
        f"package-{package_builder_name}-test-{test_session_suffix}-{int(time.time())}"
    )

    upload_test_log_path = agent_paths.logs_dir / "test.log"

    config = {
        "api_key": scalyr_api_key,
        "server_attributes": {"serverHost": server_host},
        "logs": [{"path": str(upload_test_log_path), "attributes": {"parser": "json"}}],
    }

    agent_commander = AgentCommander(
        executable_args=["scalyr-agent-2"], agent_paths=agent_paths
    )

    agent_commander.agent_paths.agent_config_path.write_text(json.dumps(config))

    logger.info("Start agent")

    agent_commander.start()

    verify_agent_status(agent_version=agent_version, agent_commander=agent_commander)

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

    _stop_agent_and_remove_logs_and_data(
        agent_commander=agent_commander,
    )

    _perform_ssl_checks(
        default_config=config,
        agent_commander=agent_commander,
        agent_paths=agent_paths,
        timeout_tracker=timeout_tracker,
    )
    # TODO: Add actual agent package testing here.


def _verify_agent_package_ownership(package_root: pl.Path):
    agent_json_path = package_root / "etc/scalyr-agent-2/agent.json"
    assert (
        agent_json_path.stat().st_uid == 0
    ), f"Owner user id of the file '{agent_json_path}' has to be 0 (root)"
    assert (
        agent_json_path.stat().st_gid == 0
    ), f"Owner group id of the file '{agent_json_path}' has to be 0 (root)"


def _verify_agent_package_config_permissions(agent_paths: AgentPaths):
    oct_mode = str(oct(agent_paths.agent_config_path.stat().st_mode))[-3:]
    assert (
        oct_mode == "640"
    ), f"Expected permissions of the 'agent.json' is 640, got {oct_mode}"

    oct_mode = str(oct(agent_paths.agent_d_path.stat().st_mode))[-3:]
    assert (
        oct_mode == "751"
    ), f"Expected permissions of the 'agent.d' is 751, got {oct_mode}"


def _perform_ssl_checks(
    default_config: Dict,
    agent_commander: AgentCommander,
    agent_paths: AgentPaths,
    timeout_tracker: TimeoutTracker,
):
    def _add_config(config):
        agent_paths.agent_config_path.write_text(json.dumps(config))

    # 1. Configure invalid path for "ca_cert_path" and verify agent throws and fails to start
    logger.info("Performing invalid ca_cert_path config option checks")
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


# Additional paths to add in case if tests run within "frozen" pytest executable.
_ADDITIONAL_ENVIRONMENT = {
    "LD_LIBRARY_PATH": "/lib",
    "PATH": "/bin:/sbin:/usr/bin:/usr/sbin"
}


def _install_from_convenience_script(
        script_path: pl.Path,
):
    """Install agent using convenience script."""
    subprocess.check_call(
        ["bash", str(script_path)],
        env=_ADDITIONAL_ENVIRONMENT
    )


def _prepare_environment(
        package_type: str,
        remote_machine_type: str,
        distro_name: str
):
    """
    If needed, do some preparation before agent installation.
    :return:
    """
    if "TEST_RUNS_IN_DOCKER" in os.environ:
        if package_type == "deb":
            _run_shell("apt update")
            _call_apt(
                ["install", "-y", "ca-certificates"],
            )
            if "debian" in distro_name:
                _call_apt(["install", "-y", "procps"])
        elif package_type == "rpm":
            if distro_name == "amazonlinux2":
                _call_yum(["install", "-y", "procps"])

    if distro_name == "centos6":
        # for centos 6, we remove repo file for disabled repo, so it could use vault repo.
        pl.Path("/etc/yum.repos.d/CentOS-Base.repo").unlink()
    elif distro_name == "centos8":
        # For centos 8 we replace repo urls for vault.
        for repo_name in ["BaseOS", "AppStream"]:
            repo_file = pl.Path(f"/etc/yum.repos.d/CentOS-Linux-{repo_name}.repo")
            content = repo_file.read_text()
            content = content.replace("mirror.centos.org", "vault.centos.org")
            content = content.replace("#baseurl", "baseurl")
            content = content.replace("mirrorlist=", "#mirrorlist=")
            repo_file.write_text(content)


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


def _run_shell(command: str, return_output: bool = False, env=None):
    env = env or {}
    if return_output:
        return subprocess.check_output(command, shell=True, env=env).decode().strip()

    subprocess.check_call(command, shell=True, env=env)


def _call_apt(command: List[str]):
    """Run apt command"""
    subprocess.check_call(
        ["apt", *command],
        # Since test may run in "frozen" pytest executable, add missing variables.
        env={"LD_LIBRARY_PATH": "/lib", "PATH": "/usr/sbin:/sbin:/usr/bin:/bin"},
    )


def _call_yum(command: List[str]):
    """Run yum command"""
    subprocess.check_call(
        ["yum", *command],
        # Since test may run in "frozen" pytest executable, add missing variables.
        env={"LD_LIBRARY_PATH": "/lib64"},
    )
