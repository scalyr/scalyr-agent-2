import dataclasses
import logging
import pathlib as pl
import hashlib
from typing import Dict

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.aws.constants import EC2DistroImage
from agent_build_refactored.tools.aws.ami import CICD_AMI_IMAGES_NAME_PREFIX, CustomAMIImage, StockAMIImage
from agent_build_refactored.tools.aws.boto3_tools import AWSSettings
from agent_build_refactored.tools.aws.ec2 import EC2InstanceWrapper

logger = logging.getLogger(__name__)

_PARENT_DIR = pl.Path(__file__).parent.absolute()
_DEPLOYMENT_SCRIPT_PATH = _PARENT_DIR / "deploy_docker_in_ec2_instance.sh"

_DOCKER_ENGINE_IMAGE_TAG = "dataset-agent-build-docker-engine"

BASE_IMAGE_AMD64 = StockAMIImage(
    image_id="ami-053b0d53c279acc90",
    name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
    #size_id="t2.small",
    ssh_username="ubuntu",
)

BASE_IMAGE_ARM64 = StockAMIImage(
    image_id="ami-0a0c8eebcdd6dcbd0",
    name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
    #size_id="t4g.small",
    ssh_username="ubuntu",
)


BASE_IMAGES = {
    CpuArch.x86_64: BASE_IMAGE_AMD64,
    CpuArch.AARCH64: BASE_IMAGE_ARM64,
}

REMOTE_DOCKER_ENGINE_IMAGES: Dict[CpuArch, CustomAMIImage] = {}


for arch, base_image in BASE_IMAGES.items():

    if arch == CpuArch.x86_64:
        size_id = "t2.small"
    elif arch == CpuArch.AARCH64:
        size_id = "t4g.small"
    else:
        raise Exception(f"Unknown architecture: {arch.value}")

    image = CustomAMIImage(
        name="test",
        base_image=base_image,
        base_instance_size_id=size_id,
        deployment_script=_DEPLOYMENT_SCRIPT_PATH,
    )

    REMOTE_DOCKER_ENGINE_IMAGES[arch] = image


# def get_remote_docker_ami_image(
#         architecture: CpuArch,
#         ec2_client,
#         ec2_resource,
#         aws_settings: AWSSettings
# ):
#
#     base_ec2_image = BASE_IMAGES[architecture]
#     info = REMOTE_DOCKER_ENGINE_AMI_INFOS[architecture]
#     builder_images = get_all_cicd_images(
#         ec2_resource=ec2_resource,
#     )
#
#     for image in builder_images:
#         for tag in image.tags:
#             if tag["Key"] == "checksum" and tag["Value"] == checksum:
#                 logger.info(f"Use already existing AMI image with checksum '{checksum}'")
#                 return image
#
#     # Create new AMI image.
#     name = f"{CICD_AMI_IMAGES_NAME_PREFIX}_{architecture.value}_{checksum}"
#     logger.info(f"Create new ami image '{name}'")
#     instance = EC2InstanceWrapper.create_and_deploy_ec2_instance(
#         ec2_client=ec2_client,
#         ec2_resource=ec2_resource,
#         aws_settings=aws_settings,
#         ec2_image=base_ec2_image,
#         root_volume_size=32,
#         deployment_script=_DEPLOYMENT_SCRIPT_PATH,
#     )
#
#     try:
#         image = create_new_ami_image(
#             ec2_client=ec2_client,
#             ec2_resource=ec2_resource,
#             ec2_instance_id=instance.boto3_instance.id,
#             name=name,
#             checksum=checksum,
#             description="Image with pre-installed docker engine that is used in dataset agent's CI-CD",
#         )
#     finally:
#         instance.terminate()
#
#     return image
