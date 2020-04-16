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

from __future__ import print_function
from __future__ import absolute_import
from __future__ import unicode_literals

from tests.utils.compat import Path
from tests.utils.image_builder import AgentImageBuilder
from tests.image_builder.monitors.base import BaseMonitorBuilder


class CommonMonitorBuilder(AgentImageBuilder):
    IMAGE_TAG = "scalyr-agent-testings-monitor-common"
    DOCKERFILE = Path(__file__).parent / "Dockerfile"
    INCLUDE_PATHS = [
        Path(__file__).parent / "init.sql",
        Path(Path(__file__).parent / "nginx-config"),
        Path(Path(__file__).parent, "dummy-flask-server.py"),
    ]
    REQUIRED_IMAGES = [BaseMonitorBuilder]
    REQUIRED_CHECKSUM_IMAGES = [BaseMonitorBuilder]
    COPY_AGENT_SOURCE = True
    IGNORE_CACHING = True
