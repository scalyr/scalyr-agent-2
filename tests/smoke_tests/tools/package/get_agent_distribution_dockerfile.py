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
from __future__ import print_function
from __future__ import absolute_import

import argparse

from tests.smoke_tests.tools.package import (
    ALL_DISTRIBUTION_NAMES,
    get_agent_distribution_builder,
)
import six

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "distribution", type=six.text_type, choices=ALL_DISTRIBUTION_NAMES
    )
    parser.add_argument(
        "python_version", type=six.text_type, choices=["python2", "python3"]
    )

    args = parser.parse_args()

    builder = get_agent_distribution_builder(
        distribution=args.distribution, python_version=args.python_version
    )

    print(builder.get_dockerfile_content())
