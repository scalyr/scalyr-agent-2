import pathlib as pl
import hashlib

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.aws.constants import EC2DistroImage
from agent_build_refactored.tools.aws.ami import CICD_AMI_IMAGES_NAME_PREFIX, create_new_ami_image
from agent_build_refactored.tools.aws.boto3_tools import AWSSettings
from agent_build_refactored.tools.aws.ec2 import create_and_deploy_ec2_instance

PARENT_DIR = pl.Path(__file__).parent.absolute()

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
    # Use the same 64 bit image since it's compatible.
    CpuArch.ARMV7: BASE_IMAGE_ARM64
}


def get_all_docker_engine_images(boto3_session):
    ec2_resource = boto3_session.resource("ec2")
    images = list(ec2_resource.images.filter(
        Filters=[
            {
                "Name": "tag-key",
                "Values": [_DOCKER_ENGINE_IMAGE_TAG]
            }
        ]
    ))

    return images


def get_buildx_builder_ami_image(
        architecture: CpuArch,
        boto3_session,
        aws_settings: AWSSettings
):
    base_ec2_image = BASE_IMAGES[architecture]

    deployment_script_path = PARENT_DIR / "deploy_docker_in_ec2_instance.sh"
    sha256 = hashlib.sha256()

    # calculate checksum of the AMI image, so we can rebuild it if some
    # data of the image has been changed.
    sha256.update(deployment_script_path.read_bytes())
    sha256.update(base_ec2_image.image_id.encode())
    sha256.update(base_ec2_image.image_name.encode())
    sha256.update(base_ec2_image.size_id.encode())
    sha256.update(base_ec2_image.short_name.encode())
    sha256.update(base_ec2_image.ssh_username.encode())

    checksum = sha256.hexdigest()

    builder_images = get_all_docker_engine_images(boto3_session=boto3_session)

    needed_image = None
    for image in builder_images:
        for tag in image.tags:
            if tag["Key"] == "checksum" and tag["Value"] == checksum:
                needed_image = image
                break

    images_to_remove = builder_images[:]
    if needed_image:
        images_to_remove.remove(needed_image)

    # Cleanup old images.
    ec2_client = boto3_session.client("ec2")
    for image in images_to_remove:
        ec2_client.deregister_image(
            ImageId=image.id,
        )

    if needed_image:
        return needed_image

    # Create new AMI image.
    # Start instance first.
    instance = create_and_deploy_ec2_instance(
        boto3_session=boto3_session,
        aws_settings=aws_settings,
        name_prefix="remote_docker",
        ec2_image=base_ec2_image,
        root_volume_size=32,
        deployment_script=deployment_script_path,
    )

    image = create_new_ami_image(
        boto3_session=boto3_session,
        instance_id=instance.id,

        checksum=checksum,
        description="Image with pre-installed docker engine that is used in dataset agent's CI-CD",
    )

    return image


