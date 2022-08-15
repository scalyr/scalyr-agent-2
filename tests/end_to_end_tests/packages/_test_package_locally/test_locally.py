import functools
import json
import logging
import pprint
import re
from http.server import SimpleHTTPRequestHandler
from socketserver import TCPServer
import threading
import time
import pathlib as pl
import subprocess
import os
import shutil
import pytest

from tests.end_to_end_tests.log_verify import (
    verify_test_log_file_upload,
    check_agent_log_for_errors,
    write_messages_to_test_log,
    check_requests_stats_in_agent_log,
)

from tests.end_to_end_tests.tools import AgentPaths, get_testing_logger


log = get_testing_logger(__name__)


def pytest_generate_tests(metafunc):
    package_type = metafunc.config.getoption("package_type")
    distro_name = metafunc.config.getoption("distro_name")
    metafunc.parametrize(
        ["package_type", "distro_name"], [[package_type, distro_name]], indirect=True
    )


def get_system_information():
    release_files = list(pl.Path("/etc").glob("*-release"))
    if release_files:
        release_info = release_files[0].read_text()
    else:
        release_info = "unknown"

    passwd_path = pl.Path("/etc/passwd")

    return f"""===========================
System information
===========================

uname -a
{os.uname()}

/etc/*-release: 
{release_info}

/etc/passwd: 
{passwd_path.read_text()}

user id: 
{os.getuid()}
==========================="""


def _get_agent_version():
    # Verify version of the installed package.
    version_output = (
        subprocess.check_output(["scalyr-agent-2", "version"]).decode().strip()
    )

    return re.search(
        r"The Scalyr Agent 2 version is (\d+\.\d+\.\d+)", version_output
    ).group(1)


def _get_agent_status() -> str:
    output = (
        subprocess.check_output(["scalyr-agent-2", "status", "-v"]).decode().strip()
    )

    return output


def _get_agent_status_json() -> dict:
    """
    Get agent status in json format.
    """
    output = (
        subprocess.check_output(["scalyr-agent-2", "status", "-v", "--format", "json"])
        .decode()
        .strip()
    )

    return json.loads(output)


def _wait_for_good_health_check():
    while True:
        status = _get_agent_status_json()
        pprint.pprint(status)
        time.sleep(1)


def _wait_for_agent_requests_stats(agent_log_path: pl.Path):
    while not check_requests_stats_in_agent_log(content=agent_log_path.read_text()):
        time.sleep(1)


def _start_agent():
    subprocess.check_call(["scalyr-agent-2", "start"])


def _start_and_wait_agent():
    _start_agent()

    log.info("Waiting for the agent to start...")

    while True:
        try:
            _get_agent_status_json()
        except subprocess.CalledProcessError as e:
            if e.stdout.decode().strip() == "The agent does not appear to be running.":
                time.sleep(0.1)
                continue
            raise
        else:
            break


def _verify_package_files_ownership(package_type: str, package_path: pl.Path):
    """
        # Verify the permissions and file ownership inside the archive. Keep in mind that until we comment
    # out fpm flag in build_package.py, permissions won't be correct since they are fixed as part of
    # postinst step, but file ownership should be 0:0 aka owned by root:root
    """
    if package_type == "rpm":
        files_permissions = (
            subprocess.check_output(["rpm", "-qplv", str(package_path)])
            .decode()
            .strip()
            .splitlines()
        )

        found = [p for p in files_permissions if "agent.json" in p]

        assert len(found) == 1

        agent_config_stats_str = found[0]
        log.info(agent_config_stats_str)

        agent_config_stats = re.split(r"\s+", agent_config_stats_str)
        assert (
            agent_config_stats[2] == "root" and agent_config_stats[3] == "root"
        ), "Owner of the file is not root:root!"
        return

    raise AssertionError(f"Unknown package type {package_type}.")


def _verify_agent_status(package_version: str):

    log.info("Verifying agent status output")
    # Verify text status
    string_status = _get_agent_status()

    assert package_version in string_status
    assert "agent.log" in string_status
    assert "linux_system_metrics" in string_status
    assert "linux_process_metrics" in string_status

    # Verify json status
    status = _get_agent_status_json()
    assert package_version == status["version"]


def _verify_logs(
    upload_test_log_path: pl.Path,
    scalyr_api_read_key: str,
    scalyr_server: str,
    full_server_host: str,
    agent_paths: AgentPaths,
):
    log.info("Write test log file messages.")
    start_time = time.time()
    write_messages_to_test_log(log_file_path=upload_test_log_path)

    content = agent_paths.agent_log_path.read_text()

    # Verify agent start up line
    assert "Starting scalyr agent" in content
    # Ensure CA validation is not disabled with default install
    assert "sslverifyoff" not in content
    assert "Server certificate validation has been disabled" not in content

    check_agent_log_for_errors(content=content)

    log.info("Wait for agent log requests stats.")
    while not check_requests_stats_in_agent_log(
        content=agent_paths.agent_log_path.read_text()
    ):
        time.sleep(1)

    verify_test_log_file_upload(
        log_file_path=upload_test_log_path,
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        full_server_host=full_server_host,
        start_time=start_time,
    )


def _verify_system_after_installation(package_type: str, agent_paths: AgentPaths):
    log.info("Verifying install_info.json file exists")
    install_info_path = agent_paths.install_root / "bin/scalyr_agent/install_info.json"
    assert install_info_path.is_file()

    if package_type in ["rpm"]:
        log.info("Verifying rc.d symlinks exist")
        found = list(pl.Path("/etc").glob("rc*.d/*scalyr-agent-2*"))
        assert len(found) == 7

    # Verify agent.json is not readable by others
    log.info("Verifying agent.json and agent.d permissions")

    # NOTE: This check needs to be performed as early as possible after fresh installation before
    # other tools modify the config

    agent_config_permissions = oct(agent_paths.agent_config_path.stat().st_mode)
    agent_config_permissions_str = str(agent_config_permissions)[-3:]

    assert (
        agent_config_permissions_str == "640"
    ), f"Expected 640 permissions for agent.json, got {agent_config_permissions_str}."

    agent_d_permissions = oct(agent_paths.agent_d_path.stat().st_mode)
    agent_d_permissions_str = str(agent_d_permissions)[-3:]

    assert agent_d_permissions_str in [
        "741",
        "751",
    ], f"Expected 741/751 permissions for agent.d, got ${agent_d_permissions_str}."


def _restart_agent(agent_paths: AgentPaths):
    log.info("Restarting agent")
    _stop_agent(agent_paths=agent_paths)

    _start_and_wait_agent()


def _restart_agent_and_remove_logs(agent_paths: AgentPaths):
    log.info("Restarting agent...")
    _stop_agent(agent_paths=agent_paths)

    # Clear log files.
    agent_paths.agent_log_path.unlink()
    _start_and_wait_agent()

    log.info("Agent restarted")


def _stop_agent(agent_paths: AgentPaths):
    log.info("Stopping the agent...")
    subprocess.check_call(["scalyr-agent-2", "stop"])

    assert (
        not agent_paths.pid_file.exists()
    ), "Agent has to be stopped, but its PID file still exists."
    log.info("    The agent has stopped")


def _write_config(config: dict, agent_paths: AgentPaths):
    agent_paths.agent_config_path.write_text(json.dumps(config))


def _perform_ssl_checks(
    scalyr_api_key: str,
    test_configs_path: pl.Path,
    bad_cert_path: pl.Path,
    agent_paths: AgentPaths,
):
    # Test MITM attack - agent should fail to connect and start up with invalid hostname
    log.info("Performing certificate validation and MITM checks")

    log.info("Performing invalid ca_cert_path config option checks")

    original_config_content = agent_paths.agent_config_path.read_text()

    def use_config(test_config_name: str):
        test_config_path = test_configs_path / test_config_name
        agent_paths.agent_config_path.write_text(
            test_config_path.read_text().replace("REPLACE_THIS", scalyr_api_key)
        )

    use_config(test_config_name="agent.json_invalid_ca_cert_path_linux")

    _start_agent()

    log.info("Verifying agent status output")

    with pytest.raises(subprocess.CalledProcessError) as err_info:
        _get_agent_status()

    assert (
        err_info.value.returncode == 1
    ), "scalyr-agent-2 status -v command should have exited with 1 exit code"

    assert "The agent does not appear to be running" in err_info.value.stdout.decode()

    log.info("Verifying agent.log")

    log_content = agent_paths.agent_log_path.read_text()
    assert "ca_cert_path: /tmp/invalid/ca_certs.crt" in log_content
    assert "failedAgentMain" in log_content
    assert (
        'Invalid path "/tmp/invalid/ca_certs.crt" specified for the "ca_cert_path"'
        in log_content
    )

    # 2. Configure agent to use system CA bundle to verify the server cert and verify it works
    log.info("Performing system CA bundle checks")

    debian_ca_bundle_path = pl.Path("/etc/ssl/certs/ca-certificates.crt")
    fedora_ca_bundle_path = pl.Path("/etc/ssl/certs/ca-bundle.crt")

    # Determine distribution specific CA path.
    if debian_ca_bundle_path.exists():
        system_ca_bundle_path = debian_ca_bundle_path
    elif fedora_ca_bundle_path.exists():
        system_ca_bundle_path = fedora_ca_bundle_path
    else:
        raise FileNotFoundError("No system CA bundle found.")

    # NOTE: We create a symlink so we can re-use config with a fixed value for ca_cert_path
    log.info(f"Using system ca bundle: {system_ca_bundle_path}")

    pl.Path("/etc/ssl/system-ca-bundle.crt").symlink_to(system_ca_bundle_path)
    use_config(test_config_name="agent.json_system_ca_bundle")

    _restart_agent_and_remove_logs(agent_paths=agent_paths)

    log.info("Verifying agent.log")

    log_content = agent_paths.agent_log_path.read_text()

    assert "ca_cert_path: /etc/ssl/system-ca-bundle.crt" in log_content

    log.info("Looking for log message with connection info...")
    while "HttpConnection uses native os ssl" not in log_content:
        time.sleep(1)
        log_content = agent_paths.agent_log_path.read_text()

    log.info("Verifying agent status output")
    status = _get_agent_status()
    assert "Last successful communication with Scalyr: " in status
    assert "Last copy response status:                 success" in status

    # 3. Mimic MITM attack by pointing a random domain to agent.scalyr.com and verify hostname
    # check post SSL handshake and cert validation fails
    log.info("Performing MITM and hostname verification checks")

    # NOTE: Dig may not be available on all the distros by defualt
    getent_output = (
        subprocess.check_output(
            ["getent", "hosts", "agent.scalyr.com"],
        )
        .decode()
        .strip()
    )

    getent_last_line = getent_output.splitlines()[-1]
    agent_scalyr_com_ip, *_ = re.split(r"\s+", getent_last_line)

    mock_host = "invalid.mitm.should.fail.test.agent.scalyr.com"
    etc_hosts_entry = f"{agent_scalyr_com_ip} {mock_host}"

    log.info(f"Using agent.scalyr.com IP: {agent_scalyr_com_ip}")

    # Add mock /etc/hosts entry and agent config scalyr_server entry
    etc_hosts_path = pl.Path("/etc/hosts")
    etc_host_backup = etc_hosts_path.read_text()
    with etc_hosts_path.open("a") as f:
        f.write(etc_hosts_entry)
        f.write("\n")

    use_config(test_config_name="agent.json_invalid_host_mitm")
    _restart_agent_and_remove_logs(agent_paths=agent_paths)

    log.info("Verifying agent status output")

    status = _get_agent_status()
    assert "Last successful communication with Scalyr: Never" in status
    assert "Bytes uploaded successfully:               0" in status
    assert "Last copy response size:                   0" in status
    assert (
        "Last copy response status:                 client/connectionFailedCertHostnameValidationFailed"
        in status
    )

    log.info("Verifying agent logs")

    log_content = agent_paths.agent_log_path.read_text()
    assert "Failed to connect to" in log_content
    assert f'Failed to connect to "https://{mock_host}:443"' in log_content
    assert "because of server certificate validation error" in log_content
    assert "This likely indicates a MITM attack" in log_content

    # Clean up at the end.
    etc_hosts_path.write_text(etc_host_backup)

    # 4. Verify that CA validation fail if we connection to a server with certificate issues by CA
    # which we don't trust (or vice versa)
    log.info("Performing cert signed by CA we dont trust checks")

    use_config(test_config_name="agent.json_invalid_bad_cert")
    # NOTE: This test relies on this ca_certs.crt file which contains CA cert for Scalyr cert ca which
    # is not used by example.com

    shutil.copy2(bad_cert_path, "/tmp/ca_certs.crt")

    _restart_agent_and_remove_logs(agent_paths=agent_paths)

    log.info("Verifying agent status output")

    status = _get_agent_status()
    assert "Last successful communication with Scalyr: Never" in status
    assert "Bytes uploaded successfully:               0" in status
    assert "Last copy request size:                    0" in status
    assert "Last copy response size:                   0" in status
    assert (
        "Last copy response status:                 client/connectionFailedSSLError"
        in status
    )

    log_content = agent_paths.agent_log_path.read_text()
    log.info("Verifying agent logs")

    assert "Failed to connect to" in log_content
    assert 'Failed to connect to "https://example.com:443"' in log_content
    assert "due to some SSL error" in log_content
    assert "certificate verify failed" in log_content

    # Clear
    agent_paths.agent_log_path.unlink()

    # Return back normal config
    agent_paths.agent_config_path.write_text(original_config_content)


def test(
    scalyr_api_key,
    scalyr_api_read_key,
    test_session_id,
    scalyr_server,
    agent_test_configs_path,
    bad_cert_path,
    previous_package_version: str,
    package_version: str,
    distro_name: str,
    package_type,
    package_path,
    agent_paths,
    install_package,
    upgrade_package,
    downgrade_package,
    uninstall_package,
):
    log.info(f" Checking {package_path.name} package file ownership")
    _verify_package_files_ownership(
        package_type=package_type, package_path=package_path
    )

    # First install the current version of the package to test out the "fresh" installation process.
    install_package()

    _verify_system_after_installation(
        package_type=package_type, agent_paths=agent_paths
    )

    assert _get_agent_version() == package_version, (
        "Version of the installed agent does not match with the target " "version."
    )

    upload_test_log_path = agent_paths.logs_dir / "test.log"

    config = {
        "api_key": scalyr_api_key,
        "server_attributes": {"serverHost": test_session_id},
        "logs": [{"path": str(upload_test_log_path), "attributes": {"parser": "json"}}],
    }

    _write_config(config=config, agent_paths=agent_paths)

    _start_and_wait_agent()

    _verify_agent_status(package_version=package_version)

    log.info("Verify installed agent logs.")
    _verify_logs(
        upload_test_log_path=upload_test_log_path,
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        full_server_host=test_session_id,
        agent_paths=agent_paths,
    )

    _stop_agent(agent_paths=agent_paths)

    # Verify agent log once more to check that there's no errors on agent's shutdown.
    check_agent_log_for_errors(content=agent_paths.agent_log_path.read_text())

    log.info("Clear agent logs...")
    agent_paths.agent_log_path.unlink()

    _perform_ssl_checks(
        scalyr_api_key=scalyr_api_key,
        test_configs_path=agent_test_configs_path,
        bad_cert_path=bad_cert_path,
        agent_paths=agent_paths,
    )

    log.info("Verify --systemd-managed flag")

    log.info(f"Downgrade agent to the previous version {previous_package_version}")
    downgrade_package(version=previous_package_version)

    assert (
        _get_agent_version() == previous_package_version
    ), "Version of the downgraded agent does not match"

    # We don't check much for a previous version of the packages, since we can not be sure about braking changes
    # that may affect it.
    _start_and_wait_agent()
    _verify_agent_status(package_version=previous_package_version)
    _stop_agent(agent_paths=agent_paths)

    log.info("Clear agent logs...")
    agent_paths.agent_log_path.unlink()

    log.info("Upgrade to a current version of the package to test the upgrade logic.")
    upgrade_package()

    _verify_system_after_installation(
        package_type=package_type, agent_paths=agent_paths
    )

    assert _get_agent_version() == package_version, (
        "Version of the upgraded agent does not match with the target " "version."
    )
    _start_and_wait_agent()

    _verify_agent_status(package_version=package_version)

    log.info("Verify upgraded agent logs.")
    _verify_logs(
        upload_test_log_path=upload_test_log_path,
        scalyr_api_read_key=scalyr_api_read_key,
        scalyr_server=scalyr_server,
        full_server_host=test_session_id,
        agent_paths=agent_paths,
    )
