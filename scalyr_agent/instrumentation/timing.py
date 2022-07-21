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

if False:
    from typing import Dict

__all__ = [
    "get_empty_stats_dict",
    "reset_stats_dict",
]


def get_empty_stats_dict():
    # type: () -> Dict[str, float]
    """
    Return empty dictionary used for holding function timing stats information.

    TODO: Once we move to Python 3 only, use a dataclass instead.
    """
    return reset_stats_dict({})


def reset_stats_dict(stats_dict):
    # type: (Dict[str, float]) -> None
    """
    Reset values for the provided function run time stats dictionary.
    """
    stats_dict["min"] = float("inf")
    stats_dict["max"] = float("-inf")
    stats_dict["avg"] = 0.0
    stats_dict["sum"] = 0.0
    stats_dict["count"] = 0
    return stats_dict
