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

if False:
    from typing import Dict

import random

from six.moves import range


def generate_random_dict(keys_count=10):
    # type: (int) -> Dict[str, str]
    """
    Generate dictionary with fixed random values.
    """
    result = {}
    keys = list(range(0, keys_count))
    random.shuffle(keys)

    for key in keys:
        result["key_%s" % (key)] = "value_%s" % (key)

    return result
