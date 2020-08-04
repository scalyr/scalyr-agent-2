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

from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

# [start of 2->TODO]
# "Modernize" tool added "six" library as a dependency in this file.
# But in case of absence of six in site-packages we can not import "six" before scalyr_init.
# The first option is to provide 2->3 compatibility without "six". This is easy for now,
# because there is only one incompatible piece of code here.
# and it can be fixed in code below...
try:
    # Python2
    text_type = unicode  # type: ignore
except NameError:
    # Python3
    text_type = str
# The second option is to assure that "six" library installed in current python environment.
# [end of 2->TOD0]


import inspect
import os
import sys
from io import open

# One of the main things this file does is correctly give the full path to two key directories regardless of install
# type :
#   package_root:  The directory containing the Scalyr source (contains files like 'agent_main.py', etc)
#   install_root:  The top-level directory where Scalyr is currently installed (contains files like 'CHANGELOG.md')
#
# There are several different ways we can be running, and this files has to give the correct values for each of them.
# For example, we could just be running out of the source tree as checked into github.  Or we can be running
# out of an RPM.  Or as part of a single Windows executable created by PyInstaller.  We handle of these cases.
#
# Example layouts for different install types:
#
# Running from source:
#     ~/scalyr-agent-2/VERSION
#     ~/scalyr-agent-2/scalyr-agent/__scalyr__.py
#     ~/scalyr-agent-2/scalyr-agent/third_party
#
#   Here the install root is ~/scalyr-agent-2 and the package root is ~/scalyr-agent-2/scalyr-agent
#
# Install using tarball:
#     ~/scalyr-agent-2/py/scalyr_agent/VERSION
#     ~/scalyr-agent-2/py/scalyr_agent/__scalyr__py
#     ~/scalyr-agent-2/py/scalyr_agent/third_party
#
#   Here the install root is ~/scalyr-agent-2 and the package root is ~/scalyr-agent-2/py/scalyr-agent
#
# Install using rpm/deb package:
#     /usr/share/scalyr-agent-2/py/scalyr_agent/VERSION
#     /usr/share/scalyr-agent-2/py/scalyr_agent/__scalyr__py
#     /usr/share/scalyr-agent-2/py/scalyr_agent/third_party
#
#   Here the install root is /usr/share/scalyr-agent-2 and the package root is /usr/share/scalyr-agent-2/py/scalyr-agent
#
# Install using win32 exe:
#     C:\Program Files (x86)\Scalyr\program_files\VERSION
#     C:\Program Files (x86)\Scalyr\program_files\__scalyr__.py
#     (There is no third party directory... its contents gets added directly to program_files
#
#   Here the install root is C:\Program Files (x86)\Scalyr\ and the package root is
#   C:\Program Files (x86)\Scalyr\program_files\

# Indicates if this code was compiled into a single Windows executable via PyInstaller.  If that's the case,
# then we cannot rely on __file__ and the source is kind of through into the same directory.
__is_frozen__ = hasattr(sys, "frozen")


def scalyr_init():
    """Initializes the environment to execute a Scalyr script.

    This should be invoked by any Scalyr module that has a main (i.e., can invoked by the commandline to
    perform some action).

    It performs such tasks as ensures PYTHONPATH include the Scalyr package and fixing some third-party import issues.
    """
    # If this is a win32 executable, then all the packages have already been bundled in the exec and there is no
    # need to change the PYTHONPATH
    if not __is_frozen__:
        __add_scalyr_package_to_path()


def __determine_package_root():
    """Returns the absolute file path to the package root.

    This must be invoked before the current working directory is changed by the code, so therefore should be
    invoked during the module load.

    @return: The absolute file path for the package root.
    """
    # We rely on the fact this file (__scalyr__.py) should be in the directory that is the package root.
    # We could just return the parent of __file__, however, this apparently is not portable on all version of
    # Windows.  Moreover, when running as a win32 exe, __file__ is not set.
    if not __is_frozen__:
        base = os.getcwd()
        file_path = inspect.stack()[1][1]
        if not os.path.isabs(file_path):
            file_path = os.path.join(base, file_path)
        file_path = os.path.dirname(os.path.realpath(file_path))
    else:
        # encode python executable path for python 2.
        executable_path = sys.executable
        if type(executable_path) != text_type:
            executable_path = text_type(executable_path, sys.getfilesystemencoding())
        return os.path.dirname(executable_path)

    return file_path


__package_root__ = __determine_package_root()


def get_package_root():
    """Returns the absolute path to the scalyr_agent Python package, including the scalyr_agent directory name.

    @return: The path to the scalyr_agent directory (which contains the Python package).
    @rtype: six.text_type
    """
    return __package_root__


def get_install_root():
    """Returns the absolute path to the root of the install location to scalyr-agent-2.  This
    works for the different types of installation such as RPM and Debian, as well as when this
    is running from the source tree.

    For example, it will return '/usr/share/scalyr-agent-2', for Linux installs and
    the top of the repository when running from the source tree.

    @return:  The path to the scalyr-agent-2 directory.
    @rtype: six.text_type
    """
    # See the listed cases above.  From that, it should be clear that these rules work for the different cases.
    parent_of_package_install = os.path.dirname(get_package_root())
    if __is_frozen__:  # win32 install
        return parent_of_package_install
    elif os.path.basename(parent_of_package_install) != "py":  # Running from Source
        return parent_of_package_install
    else:  # Installed using tarball or rpm/debian package
        return os.path.dirname(parent_of_package_install)


def __add_scalyr_package_to_path():
    """Adds the path for the scalyr package and embedded third party packages to the PYTHONPATH.

    If you add any new paths in this method, be sure to add them near the top of `setup.py` as well so as not
    to break the Windows builds.
    """
    # prepend the third party directory first so it appears after the package root, third_party_pythonX
    # and third_party_tls directories
    sys.path.insert(0, os.path.join(get_package_root(), "third_party"))

    if sys.version_info[0] == 2:
        sys.path.insert(0, os.path.join(get_package_root(), "third_party_python2"))
    else:
        sys.path.insert(0, os.path.join(get_package_root(), "third_party_python3"))

    # if we are not on windows, prepend the third party tls directory first so it appears after the package root
    if not __is_frozen__:
        sys.path.insert(0, os.path.join(get_package_root(), "third_party_tls"))

    sys.path.insert(0, os.path.dirname(get_package_root()))


def __determine_version():
    """Returns the agent version number, read from the VERSION file.
    """

    file_names = ["VERSION"]

    if __is_frozen__:
        # also check for VERSION.txt file because there is a reserved filename - "VERSION" in Pyinstaller,
        # and it expects that this file is a DLL.
        file_names.append("VERSION.txt")

    def find_path():
        # This file can be either in the package root or the install root (if you examine the cases
        # from above).  So, just check both locations.
        for root in [get_install_root(), get_package_root()]:
            for file_name in file_names:
                path = os.path.join(root, file_name)
                if os.path.isfile(path):
                    return path

        raise Exception("Could not locate VERSION file!")

    version_path = find_path()

    version_fp = open(version_path, "r")
    try:
        return version_fp.readline().strip()
    finally:
        version_fp.close()


SCALYR_VERSION = __determine_version()


# The constants for INSTALL_TYPE, a variable declared down below.
PACKAGE_INSTALL = 1  # Indicates source code was installed via a package manager such as RPM or Windows executable.
TARBALL_INSTALL = 2  # Indicates source code was installed via a tarball created by the build_package.py script.
DEV_INSTALL = 3  # Indicates source code is running out of the original source tree, usually during dev testing.
MSI_INSTALL = 4  # Indicates source code was installed via a Windows MSI package


def __determine_install_type():
    """Returns the type of install that was used for the source currently running.

    @return: The install type, drawn from the constants above.
    @rtype: int
    """
    # Determine which type of install this is.  We do this based on
    # whether or not certain files exist in the root of the source tree.
    install_root = get_install_root()
    if os.path.exists(os.path.join(install_root, "packageless")):
        install_type = TARBALL_INSTALL
    elif os.path.exists(os.path.join(install_root, "run_tests.py")):
        install_type = DEV_INSTALL
    elif hasattr(sys, "frozen"):
        install_type = MSI_INSTALL
    else:
        install_type = PACKAGE_INSTALL
    return install_type


# Holds which type of installation we are currently running from.
INSTALL_TYPE = __determine_install_type()
