from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import tarfile
import os

import six
import docker

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

        def wrapper(request, *args, **kwargs):
            no_dockerize = request.config.getoption("--no-dockerize")
            if no_dockerize:
                result = f(request, *args, **kwargs)
                return result

            builder = builder_cls()
            use_cache_path = request.config.getoption("--image-cache-path", None)

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

            logs = six.ensure_text(container.logs(follow=True))
            print(logs)

            # save logs if artifacts path is specified.
            artifacts_path = request.config.getoption("--artifacts-path", None)
            if artifacts_path is not None:
                artifacts_path = Path(artifacts_path)
                if artifacts_path.exists():
                    # fetch log as tar file stream if it exists
                    agent_log_file_exists = True

                    try:
                        stream, _ = container.get_archive(
                            "/var/log/scalyr-agent-2/agent.log"
                        )
                    except docker.errors.NotFound as e:
                        # Not all the test files produce agent.log so we simply ignore the error
                        # if agent log file doesn't exist
                        msg = str(e).lower()

                        if "could not find the file" in msg:
                            agent_log_file_exists = False
                            return

                        raise e

                    if agent_log_file_exists:
                        agent_log_tar_path = artifacts_path / "agent.tar"
                        # write it to file.
                        with agent_log_tar_path.open("wb") as agent_file:
                            for b in stream:
                                agent_file.write(b)
                        # extract tar file.
                        with tarfile.open(agent_log_tar_path) as tar_file:
                            tar_file.extractall(artifacts_path)
                        # remove tar file.
                        os.remove(agent_log_tar_path)
                    else:
                        print("Agent log file doesn't exist, skipping copy.")

            # raise failed assertion, due to non-zero result from container.
            if exit_code:
                raise AssertionError("Test case inside container failed.")

        return wrapper

    return dockerized_real
