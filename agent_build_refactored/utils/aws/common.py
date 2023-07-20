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


import dataclasses
import os
import pathlib as pl

import boto3

COMMON_TAG_NAME = "automated-agent-ci-cd"
CURRENT_SESSION_TAG_NAME = "current-ci-cd-session"


@dataclasses.dataclass
class AWSSettings:
    """
    Dataclass that stores all settings that are required to manipulate AWS objects.
    """

    access_key: str
    secret_key: str
    private_key_path: pl.Path
    private_key_name: str
    region: str
    cicd_workflow: str = None
    cicd_job: str = None

    @staticmethod
    def create_from_env():
        vars_name_prefix = os.environ.get("AWS_ENV_VARS_PREFIX", "")

        def _validate_setting(name, required: bool = True):
            final_name = f"{vars_name_prefix}{name}"
            value = os.environ.get(final_name)
            if value is None and required:
                raise Exception(f"Env. variable '{final_name}' is not found.")

            return value

        return AWSSettings(
            access_key=_validate_setting("AWS_ACCESS_KEY"),
            secret_key=_validate_setting("AWS_SECRET_KEY"),
            private_key_path=pl.Path(_validate_setting("AWS_PRIVATE_KEY_PATH")),
            private_key_name=_validate_setting("AWS_PRIVATE_KEY_NAME"),
            region=_validate_setting("AWS_REGION"),
            cicd_workflow=_validate_setting("CICD_WORKFLOW", required=False),
            cicd_job=_validate_setting("CICD_JOB", required=False),
        )

    def create_boto3_session(self):
        return boto3.session.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
        )


@dataclasses.dataclass
class EC2DistroImage:
    """
    Simple specification of the ec2 AMI image.
    """

    image_id: str
    image_name: str
    short_name: str
    size_id: str
    ssh_username: str
