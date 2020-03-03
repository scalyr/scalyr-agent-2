#!/usr/bin/env python
# This script is convenient to run circlici job on local machine.
# What this script does:
# - converts config to 2.0 version because CircleCi CLI does not support config version higher than 2.0.
# - set root user for all jobs with 'setup_remote_docker',
#   because 'circleci' user does not have permissions to run docker commands in local mode.
#
# usage: circleci_cli.py <any available options that circleci accepts>
#
# for example: circleci_cli.py local execute --job unittests

from __future__ import print_function
from __future__ import unicode_literals

from __future__ import absolute_import
import subprocess
import os
import shutil
import sys
from io import open
import argparse
import time

import yaml

_script_abs_path = os.path.abspath(__file__)


def set_root_user_for_docker_jobs(path):
    """
    Set user - 'root' for all jobs with 'setup_remote_docker'.
    This is needed because job can not run docker commands without root on with local CLI.
    """
    with open(path, "r") as f:
        config = yaml.safe_load(f)

    for job_name, job in config["jobs"].items():
        if "steps" not in job:
            continue
        for step in job["steps"]:
            if "setup_remote_docker" not in step:
                continue
            for image in job["docker"]:
                image["user"] = "root"

    with open(path, "w") as f:
        yaml.dump(config, f)


def is_smoke_test():  # type: () -> bool
    """
    Return True if  command is - 'local execute --job <name>', and <name> starts with 'smoke'.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("command")

    sub_parsers = parser.add_subparsers()
    command_parser = sub_parsers.add_parser("execute")
    command_parser.add_argument("--job", required=True)

    try:
        args, _ = parser.parse_known_args()
    except:
        return False

    if not args.job.startswith("smoke"):
        return False

    return True


def set_smoke_env_variables_from_config():
    """
    Smoke tests require some environment variables to be able to interact with Scalyr servers.
    Smoke tests provide ability to create 'config.yml' file with agent settings for local testing.
    This function gets those settings and add them as "-e <VAR_NAME>=<VAR_VALUE> to the current circleci command."
    """
    test_config_path = os.path.join(
        os.path.dirname(os.path.dirname(_script_abs_path)), "smoke_tests", "config.yml"
    )

    if not os.path.exists(test_config_path):
        print("Can not find smoke test config file.")
        return

    with open(test_config_path, "r") as f:
        config = yaml.safe_load(f)

    agent_settings = config.get("agent_settings", dict())

    # since 'CIRCLE_BUILD_NUM' env. variable is not set in local builds,
    # add timestamp to 'AGENT_HOST_NAME' env. variable. This variable will be used instead of 'CIRCLE_BUILD_NUM.
    agent_settings["AGENT_HOST_NAME"] = "{0}-{1}".format(
        agent_settings["AGENT_HOST_NAME"], int(time.time())
    )

    # add new '-e <VAR_NAME>=<VAR_VALUE' options to the current command line arguments.
    for k, v in agent_settings.items():
        sys.argv.append("-e")
        sys.argv.append("{0}={1}".format(k, v))


if __name__ == "__main__":

    if is_smoke_test():
        # if smoke test is specified, set env. variables from smoke tests config file.
        # this provides ability to keep only one config file for all kinds of tests(pytest, tox).
        set_smoke_env_variables_from_config()

    circleci_dir = os.path.dirname(_script_abs_path)
    os.chdir(os.path.dirname(circleci_dir))
    config_path = os.path.join(circleci_dir, "config.yml")
    backup_file_path = os.path.join(circleci_dir, "config.yml.backup")

    # restore original config from backup. If backup exists, something went from previous run.
    if os.path.exists(backup_file_path):
        shutil.copy(backup_file_path, config_path)
        os.remove(backup_file_path)

    # create backup for original config.
    shutil.copy(config_path, backup_file_path)

    new_local_config_path = os.path.join(circleci_dir, "config.yml~")

    try:
        # call circleci to create new 2.0 compatible config file.
        with open(new_local_config_path, "wb") as f:
            output = subprocess.check_call(
                ["circleci", "config", "process", config_path], stdout=f
            )

        # set root user for all job with "setup_remote_docker"
        set_root_user_for_docker_jobs(new_local_config_path)

        # replace original config with new.
        shutil.copy(new_local_config_path, config_path)

        # call circleci with command line argument. It will get new compatible config, so it should work well.
        process = subprocess.Popen(
            ["circleci"] + sys.argv[1:], stdout=sys.stdout, stderr=sys.stderr
        )
        process.communicate()
    finally:
        # restore original config from backup.
        shutil.copy(backup_file_path, config_path)
        os.remove(backup_file_path)
        os.remove(new_local_config_path)
