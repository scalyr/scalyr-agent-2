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

"""
THis module defines custom AMI images with preinstalled Docker Engine, so we can use it as remote docker builder to
do to CPU heave compilations of agent dependencies.
"""

import logging
import pathlib as pl
from typing import Dict

from agent_build_refactored.utils.constants import CpuArch
from agent_build_refactored.utils.aws.ami import CustomAMIImage, StockAMIImage


logger = logging.getLogger(__name__)

_PARENT_DIR = pl.Path(__file__).parent.absolute()
_DEPLOYMENT_SCRIPT_PATH = _PARENT_DIR / "deploy_docker_in_ec2_instance.sh"

_DOCKER_ENGINE_IMAGE_TAG = "dataset-agent-build-docker-engine"

BASE_IMAGE_AMD64 = StockAMIImage(
    image_id="ami-053b0d53c279acc90",
    name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
    ssh_username="ubuntu",
)

BASE_IMAGE_ARM64 = StockAMIImage(
    image_id="ami-0a0c8eebcdd6dcbd0",
    name="Ubuntu Server 22.04 LTS (HVM), SSD Volume Type",
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
        name=f"remote_docker_engine_{arch.value}",
        base_image=base_image,
        base_instance_size_id=size_id,
        deployment_script=_DEPLOYMENT_SCRIPT_PATH,
    )

    REMOTE_DOCKER_ENGINE_IMAGES[arch] = image
