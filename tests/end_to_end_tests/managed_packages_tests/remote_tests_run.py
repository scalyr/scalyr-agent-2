import pathlib as pl
import subprocess


def run_test_in_docker(
        test_runner_path: pl.Path
):

    subprocess.check_call([
        "docker",
        "run",
        "-i",
        "-v",
        f"{test_runner_path}:/test_runner",
        "ubuntu:22.04",
        "/test_runner"
    ])