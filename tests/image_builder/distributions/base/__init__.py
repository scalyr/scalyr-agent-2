# Copyright 2014-2020 Scalyr Inc.
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

from __future__ import unicode_literals
from __future__ import absolute_import

import six

# this prefix is important. If it has to changed, you should also change it in dockerfiles and circleci bash scripts.
BASE_AGENT_DISTRIBUTION_PREFIX = "scalyr-agent-testings-distribution"


def create_distribution_image_name(
    distribution_name,
):  # type: (six.text_type) -> six.text_type
    return "{0}-{1}".format(BASE_AGENT_DISTRIBUTION_PREFIX, distribution_name)


def create_distribution_base_image_name(distribution_name):
    # type: (six.text_type) -> six.text_type
    return "{0}-{1}-base".format(BASE_AGENT_DISTRIBUTION_PREFIX, distribution_name)
