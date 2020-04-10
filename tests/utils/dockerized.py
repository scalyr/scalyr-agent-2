from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import tarfile
import os

import six
import docker

from tests.utils.compat import Path

from scalyr_agent import compat

DEFAULT_FILE_PATHS_TO_COPY = [
    "/var/log/scalyr-agent-2/agent.log",
    "/root/scalyr-agent-dev/log/agent.log",
]


def dockerized_case(
    builder_cls,
    file_path,
    file_paths_to_copy=None,
    artifacts_use_subdirectory=True,
    remove_container=True,
    python_executable="python3",
):
    """
    Decorator that makes decorated test case run inside docker container.

    :param builder_cls: Image builder class to use.
    :param file_path: Path to the test file.
    :param file_paths_to_copy: A list of file paths to copy from the container to the artifacts
                               directory specified --artifacts-path option.
    :param artifacts_use_subdirectory: True to store artifacts in a subdirectory which matches the
                                       test name. This comes handy in scenarios where single test
                                       file contains multiple test functions.
    :param remove_container: True to remove container after run.
    :param python_executable: Python executable to use to run tests with (aka pytest).
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
            skip_requirements = request.config.getoption(
                "--skip-builder-requirements", False
            )

            builder.build(skip_requirements=skip_requirements)

            docker_client = docker.from_env()

            print("Create container from '{0}' image.".format(builder.image_tag))
            container = docker_client.containers.run(
                builder.image_tag,
                detach=True,
                command=command,
                stdout=True,
                stderr=True,
                environment=get_environment_for_docker_run(),
            )

            exit_code = container.wait()["StatusCode"]

            logs = six.ensure_text(container.logs(follow=True))
            print(logs)

            # save logs if artifacts path is specified.
            artifacts_path = request.config.getoption("--artifacts-path", None)

            if artifacts_path:
                coverage_file_path = Path("/", ".coverage")
                artifacts_path = Path(artifacts_path)

                if artifacts_use_subdirectory:
                    # We run each test case in a new container instance so we make sure we store
                    # logs under a sub-directory which matches the test function name
                    artifacts_path = artifacts_path / func_name

                file_paths_to_copy.add(six.text_type(coverage_file_path))

                copy_artifacts(
                    container=container,
                    file_paths=file_paths_to_copy,
                    destination_path=artifacts_path,
                )

            if remove_container:
                container.remove()
                print("Container '{0}' removed.".format(builder.image_tag))

            # raise failed assertion, due to non-zero result from container.
            if exit_code:
                raise AssertionError("Test case inside container failed.")

        return wrapper

    return dockerized_real


def copy_artifacts(container, file_paths, destination_path):
    """
    Copy provided file paths from Docker container to a destination on a host.

    :param container: Container instance to use.
    :param file_paths: A list of file paths inside the Docker container to copy over.
    :param destination_path: Destination directory on the host where the files should be copied to.
    """
    if not file_paths:
        return

    try:
        os.makedirs(destination_path)
    except OSError:
        pass

    for file_path in file_paths:
        # fetch file as tar file stream if it exists
        try:
            stream, _ = container.get_archive(file_path)
        except docker.errors.NotFound as e:
            # Not all the test files produce agent.log so we simply ignore the error
            # if agent log file doesn't exist
            msg = str(e).lower()

            if "could not find the file" in msg:
                print("File path %s doesn't exist, skipping copy" % (file_path))
                continue

            raise e

        print('Copying file path "%s" to "%s"' % (file_path, destination_path))

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


def get_environment_for_docker_run():
    """
    Return sanitized environment to be used with containers.run() command.

    The returned environment excludes any environment variables which could effect tests
    and cause a failure.
    """
    env_vars_to_delete = ["PATH", "HOME"]

    environment = compat.os_environ_unicode.copy()

    for env_var in env_vars_to_delete:
        if env_var in environment:
            del environment[env_var]

    return environment
