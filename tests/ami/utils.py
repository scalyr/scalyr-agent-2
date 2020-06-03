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

if False:  # NOSONAR
    from typing import Optional

from scalyr_agent import compat


def get_env_throw_if_not_set(name, default_value=None):
    # type: (str, Optional[str]) -> str
    """
    Return provided environment variable value and throw if it's not set.
    """
    value = compat.os_getenv_unicode(name, default_value)

    if value is None:
        raise ValueError("Environment variable '%s' not set" % (name))

    return value
