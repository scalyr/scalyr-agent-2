#!/usr/bin/env python3

import pathlib
import pathlib as pl
import argparse
from textwrap import dedent
import subprocess
import json
import time
import os
import tarfile
import re


def run_command(command):
    subprocess.check_call(command, shell=True)


def install_deb_package():
    env = os.environ.copy()
    #original_ld_lib_path = os.environ['LD_LIBRARY_PATH']
    #env["LD_LIBRARY_PATH"] = f"/lib/x86_64-linux-gnu:{original_ld_lib_path}"
    os.environ["LD_LIBRARY_PATH"] = f'/lib/x86_64-linux-gnu:{os.environ["LD_LIBRARY_PATH"]}'
    subprocess.check_call(
        f"dpkg -i {package_path}",
        env=os.environ,
        shell=True
    )


def install_rpm_package():
    #env = os.environ.copy()
    #env["LD_LIBRARY_PATH"] = f"/libx64"
    os.environ["LD_LIBRARY_PATH"] = "/libx64"
    subprocess.check_call(
        f"rpm -i {package_path}",
        env=os.environ,
        shell=True
    )


def install_tarball():
    tar = tarfile.open(package_path)
    tar.extractall(pathlib.Path("~").expanduser())
    tar.close()

def install_msi_package():
    subprocess.check_call(
        #f"Start-Process msiexec.exe -Wait -ArgumentList '/I {package_path} /quiet'", shell=True
        f"msiexec.exe /I {package_path} /quiet", shell=True
    )




def install_package(package_type: str):
    if package_type == "deb":
        install_deb_package()
    elif package_type == "rpm":
        install_rpm_package()
    elif package_type == "tar":
        install_tarball()
    elif package_type == "msi":
        install_msi_package()


def determine_version():
    if package_type in ["deb", "rpm"]:
        pass
    elif package_type == "tar":
        m = re.search(r"scalyr-agent-(\d+\.\d+\.\d+)", package_path.name)
        return m.group(1)


def start_agent():
    if package_type in ["deb", "rpm", "msi"]:

        if package_type == "msi":
            # Add agent binaries to the PATH env. variable on windows.
            bin_path = pl.Path(os.environ['programfiles(x86)'], "Scalyr", "bin")
            os.environ["PATH"] = f"{bin_path};{os.environ['PATH']}"

        subprocess.check_call(
            f"scalyr-agent-2 start", shell=True, env=os.environ
        )
    elif package_type == "tar":
        tarball_dir = list(pl.Path("~").expanduser().glob("scalyr-agent-*.*.*"))[0]

        subprocess.check_call(
            f"{tarball_dir}/bin/scalyr-agent-2 start", shell=True
        )


def get_agent_status():
    if package_type in ["deb", "rpm", "msi"]:
        subprocess.check_call(
            f"scalyr-agent-2 status -v", shell=True
        )
    elif package_type == "tar":
        tarball_dir = list(pl.Path("~").expanduser().glob("scalyr-agent-*.*.*"))[0]

        subprocess.check_call(
            f"{tarball_dir}/bin/scalyr-agent-2 status -v", shell=True,
        )


def stop_agent():
    if package_type in ["deb", "rpm", "msi"]:
        subprocess.check_call(
            f"scalyr-agent-2 stop", shell=True
        )
    if package_type == "tar":
        tarball_dir = list(pl.Path("~").expanduser().glob("scalyr-agent-*.*.*"))[0]

        subprocess.check_call(
            f"{tarball_dir}/bin/scalyr-agent-2 stop", shell=True
        )


def configure_agent(api_key: str):
    if package_type in ["deb", "rpm"]:
        config_path = pathlib.Path(AGENT_CONFIG_PATH)
    elif package_type == "tar":
        version = determine_version()

        config_path = pl.Path("~").expanduser() / f"scalyr-agent-{version}" / "config" / "agent.json"
    elif package_type == "msi":
        config_path = pl.Path(os.environ["programfiles(x86)"], "Scalyr", "config", "agent.json")

    config = {}
    #api_key = "0v7dW1EIPpglMcSjGywUdgY9xTNWQP/kas6qHEmiUG5w-"
    config["api_key"] = api_key

    config["server_attributes"] = {"serverHost": "ARTHUR_TEST"}
    config["implicit_metric_monitor"] = False
    config["verify_server_certificate"] = False
    config_path.write_text(json.dumps(config))


def remove_deb_package():
    #env = os.environ.copy()
    #original_ld_lib_path = os.environ['LD_LIBRARY_PATH']
    #env["LD_LIBRARY_PATH"] = f"/lib/x86_64-linux-gnu:{original_ld_lib_path}"
    subprocess.check_call(
        f"apt-get remove -y scalyr-agent-2",
        #env=env,
        shell=True
    )


def remove_rpm_package():
    #env = os.environ.copy()
    #env["LD_LIBRARY_PATH"] = f"/libx64"
    subprocess.check_call(
        f"yum remove -y scalyr-agent-2",
        #env=env,
        shell=True
    )


def remove_package(package_type: str):
    if package_type == "deb":
        remove_deb_package()
    elif package_type == "rpm":
        remove_rpm_package()


AGENT_CONFIG_PATH ="/etc/scalyr-agent-2/agent.json"


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--package-path",
        type=str,
        required=True
    )

    parser.add_argument("--scalyr-api-key", required=True)

    args = parser.parse_args()

    package_path = pl.Path(args.package_path)

    scalyr_api_key = args.scalyr_api_key

    if not package_path.exists():
        print("No package.")
        exit(1)

    if package_path.name.endswith(".deb"):
        package_type = "deb"
    elif package_path.name.endswith(".rpm"):
        package_type = "rpm"
    elif package_path.name.endswith("tar.gz"):
        package_type = "tar"
    elif package_path.name.endswith(".msi"):
        package_type = "msi"
    else:
        raise ValueError("Unknown package format.")

    install_package(package_type)

    configure_agent(args.scalyr_api_key)

    start_agent()

    time.sleep(2)

    get_agent_status()

    time.sleep(2)

    stop_agent()

    remove_package(package_type)








