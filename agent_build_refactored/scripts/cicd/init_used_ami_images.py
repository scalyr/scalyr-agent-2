import logging
import sys
import pathlib as pl

# Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.aws.boto3_tools import AWSSettings
from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.common import init_logging
from agent_build_refactored.tools.docker.buildx.remote_builder.remote_builder_ami_image import get_remote_docker_ami_image

init_logging()

logger = logging.getLogger(__name__)


def main():
    aws_settings = AWSSettings.create_from_env()

    boto3_session = aws_settings.create_boto3_session()

    logger.info(
        "Init AMI images that are required by next cicd workflows. "
        "It may take some time to populate new images, if needed"
    )
    for arch in [CpuArch.x86_64, CpuArch.AARCH64]:
        get_remote_docker_ami_image(
            architecture=arch,
            boto3_session=boto3_session,
            aws_settings=aws_settings,
        )


if __name__ == '__main__':
    main()