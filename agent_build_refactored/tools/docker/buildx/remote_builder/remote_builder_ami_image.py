import logging
import pathlib as pl
import hashlib

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.aws.constants import EC2DistroImage
from agent_build_refactored.tools.aws.ami import CICD_AMI_IMAGES_NAME_PREFIX, create_new_ami_image, get_all_cicd_images
from agent_build_refactored.tools.aws.boto3_tools import AWSSettings
from agent_build_refactored.tools.aws.ec2 import EC2InstanceWrapper

logger = logging.getLogger(__name__)

_PARENT_DIR = pl.Path(__file__).parent.absolute()
_DEPLOYMENT_SCRIPT_PATH = _PARENT_DIR / "deploy_docker_in_ec2_instance.sh"

_DOCKER_ENGINE_IMAGE_TAG = "dataset-agent-build-docker-engine"

BASE_IMAGE_AMD64 = EC2DistroImage(
    image_id="ami-053b0d53c279acc90",
    image_name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
    short_name="ubuntu2204_AMD64",
    size_id="t2.small",
    ssh_username="ubuntu",
)

BASE_IMAGE_ARM64 = EC2DistroImage(
    image_id="ami-0a0c8eebcdd6dcbd0",
    image_name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
    short_name="ubuntu2204_ARM",
    size_id="t4g.small",
    ssh_username="ubuntu",
)


BASE_IMAGES = {
    CpuArch.x86_64: BASE_IMAGE_AMD64,
    CpuArch.AARCH64: BASE_IMAGE_ARM64,
}


REMOTE_DOCKER_ENGINE_AMI_CHECKSUMS = {}


def _get_ami_image_checksum(architecture: CpuArch):
    sha256 = hashlib.sha256()

    # calculate checksum of the AMI image, so we can rebuild it if some
    # data of the image has been changed.
    sha256.update(_DEPLOYMENT_SCRIPT_PATH.read_bytes())

    sha256.update(ec2_image.image_id.encode())
    sha256.update(ec2_image.image_name.encode())
    sha256.update(ec2_image.size_id.encode())
    sha256.update(ec2_image.short_name.encode())
    sha256.update(ec2_image.ssh_username.encode())

    checksum = sha256.hexdigest()

    return checksum


for cpu_arch, ec2_image in BASE_IMAGES.items():
    REMOTE_DOCKER_ENGINE_AMI_CHECKSUMS[cpu_arch] = _get_ami_image_checksum(
        architecture=cpu_arch
    )


def get_remote_docker_ami_image(
        architecture: CpuArch,
        boto3_session,
        aws_settings: AWSSettings
):

    base_ec2_image = BASE_IMAGES[architecture]
    checksum = REMOTE_DOCKER_ENGINE_AMI_CHECKSUMS[architecture]
    builder_images = get_all_cicd_images(
        boto3_session=boto3_session,
    )

    for image in builder_images:
        for tag in image.tags:
            if tag["Key"] == "checksum" and tag["Value"] == checksum:
                logger.info(f"Use already existing AMI image with checksum '{checksum}'")
                return image

    # Create new AMI image.
    name = f"{CICD_AMI_IMAGES_NAME_PREFIX}_{architecture.value}_{checksum}"
    logger.info(f"Create new ami image '{name}'")
    instance = EC2InstanceWrapper.create_and_deploy_ec2_instance(
        boto3_session=boto3_session,
        aws_settings=aws_settings,
        name_prefix="remote_docker_ami_base",
        ec2_image=base_ec2_image,
        root_volume_size=32,
        deployment_script=_DEPLOYMENT_SCRIPT_PATH,
    )

    try:
        image = create_new_ami_image(
            boto3_session=boto3_session,
            ec2_instance_id=instance.boto3_instance.id,
            name=name,
            checksum=checksum,
            description="Image with pre-installed docker engine that is used in dataset agent's CI-CD",
        )
    finally:
        instance.terminate()

    return image


