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

import os

if False:
    from typing import Dict
    from typing import Optional

from scalyr_agent import util as scalyr_util
from scalyr_agent.scalyr_logging import AgentLogger
from scalyr_agent.configuration import Configuration

import six


def read_checkpoint_state_from_file(
    file_path, logger
):  # type: (six.text_type, AgentLogger) -> Optional[Dict]

    if not os.path.exists(file_path):
        return None

    # noinspection PyBroadException
    try:
        checkpoints = scalyr_util.read_file_as_json(file_path, strict_utf8=True)
    except Exception:
        logger.exception("Cannot read the checkpoint file {0}.".format(file_path))
        return None

    # the data in the file was somehow corrupted so it can not be read as dict.
    if not isinstance(checkpoints, dict):
        logger.error("The checkpoint file data has to be de-serialized into dict.")
        return None

    return checkpoints


def update_checkpoint_state_in_file(
    checkpoints_to_save, file_path, current_time, config, logger
):
    # type: (Dict, six.text_type, float, Configuration, AgentLogger) -> None
    """
    Updates the content of the file with the checkpoint states from the given log processors.
    Initially, it reads the checkpoints from the file(if exists) and removes all stale checkpoint states. It is better
    to remove stale checkpoint state to prevent the checkpoint file growth.

    :param checkpoints_to_save: The checkpoint states.
    :param file_path: The checkpoint file path.
    """

    checkpoints = {}

    # read existing checkpoint files (if presented).
    file_data = read_checkpoint_state_from_file(file_path, logger)

    if file_data:
        checkpoints = file_data["checkpoints"]

    # remove stale checkpoint states.
    for path, state in list(checkpoints.items()):
        state_timestamp = state.get("time")
        if state_timestamp is None:
            continue

        # remove the checkpoint state if it is older than time which is specified in the config.
        if state_timestamp + config.max_allowed_checkpoint_age < current_time:
            del checkpoints[path]

    checkpoints.update(checkpoints_to_save)
    write_checkpoint_state_to_file(checkpoints, file_path, current_time)


def write_checkpoint_state_to_file(checkpoints, file_path, current_time):

    tmp_path = file_path + "~"
    state = {
        "time": current_time,
        "checkpoints": checkpoints,
    }
    # We write to a temporary file and then rename it to the real file name to make the write more atomic.
    # We have had problems in the past with corrupted checkpoint files due to failures during the write.
    scalyr_util.atomic_write_dict_as_json_file(file_path, tmp_path, state)
