import hashlib
import time
from typing import Dict, Optional, List

from agent_build_refactored.tools.aws.boto3_tools import AWSSettings
from agent_build_refactored.tools.aws.constants import COMMON_TAG_NAME
from agent_build_refactored.tools.constants import CpuArch

CICD_AMI_IMAGES_NAME_PREFIX = "dataset-agent-build"

_used_ami_images = []


def get_all_cicd_images(
    ec2_resource,
):

    images = list(ec2_resource.images.filter(
        Filters=[
            {
                "Name": "tag-key",
                "Values": [COMMON_TAG_NAME]
            },
        ]
    ))

    return images


def create_new_ami_image(
        boto3_session,
        ec2_instance_id: str,
        name: str,
        checksum: str,
        description: str,
):

    ec2_client = boto3_session.client("ec2")

    created_image_info = ec2_client.create_image(
        InstanceId=ec2_instance_id,
        Description=description,
        Name=name,
        TagSpecifications=[
            {
                "ResourceType": "image",
                'Tags': [
                    {
                        'Key': COMMON_TAG_NAME,
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
