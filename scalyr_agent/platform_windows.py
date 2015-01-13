# Copyright 2014 Scalyr Inc.
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
# ------------------------------------------------------------------------
#
# author: Scott Sullivan <guy.hoozdis@gmail.com>

__author__ = 'guy.hoozdis@gmail.com'


import sys

try:
    from scalyr_agent.ScalyrAgentService import ScalyrAgentService, WindowsPlatformController
except ImportError:
    # The module lookup path list might fail when this module is being hosted by
    # PythonService.exe, so append the lookup path and try again.
    from os import path
    sys.path.append(
        path.dirname(
            path.dirname(
                path.abspath(__file__)
            )
        )
    )
    from scalyr_agent.ScalyrAgentService import ScalyrAgentService, WindowsPlatformController
