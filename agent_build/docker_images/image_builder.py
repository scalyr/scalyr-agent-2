import hashlib
import logging
import pathlib as pl
import subprocess
from typing import Union, Dict, Optional

from agent_build import common

logging.basicConfig(level=logging.INFO)


SOURCE_ROOT = pl.Path(__file__).absolute().parent.parent


class ImageBuilder:
    """
    Simple abstraction to build docker image. It also has the additional methods which should be useful in the CI/CD to
    cache the image for future use.
    """

    def __init__(
            self, image_name: str,
            source_dir: Union[str, pl.Path],
            dockerfile_path: Union[str, pl.Path],
            build_args: Dict[str, str] = None
    ):
        """
        :param image_name: Name of the result image.
        :param source_dir: The path for the image build context.
        :param dockerfile_path: Path to the Dockerfile.
        """
        self._source_dir = pl.Path(source_dir)
        self._dockerfile_path = pl.Path(dockerfile_path)
        self._build_args = build_args or {}

        self._image_name_prefix = image_name
        self._image_name: Optional[str] = None

        self._is_built = False

    @property
    def image_name(self):
        if not self._image_name:
            used_files_checksum_sha256 = common.get_files_sha256_checksum(self.get_used_files())
            used_files_checksum = used_files_checksum_sha256.hexdigest()
            self._image_name = f"{self._image_name_prefix}-{used_files_checksum}"

        return self._image_name

    def get_used_files(self):
        """
        Get list of the paths of the files which are used in the image. This is mostly needed to calculate the checksum
        of those files, so it can be used as a cache key in CI/CD.
        There's no fast way to get the list of the files which are used in the image, so we have to parse the dockerfile
        and look for the 'ADD' and 'COPY' statements.
        """
        used_paths = list()
        for line in self._dockerfile_path.read_text().splitlines():
            # Skip if there is no ADD or COPY command.
            if not line.startswith("ADD ") and not line.startswith("COPY"):
                continue

            # According to the Dockerfile format, the ADD operator support multiple source paths
            # and the last is the destination path.

            # Split the ADD or COPY line.
            add_or_copy_line_parts = line.strip().split(" ")

            # Ignore the multi-stage build COPY operators.
            if add_or_copy_line_parts[0] == "COPY" and add_or_copy_line_parts[1].startswith("--from"):
                continue

            # The first part is the operator itself, and the last the destination path.
            # Everything between - the source files.

            for source_path in add_or_copy_line_parts[1:len(add_or_copy_line_parts) - 1]:
                # Since we know the path for the image's build context, we can resolve the absolute paths.

                used_paths.append(
                    pl.Path(self._source_dir, source_path).absolute()
                )

        # Take into account the dockerfile itself.
        used_paths.append(self._dockerfile_path)
        # and this script
        used_paths.append(pl.Path(__file__))

        # All paths that are used in the image have been determined. But there may be directories, so we also have to
        # take into account files inside them. The easiest way is to just walk through those directories and get all
        # files.
        used_files = []

        def get_dir_files(dir_path: pl.Path):
            if dir_path.name == "__pycache__":
                return []

            result = []
            for child_path in dir_path.iterdir():
                if child_path.is_dir():
                    result.extend(get_dir_files(child_path))
                else:
                    result.append(child_path)

            return result

        for used_path in used_paths:
            # skip if not directory.
            if not used_path.is_dir():
                used_files.append(used_path)
                continue

            used_files.extend(get_dir_files(used_path))

        return used_files

    def _build(self, image_name: str):
        """
        Build the docker image.
        """
        # Before the build, check if there is already an image with the same name. The name contains a checksum of all
        # content of the image, so the image name has to be the same if content is also the same..
        # If so, skip the build.
        output = subprocess.check_output(
            f"docker images -q {image_name}", shell=True
        ).decode().strip()

        if output:
            # The image already exists, skip the build.
            return

        # Add build args.
        if self._build_args:
            build_args = ""
            for arg_name, arg in self._build_args.items():
                build_args = f'{build_args} --build-arg {arg_name}="{arg}"'
        else:
            build_args = ""

        subprocess.check_call(
            f"docker build -t {image_name} -f {self._dockerfile_path} {build_args} {self._source_dir}",
            shell=True
        )

        self._is_built = True
        logging.info(f"The image '{image_name}' has been succesfully built.")

    def build(self, cache_dir: Union[str, pl.Path] = None):
        """
        Build the docker image or re-using the existing one by loading it from the cached tar file.
        :param cache_dir: If not None, the path to folder where to search for the cached image tar file.
        The build will be skipped and the image will be re-used.
        """

        logging.info(f"Start building the image '{self.image_name}'")

        if cache_dir:
            cache_dir = pl.Path(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            image_tar_file_name = cache_dir / f"{self.image_name}.tar"
            if not image_tar_file_name.exists():
                logging.info(f"Can't find cached file for image '{self.image_name}'. Build a new one...")
                self._build(self.image_name)
                logging.info(f"Save image '{self.image_name}' into file '{image_tar_file_name}'")
                subprocess.check_call(
                    f"docker save {self.image_name} > {image_tar_file_name}",
                    shell=True
                )
            else:
                logging.info(
                    f"The cached file '{image_tar_file_name}' for the image '{self.image_name}' is found. Reusing it..."
                )
                subprocess.check_call(
                    f"docker load -i {image_tar_file_name}",
                    shell=True
                )
        else:
            self._build(self.image_name)

    def save_artifacts(self, paths: Dict[str, Union[str, pl.Path]]):

        # Create the container from the image to be able to copy files from it.
        container_id = subprocess.check_output(
            f"docker create {self.image_name}", shell=True
        ).decode().strip()

        # Save needed files.
        for container_path, host_path in paths.items():
            subprocess.check_call(
                f"docker cp -a {container_id}:{container_path}/. {str(host_path)}", shell=True
            )

        # Remove the container
        subprocess.check_call(
            f"docker rm -f {container_id}", shell=True
        )
