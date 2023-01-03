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

"""
This script performs set of simple sanity checks for a Python interpreter that is shipped by the
Linux dependency packages.
"""

import re
import os
import sys
import pathlib as pl
import site

from agent_build_refactored.tools.constants import SOURCE_ROOT
from agent_build_refactored.managed_packages.scalyr_agent_python3 import PYTHON_PACKAGE_SSL_VERSION
from agent_build_refactored.managed_packages.managed_packages_builders import (
    AGENT_SUBDIR_NAME as SUBDIR,
)

# Make sure that current interpreter prefixes are withing subdirectories.
assert sys.prefix == f"/usr/lib/{SUBDIR}/requirements/python3"
assert sys.exec_prefix == sys.prefix

# Check that only verified prefixes are used.
assert set(site.PREFIXES) == {sys.prefix, sys.exec_prefix}

PYTHON_MAJOR_VERSION = sys.version_info[0]
PYTHON_MINOR_VERSION = sys.version_info[1]
PYTHON_X_Y_VERSION = f"{PYTHON_MAJOR_VERSION}.{PYTHON_MINOR_VERSION}"

# Verify that site packages paths collection consists only of expected paths.
assert set(site.getsitepackages()) == {
    f"{sys.prefix}/lib/python{PYTHON_X_Y_VERSION}/site-packages",
    f"{sys.exec_prefix}/lib/python{PYTHON_X_Y_VERSION}/site-packages",
}

# Verify that only previously checked prefixes are used in the Python paths.
assert sys.path == [
    str(pl.Path(__file__).parent),
    str(SOURCE_ROOT),
    f"{sys.prefix}/lib/python{PYTHON_MAJOR_VERSION}{PYTHON_MINOR_VERSION}.zip",
    f"{sys.prefix}/lib/python{PYTHON_X_Y_VERSION}",
    f"{sys.prefix}/lib/python{PYTHON_X_Y_VERSION}/lib-dynload",
    f"{sys.prefix}/lib/python{PYTHON_X_Y_VERSION}/site-packages",
]

# Check that only libraries from the previously verified prefix are used.
assert os.environ["LD_LIBRARY_PATH"].startswith(f"{sys.prefix}/lib")