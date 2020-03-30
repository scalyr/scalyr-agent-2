from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import tarfile
import os

import six
import docker

from tests.utils.compat import Path

from scalyr_agent import compat

DEFAULT_FILE_PATHS_TO_COPY = ["/var/log/scalyr-agent-2/agent.log"]


def dockerized_case(builder_cls, file_path, file_paths_to_copy=None, python_executable="python3"):
    """
    Decorator that makes decorated test case run inside docker container.

    :param file_paths_to_copy: A list of file paths to copy from the container to the artifacts
                               directory specified --artifacts-path option.
    """
    # We always include agent log file
    file_paths_to_copy = set(file_paths_to_copy or [])
    file_paths_to_copy.update(set(DEFAULT_FILE_PATHS_TO_COPY))

    def dockerized_real(f):
        func_name = f.__name__
        root = Path(__file__).parent.parent.parent
        rel_path = Path("agent_source") / Path(file_path).relative_to(root)

        command = "{0} -m pytest {1}::{2} -s --color=yes --no-dockerize".format(
            python_executable, rel_path, func_name
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

            print("Create container from '{0}' image.".format(builder.image_tag))
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
                    for file_path in file_paths_to_copy:
                        # fetch file as tar file stream if it exists

                        try:
                            stream, _ = container.get_archive(file_path)
                        except docker.errors.NotFound as e:
                            # Not all the test files produce agent.log so we simply ignore the error
                            # if agent log file doesn't exist
                            msg = str(e).lower()

                            if "could not find the file" in msg:
                                print(
                                    "File path %s doesn't exist, skipping copy"
                                    % (file_path)
                                )
                                continue

                            raise e

                        # We run each test case in a new container instance so we make sure we store
                        # logs under a sub-directory which matches the test function name
                        destination_path = artifacts_path / func_name

                        try:
                            os.makedirs(destination_path)
                        except OSError:
                            pass

                        print(
                            'Copying file path "%s" to "%s"'
                            % (file_path, destination_path)
                        )

                        data_tar_path = destination_path / "data.tar"
                        # write it to file.
                        with data_tar_path.open("wb") as data_fp:
                            for b in stream:
                                data_fp.write(b)

                        # extract tar file in a directory for this function
                        with tarfile.open(data_tar_path) as tar_file:
                            tar_file.extractall(destination_path)

                        # remove tar file.
                        os.remove(data_tar_path)

            container.remove()
            print("Container '{0}' removed.".format(builder.image_tag))

            # raise failed assertion, due to non-zero result from container.
            if exit_code:
                raise AssertionError("Test case inside container failed.")

        return wrapper

    return dockerized_real
