import hashlib
import time

from agent_build_refactored.tools.aws.boto3_tools import AWSSettings
from agent_build_refactored.tools.aws.ec2 import create_and_deploy_ec2_instance
from agent_build_refactored.tools.constants import CpuArch

CICD_AMI_IMAGES_TAG = "dataset-agent-build"
CICD_AMI_IMAGES_NAME_PREFIX = "dataset-agent-build"

_used_ami_images = []


def get_all_cicd_images(boto3_session):

    ec2_resource = boto3_session.resource("ec2")
    images = list(ec2_resource.images.filter(
        Filters=[
            {
                "Name": "tag-key",
                "Values": [CICD_AMI_IMAGES_TAG]
            }
        ]
    ))

    return images


def create_new_ami_image(
        boto3_session,
        ec2_instance_id: str,

        checksum: str,
        description: str,
):

    ec2_client = boto3_session.client("ec2")

    created_image_info = ec2_client.create_image(
        InstanceId=ec2_instance_id,
        Description=description,
        Name=f"{CICD_AMI_IMAGES_NAME_PREFIX}-{checksum}",
        TagSpecifications=[
            {
                "ResourceType": "image",
                'Tags': [
                    {
                        'Key': CICD_AMI_IMAGES_TAG,
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
