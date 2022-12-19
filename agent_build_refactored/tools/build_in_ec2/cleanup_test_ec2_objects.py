# Copyright 2014-2022 Scalyr Inc.
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
This script is used by the GitHub Actions to clean up the ec2 instances and related objects.
"""

import sys
import pathlib as pl


# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.build_in_ec2 import AWSSettings, cleanup_old_prefix_list_entries, cleanup_old_ec2_test_instance


if __name__ == "__main__":

    aws_settings = AWSSettings.create_from_env()

    cleanup_old_prefix_list_entries(
        boto3_client=aws_settings.create_boto3_ec2_client(),
        prefix_list_id=aws_settings.security_groups_prefix_list_id,
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix,
    )

    cleanup_old_ec2_test_instance(
        libcloud_ec2_driver=aws_settings.create_libcloud_ec2_driver(),
        ec2_objects_name_prefix=aws_settings.ec2_objects_name_prefix
    )
