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

from __future__ import absolute_import
from tests.utils.compat import Path

from tests.utils.image_builder import AgentImageBuilder

import six

dockerfile = Path(Path(__file__).parent, "Dockerfile")


class BaseDistributionBuilder(AgentImageBuilder):
    COPY_AGENT_SOURCE = True

    @classmethod
    def get_dockerfile_content(cls):  # type: () -> six.text_type
        content = super(BaseDistributionBuilder, cls).get_dockerfile_content()
        return content.format(fpm_package_builder_dockerfile=dockerfile.read_text())
