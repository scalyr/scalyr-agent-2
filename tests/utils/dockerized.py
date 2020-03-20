from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import tarfile
import os

import docker
import pytest

from tests.utils.compat import Path

from scalyr_agent import compat


def dockerized_case(builder_cls, file_path):
    """Decorator that makes decorated test case run inside docker container."""

    def dockerized_real(f):
        root = Path(__file__).parent.parent.parent
        rel_path = Path("agent_source") / Path(file_path).relative_to(root)

        command = "python3 -u -m pytest {0}::{1} -s --no-dockerize".format(
            rel_path, f.__name__
        )

        def wrapper(*args, **kwargs):
            no_dockerize = pytest.config.getoption(  # pylint: disable=no-member
                "--no-dockerize"
            )  # pylint: disable=no-member
            if no_dockerize:
                result = f(*args, **kwargs)
                return result

            builder = builder_cls()
            use_cache_path = pytest.config.getoption(
                "--image-cache-path", None
            )  # pylint: disable=no-member

            builder.build(image_cache_path=use_cache_path)

            docker_client = docker.from_env()

            container = docker_client.containers.run(
                builder.image_tag,
                detach=True,
                command=command,
                stdout=True,
                stderr=True,
                environment=compat.os_environ_unicode.copy(),
            )

            exit_code = container.wait()["StatusCode"]

            logs = container.logs()
            print(logs)

            # save logs if artifacts path is specified.
            artifacts_path = pytest.config.getoption(
                "--artifacts-path", None
            )  # pylint: disable=no-member
            if artifacts_path is not None:
                artifacts_path = Path(artifacts_path)
                if artifacts_path.exists():
                    stream, _ = container.get_archive(
                        "/var/log/scalyr-agent-2/agent.log"
                    )
                    agent_log_tar_path = artifacts_path / "agent.tar"
                    with agent_log_tar_path.open("wb") as agent_file:
                        for b in stream:
                            agent_file.write(b)
                    with tarfile.open(agent_log_tar_path) as tar_file:
                        tar_file.extractall(artifacts_path)
                    os.remove(agent_log_tar_path)

            if exit_code:
                raise AssertionError("Test case inside container failed.")

        return wrapper

    return dockerized_real
