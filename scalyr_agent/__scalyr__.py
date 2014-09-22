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
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import inspect
import os
import sys


def scalyr_init():
    """Initializes the environment to execute a Scalyr script.

    This should be invoked by any Scalyr module that has a main (i.e., can invoked by the commandline to
    perform some action).

    It performs such tasks as ensures PYTHONPATH include the Scalyr package.
    """
    add_scalyr_package_to_path()


def determine_file_path(base=None):
    """Returns the absolute file path for module that invoked this function.

    This is similar to __file__ but determines it in a way that's suppose to be more portable.

    @param base: The current working directory that was being used when the module that's invoking this function was
        being invoked. If you invoke this method when the module loads, you may omit this parameter.

    @return: The absolute file path for the module that invoked this function.
    """
    # We do not rely on __file__ because
    # some folks report problems with that when running on some versions of Windows.
    # Get the file for this script and make it absolute.
    if base is None:
        base = os.getcwd()
    file_path = inspect.stack()[1][1]
    if not os.path.isabs(file_path):
        file_path = os.path.join(base, file_path)
    file_path = os.path.realpath(file_path)

    return file_path

__file_path__ = determine_file_path()


def add_scalyr_package_to_path():
    """Adds the path for the scalyr package and embedded third party packages to the PYTHONPATH.
    """
    sys.path.append(os.path.dirname(get_package_root()))
    # Also add in the third party directory
    sys.path.append(os.path.join(os.path.dirname(__file_path__), 'third_party'))


def get_package_root():
    """Returns the absolute path to the scalyr_agent Python package, including the scalyr_agent directory name.

    @return: The path to the scalyr_agent directory (which contains the Python package).
    @rtype: str
    """
    # We rely on the fact that the __scalyr__.py file should be in a directory structure that looks like:
    # py/scalyr_agent/__scalyr__.py  .  We wish to return the parent of this current file.
    return os.path.dirname(__file_path__)


def get_install_root():
    """Returns the absolute path to the root of the install location to scalyr-agent-2.  This
    works for the different types of installation such as RPM and Debian, as well as when this
    is running from the source tree.

    For example, it will return '/usr/share/scalyr-agent-2', for Linux installs and
    the top of the repository when running from the source tree.

    @return:  The path to the scalyr-agent-2 directory.
    @rtype: str
    """
    # There are cases to consider.  Either this source was installed as part of an RPM or Debian package,
    # or we are running directly from the source tree.  The paths to this package will look like:
    # /usr/share/scalyr-agent-2/py/scalyr_agent/__scalyr__.py      for RPM/Debian
    # ~/scalyr-agent-2/scalyr_agent/__scalyr__.py      for RPM/Debian.
    # So, we just look at the grandparent to determine which of the two cases we are in.
    grandparent = os.path.dirname(os.path.dirname(__file_path__))
    if os.path.basename(grandparent) == 'py':
        return os.path.dirname(grandparent)
    else:
        return grandparent


def __determine_version():
    """Returns the agent version number, read from the VERSION file.

    This file is either in this directory or the parent of this directory.
    """
    # There are two cases to handle.  We are either in development mode (just executing
    # the commands directly in the source tree), or this is an installed package.
    # For development mode, the VERSION file is in the parent of this directory.
    # For installed mode, the VERSION file will be in this directory.
    source_dir_path = os.path.dirname(__file_path__)
    parent = os.path.dirname(source_dir_path)

    if os.path.isfile(os.path.join(source_dir_path, 'VERSION')):
        version_path = os.path.join(source_dir_path, 'VERSION')
    elif os.path.isfile(os.path.join(parent, 'VERSION')):
        version_path = os.path.join(parent, 'VERSION')
    else:
        raise Exception('Could not locate VERSION file!')

    version_fp = open(version_path, 'r')
    try:
        return version_fp.readline().strip()
    finally:
        version_fp.close()


SCALYR_VERSION = __determine_version()
