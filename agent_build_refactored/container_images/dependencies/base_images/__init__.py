import pathlib as pl
import re

_PARENT_DIR = pl.Path(__file__).parent


def _read_image_name_from_dockerfile(dockerfile_path: pl.Path):
    m = re.match(
        f"FROM\s+([^\n]+)", dockerfile_path.read_text()
    )

    if not m:
        raise Exception(f"Can not read base image name from the dockerfile {dockerfile_path}.")

    image_name = m.group(1)
    return image_name


UBUNTU_BASE_IMAGE = _read_image_name_from_dockerfile(
    dockerfile_path=_PARENT_DIR / "ubuntu.Dockerfile"
)


ALPINE_BASE_IMAGE = _read_image_name_from_dockerfile(
    dockerfile_path=_PARENT_DIR / "alpine.Dockerfile"
)