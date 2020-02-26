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
import tempfile
import shutil

from .compat import Path

from scalyr_agent.__scalyr__ import get_package_root

import six
from scalyr_agent import compat


def get_env(name):
    try:
        return compat.os_environ_unicode[name]
    except KeyError:
        raise KeyError("Environment variable: '{0}' not set.".format(name))


def create_temp_dir_with_constant_name(name):
    # type: (six.text_type) -> Path
    """
    Create temporary directory but with constant name.
    :param name: tmp directory name.
    :return: path object to new tmp directory.
    """
    tmp_dir_path = Path(tempfile.gettempdir()) / name
    if tmp_dir_path.exists():
        shutil.rmtree(six.text_type(tmp_dir_path), ignore_errors=True)
    tmp_dir_path.mkdir(exist_ok=True)

    return tmp_dir_path


def copy_agent_source(dest_path):
    root_path = Path(get_package_root()).parent
    shutil.copytree(
        six.text_type(root_path),
        six.text_type(dest_path),
        ignore=shutil.ignore_patterns(
            "*.pyc",
            "__pycache__",
            "*.egg-info",
            ".tox",
            ".pytest*",
            ".mypy*",
            ".idea",
            ".git",
        ),
    )
