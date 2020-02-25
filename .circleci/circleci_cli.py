#!/usr/bin/env python
# This script is convenient to run circlici job on lical macine.
# What this script does:
# - converts config to 2.0 version because CircleCi CLI does not support config version higher than 2.0.
# - set root user for all jobs with 'setup_remote_docker',
#   because 'circleci' does not have permisions to run docker commands.
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
import yaml


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


if __name__ == "__main__":
    circleci_dir = os.path.dirname(os.path.abspath(__file__))
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
