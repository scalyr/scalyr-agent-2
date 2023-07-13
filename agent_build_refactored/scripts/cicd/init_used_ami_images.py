import sys
import pathlib as pl

# Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.aws.boto3_tools import AWSSettings
from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.common import init_logging
from agent_build_refactored.tools.aws.ami import get_buildx_builder_ami_image

init_logging()


def main():
    aws_settings = AWSSettings.create_from_env()

    boto3_session = aws_settings.create_boto3_session()

    for arch in [CpuArch.x86_64, CpuArch.AARCH64, CpuArch.ARMV7]:
        get_buildx_builder_ami_image(
            architecture=arch,
            boto3_session=boto3_session,
            aws_settings=aws_settings,
        )


if __name__ == '__main__':
    main()