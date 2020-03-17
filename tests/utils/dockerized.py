import docker
import pytest
from pathlib2 import Path


def dockerized_case(builder_cls, file_path):
    """Decorator that makes decorated test case run inside docker container."""
    def dockerized_real(f):
        root = Path(__file__).parent.parent.parent
        rel_path = Path("agent_source") / Path(file_path).relative_to(root)

        command = "python -u -m pytest {0}::{1} -s --no-dockerize".format(
            rel_path,
            f.__name__
        )

        def wrapper(*args, **kwargs):
            no_dockerize = pytest.config.getoption("--no-dockerize")
            if no_dockerize:
                result = f(*args, **kwargs)
                return result

            builder = builder_cls()
            builder.build()

            docker_client = docker.from_env()

            container = docker_client.containers.run(
                builder.image_tag,
                detach=True,
                command=command
            )

            exit_code = container.wait()["StatusCode"]

            logs = container.logs(
            )
            print(logs)
            if exit_code:
                raise AssertionError("Test case inside container failed.")

        return wrapper

    return dockerized_real