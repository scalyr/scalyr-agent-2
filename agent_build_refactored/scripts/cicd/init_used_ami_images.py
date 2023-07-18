import logging
import sys
import pathlib as pl

# Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.aws.common import AWSSettings
from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.common import init_logging
from agent_build_refactored.tools.docker.buildx.remote_builder.remote_builder_ami_image import REMOTE_DOCKER_ENGINE_IMAGES

init_logging()

logger = logging.getLogger(__name__)


def main():
    aws_settings = AWSSettings.create_from_env()

    boto3_session = aws_settings.create_boto3_session()
    ec2_client = boto3_session.client("ec2")
    ec2_resource = boto3_session.resource("ec2")

    logger.info(
        "Init AMI images that are required by next cicd workflows. "
        "It may take some time to populate new images, if needed"
    )

    for arch, ami_image in REMOTE_DOCKER_ENGINE_IMAGES.items():
        ami_image.initialize()


if __name__ == '__main__':
    main()