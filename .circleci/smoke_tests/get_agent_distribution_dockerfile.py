from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import argparse
import os
import sys

root_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(root_path)

from smoke_tests.tools.package import (
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
