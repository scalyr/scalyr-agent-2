import abc
import atexit
import dataclasses
import logging
import subprocess
from typing import Dict


logger = logging.getLogger(__name__)

BUILDKIT_VERSION = "v0.11.6"

_existing_builders: Dict[str, 'BuildxBuilderWrapper'] = {}


class BuildxBuilderWrapper:
    def __init__(
        self,
        name: str
    ):

        self.name = name

    @classmethod
    def create(cls, *args, **kwargs):
        instance = cls(*args, **kwargs)

        if instance.name in _existing_builders:
            return _existing_builders[instance.name]

        _existing_builders[instance.name] = instance
        instance.initialize()
        return instance

    @abc.abstractmethod
    def initialize(self):
        pass

    def close(self):
        try:
            subprocess.run(
                [
                    "docker",
                    "buildx",
                    "rm",
                    self.name,
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            logger.exception(f"Can not remove docker buildx builder '{self.name}'. Stderr: {e.stderr.decode()}")
            raise


class LocalBuildxBuilderWrapper(BuildxBuilderWrapper):

    def initialize(self):

        result = subprocess.run(
            [
                "docker", "buildx", "ls"
            ],
            check=True,
            capture_output=True
        )
        result_output = result.stdout.decode()

        if self.name in result_output:
            return

        create_builder_args = [
            "docker",
            "buildx",
            "create",
            "--name",
            self.name,
            "--driver",
            "docker-container",
            "--driver-opt",
            f"image=moby/buildkit:{BUILDKIT_VERSION}",
            "--driver-opt",
            "network=host",
            "--bootstrap",

        ]

        try:
            subprocess.run(
                create_builder_args,
                check=True,
                capture_output=True,
            )
        except subprocess.SubprocessError as e:
            logger.exception(f"Can not create buildx builder. Stderr: {e.stderr.decode}")
            raise


def cleanup():
    for builder in _existing_builders.values():
        builder.close()


atexit.register(cleanup)