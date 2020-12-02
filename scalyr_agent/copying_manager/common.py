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


if False:
    from typing import Dict

from scalyr_agent import util as scalyr_util

import six


def write_checkpoint_state_to_file(checkpoints, file_path, current_time):
    # type: (Dict, six.text_type, float) -> None
    """
    Write checkpoint state into file.
    :param checkpoints: The checkpoint state stored in dict.
    :param file_path: Output file path.
    """
    # We write to a temporary file and then rename it to the real file name to make the write more atomic.
    # We have had problems in the past with corrupted checkpoint files due to failures during the write.
    tmp_path = file_path + "~"
    state = {
        "time": current_time,
        "checkpoints": checkpoints,
    }
    scalyr_util.atomic_write_dict_as_json_file(file_path, tmp_path, state)
