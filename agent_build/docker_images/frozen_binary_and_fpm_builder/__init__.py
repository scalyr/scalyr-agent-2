import pathlib as pl

from agent_build.docker_images import image_builder

PARENT_DIR = pl.Path(__file__).parent
SOURCE_ROOT = PARENT_DIR.parent.parent.parent

FROZEN_BINARY_AND_FPM_BUILDER = image_builder.ImageBuilder(
    image_name=PARENT_DIR.name,
    source_dir=SOURCE_ROOT,
    dockerfile_path=PARENT_DIR / "Dockerfile"
)