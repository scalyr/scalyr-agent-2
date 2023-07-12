import pathlib as pl
import hashlib
import time
from typing import List

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.tools.aws.boto3_tools import AWSSettings, create_and_deploy_ec2_instance
from agent_build_refactored.tools.aws.constants import EC2DistroImage

PARENT_DIR = pl.Path(__file__).parent.absolute()

IMAGE_NAME_PREFIX = "dataset-agent-ci-cd-builder-builder"


def get_all_cicd_docker_buildx_builder_images(boto3_session):

    ec2_resource = boto3_session.resource("ec2")
    images = list(ec2_resource.images.filter(
        Filters=[
            {
                "Name": "tag-key",
                "Values": [IMAGE_NAME_PREFIX]
            }
        ]
    ))

    return images


def create_new_ami_image(
        boto3_session,
        instance_id: str,
        checksum: str,
):

    ec2_client = boto3_session.client("ec2")

    created_image_info = ec2_client.create_image(
        InstanceId=instance_id,
        Description="Image with pre-installed docker engine that is used in dataset agent's CI-CD",
        Name=f"{IMAGE_NAME_PREFIX}-{checksum}",
        TagSpecifications=[
            {
                "ResourceType": "image",
                'Tags': [
                    {
                        'Key': IMAGE_NAME_PREFIX,
                        "Value": ""
                    },
                    {
                        'Key': "checksum",
                        "Value": checksum
                    },

                ]
            },
        ]
    )

    image_id = created_image_info["ImageId"]
    ec2_resource = boto3_session.resource("ec2")
    images = list(ec2_resource.images.filter(
        ImageIds=[image_id],
    ))

    if not images:
        raise Exception(f"Can not find created image {image_id}")

    new_image = images[0]

    while new_image.state == "pending":
        time.sleep(60)
        new_image.reload()

    if new_image.state != "available":
        raise Exception("Error during the creation of the image")


    return new_image


def get_buildx_builder_ami_image(
        base_ec2_image: EC2DistroImage,
        boto3_session,
        aws_settings: AWSSettings
):
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

    builder_images = get_all_cicd_docker_buildx_builder_images(boto3_session=boto3_session)

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
    )

    return image


def main():
    get_buildx_builder_ami_image()


if __name__ == '__main__':
    main()

    a=10

