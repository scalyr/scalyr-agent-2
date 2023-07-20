# Copyright 2014-2023 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import abc
import dataclasses
import hashlib
import logging
import time
import pathlib as pl
from typing import Dict, Optional

from agent_build_refactored.tools.aws.common import COMMON_TAG_NAME, AWSSettings

logger = logging.getLogger(__name__)

CICD_AMI_IMAGES_NAME_PREFIX = "dataset-agent-build"

_used_ami_images = []


class AMIImage:
    """
    Class that represents AWS EC2 AMI image.
    """
    def __init__(
        self,
        name: str,
        ssh_username: str,
        short_name: str = None
    ):
        self.name = name
        self.ssh_username = ssh_username
        self.short_name = short_name

    @property
    @abc.abstractmethod
    def image_id(self) -> str:
        pass

    def deploy_ec2_instance(
            self,
            size_id: str,
            root_volume_size: int = None,
            files_to_upload: Dict = None,
            deployment_script: pl.Path = None,
    ):
        from agent_build_refactored.tools.aws.ec2 import EC2InstanceWrapper

        aws_settings = AWSSettings.create_from_env()

        boto3_session = aws_settings.create_boto3_session()
        ec2_client = boto3_session.client("ec2")
        ec2_resource = boto3_session.resource("ec2")
        return EC2InstanceWrapper.create_and_deploy_ec2_instance(
            ec2_client=ec2_client,
            ec2_resource=ec2_resource,
            image_id=self.image_id,
            size_id=size_id,
            ssh_username=self.ssh_username,
            aws_settings=aws_settings,
            root_volume_size=root_volume_size,
            files_to_upload=files_to_upload,
            deployment_script=deployment_script,
        )


class StockAMIImage(AMIImage):
    """
    Represents "stock" (community or marketplace) AMI images in AWS.
    """

    def __init__(
        self,
        name: str,
        ssh_username: str,
        image_id: str,
        short_name: str = None
    ):
        super(StockAMIImage, self).__init__(
            name=name,
            ssh_username=ssh_username,
            short_name=short_name,
        )
        self._image_id = image_id

    @property
    def image_id(self) -> str:
        return self._image_id


@dataclasses.dataclass
class CustomAMIImage(AMIImage):
    """
    AWS EC2 images that can be build from the "base" existing AMI image with additional changes that
    can be done by specifying a deployment script.
    """
    base_image: AMIImage
    base_instance_size_id: str
    deployment_script: pl.Path = None,
    base_instance_root_volume_size: int = None
    base_instance_additional_ec2_instances_tags: Dict[str, Optional[str]] = None

    _checksum: str = dataclasses.field(init=False)
    _id: str = dataclasses.field(init=False, default=None)

    def __init__(
        self,
        name: str,
        base_image: AMIImage,
        base_instance_size_id: str,
        deployment_script: pl.Path = None,
        base_instance_root_volume_size: int = None,
        base_instance_additional_ec2_instances_tags: Dict[str, Optional[str]] = None,
        ssh_username: str = None,
        short_name: str = None,
    ):
        """

        :param name: Name of image.
        :param base_image: AMI image that is used as base.
        :param base_instance_size_id: Size id for an intermediate instance that will be used to create an image.
        :param deployment_script: Deployment script path.
        :param base_instance_root_volume_size: Root volume for intermediate ec2 instance.
        :param base_instance_additional_ec2_instances_tags: Additional tags for created instances.
        :param ssh_username:
        :param short_name:
        """
        super(CustomAMIImage, self).__init__(
            name=name,
            ssh_username=ssh_username or base_image.ssh_username,
            short_name=short_name,
        )

        self.base_image = base_image
        self.base_instance_size_id = base_instance_size_id
        self.deployment_script = deployment_script
        self.base_instance_root_volume_size = base_instance_root_volume_size
        self.base_instance_additional_ec2_instances_tags = base_instance_additional_ec2_instances_tags

        self._checksum: Optional[str] = None
        self._image_id: Optional[str] = None
        self._initialized = False

    @property
    def checksum(self):
        if self._checksum:
            return self._checksum

        sha256 = hashlib.sha256()

        # calculate checksum of the AMI image, so we can rebuild it if some
        # data of the image has been changed.
        sha256.update(self.deployment_script.read_bytes())

        sha256.update(self.base_image.image_id.encode())
        sha256.update(self.base_image.ssh_username.encode())

        sha256.update(self.ssh_username.encode())

        self._checksum = sha256.hexdigest()
        return self._checksum

    @property
    def image_id(self) -> str:
        if not self._image_id:
            self.initialize()

        return self._image_id

    def initialize(self):
        if self._initialized:
            return

        aws_settings = AWSSettings.create_from_env()
        boto3_session = aws_settings.create_boto3_session()
        ec2_client = boto3_session.client("ec2")
        ec2_resource = boto3_session.resource("ec2")

        found_boto3_images = list(ec2_resource.images.filter(
            Filters=[
                {
                    "Name": "tag-key",
                    "Values": [COMMON_TAG_NAME],
                },
            ]
        ))

        found_boto3_image = None
        for boto3_image in found_boto3_images:
            tags = {tag["Key"]: tag["Value"] for tag in boto3_image.tags}
            checksum = tags.get("checksum")
            if checksum == self.checksum:
                found_boto3_image = boto3_image
                break

        if found_boto3_image:
            self.wait_until_new_image_is_available(ec2_image=found_boto3_image)
            self._image_id = found_boto3_image.id
            return

        # Create new AMI image.
        name = f"{CICD_AMI_IMAGES_NAME_PREFIX}_{self.checksum}"
        logger.info(f"Create new ami image '{name}'")

        base_instance = self.base_image.deploy_ec2_instance(
            size_id=self.base_instance_size_id,
            root_volume_size=self.base_instance_root_volume_size,
            deployment_script=self.deployment_script,
        )

        try:

            logger.info(f"Create AMI image from the instance {base_instance.boto3_instance.id}")
            created_image_info = ec2_client.create_image(
                InstanceId=base_instance.boto3_instance.id,
                Description="Image with pre-installed docker engine that is used in dataset agent's CI-CD",
                Name=f"(disposable)agent_cicd_{name}",
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
                                "Value": self.checksum
                            },

                        ]
                    },
                ]
            )

            image_id = created_image_info["ImageId"]
            images = list(ec2_resource.images.filter(
                ImageIds=[image_id],
            ))
            if not images:
                raise Exception(f"Can not find created image {image_id}")

            new_ec2_image = images[0]
            self.wait_until_new_image_is_available(ec2_image=new_ec2_image)
        finally:
            base_instance.terminate()

        self._image_id = new_ec2_image.id
        return

    @staticmethod
    def wait_until_new_image_is_available(ec2_image):
        while ec2_image.state == "pending":
            time.sleep(60)
            ec2_image.reload()

        if ec2_image.state != "available":
            raise Exception(
                f"Error during the creation of the image. State: {ec2_image.state}"
            )
