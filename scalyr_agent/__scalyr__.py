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


import platform
import os
import sys
import pathlib as pl
import enum
from typing import Tuple


PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3
PY2_pre_279 = PY2 and sys.version_info < (2, 7, 9)
PY3_pre_32 = PY3 and sys.version_info < (3, 2)


# TODO: change this explanation comment since now there's no the 'package_root' thing.
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


# Indicates if this code was compiled into a single executable via PyInstaller.  If that's the case,
# then we cannot rely on __file__ and the source is kind of through into the same directory.
__is_frozen__ = hasattr(sys, "frozen")


class PlatformType(enum.Enum):
    """
    The Enum class with possible types of the OS. Firstly, used for the 'P'
    """
    WINDOWS = "windows"
    LINUX = "linux"


def __determine_platform():
    system_name = platform.system().lower()
    if system_name.startswith("win"):
        return PlatformType.WINDOWS
    elif system_name.startswith("linux"):
        return PlatformType.LINUX


PLATFORM_TYPE = __determine_platform()


# The enum  for INSTALL_TYPE, a variable declared down below.
class InstallType(enum.Enum):
    """
    The enumeration of the Scalyr agent installation types. It is used for INSTALL_TYPE, a variable declared down below.
    """
    # region Those package types contain Scalyr Agent as frozen binary.
    PACKAGE_INSTALL = "package" # Indicates it was installed via a package manager such as RPM or Windows executable.
    TARBALL_INSTALL = "packageless" # Indicates it was installed via a tarball.
    # endregion
    DEV_INSTALL = "dev" # Indicates source code is running out of the original source tree, usually during dev testing.


# def __determine_install_type() -> InstallType:
#     """
#     Returns the type of install that was used for the source currently running.
#     """
#     if __is_frozen__:
#         # All installation types that use frozen binary of the Scalyr agent follow the same file structure,
#         # so it's just needed to specify the relative path to the install root from the current executable binary path.
#
#         # The executable frozen binary should be in the <install-root>/bin folder.
#
#         # Since it is a frozen binary, then the `sys.executable has to work as a path for the frozen binary itself,
#         # so we can find the 'bin' folder from it.
#         executable_dir = pl.Path(sys.executable).parent
#
#         # Move the parent <install-root> folder.
#         install_root = executable_dir.parent
#
#         # Search for the special file. The installation type has to be written to it.
#
#         install_type_file = install_root / "install_type"
#
#         if install_type_file.is_file():
#             install_type = install_type_file.read_text().strip()
#             if install_type not in [e.value for e in InstallType]:
#                 # Any supported package file type haven't been found.
#                 raise ValueError(f"Can not determine the installation type. Unknown value: {install_type}")
#         else:
#             # TODO: Here we can handle an install type which is similar to the DEV_INSTALL
#             #  but withing the frozen binary.
#             raise FileNotFoundError(
#                 f"Can not determine the installation type. The file {install_type_file} is not found."
#             )
#
#         return InstallType(install_type)
#     else:
#         script_path = pl.Path(sys.argv[0])
#         if not script_path.is_absolute():
#             script_path = pl.Path(os.getcwd(), script_path)
#
#         root_path = script_path.parent.parent.parent
#         install_type_file = root_path / "install_type"
#         if install_type_file.is_file():
#             if install_type_file.read_text().strip() == InstallType.TARBALL_INSTALL.value:
#                 return InstallType.TARBALL_INSTALL
#
#         # For now, there's no any installation type, which doesn't use frozen binaries, so just fallback to the DEV_INSTALL.
#         return InstallType.DEV_INSTALL
#
# def __determine_install_root() -> str:
#     """
#     Returns the absolute path to the root of the install location to scalyr-agent-2.  This
#     works for the different types of installation such as RPM and Debian, as well as when this
#     is running from the source tree.
#
#     For example, it will return:'/usr/share/scalyr-agent-2', for Linux installs and
#     the top of the repository when running from the source tree.
#     """
#
#     if INSTALL_TYPE == InstallType.PACKAGE_INSTALL:
#         # The install root dir should be a parent directory for the 'bin' folder where the executables are stored.
#         result = pl.Path(sys.executable).parent.parent
#     elif INSTALL_TYPE == InstallType.TARBALL_INSTALL:
#         result = pl.Path(__file__).parent.parent
#     elif INSTALL_TYPE == InstallType.DEV_INSTALL:
#         # The install root is just a source root in case of DEV_INSTALL.
#         result = pl.Path(__file__).parent.parent
#     else:
#         raise ValueError(f"Can not determine the install root for the agent installation type: '{INSTALL_TYPE.value}'")
#
#     return str(result.absolute())


def __determine_install_root_and_type() -> Tuple[str, InstallType]:

    def read_install_type(path: pl.Path) -> InstallType:
        # Read the type of the package from the file.
        install_type = install_type_file_path.read_text().strip()
        # Check if the package type is one of the valid install types.
        if install_type not in [e.value for e in InstallType]:
            raise ValueError(f"Can not determine the installation type. Unknown value: {install_type}")

        return InstallType(install_type)

    if __is_frozen__:
        # All installation types that use frozen binary of the Scalyr agent follow the same file structure,
        # so it's just needed to specify the relative path to the install root from the current executable binary path.

        # The executable frozen binary should be in the <install-root>/bin folder.

        # Since it is a frozen binary, then the `sys.executable has to work as a path for the frozen binary itself,
        # so we can find the 'bin' folder from it.

        bin_dir = pl.Path(sys.executable).parent

        # Move the parent <install-root> folder.
        install_root = bin_dir.parent

        # All agent packages have the special file 'install_type' which contains the type of the package.
        # This file is always located in the install root, so it is a good way to verify if it is a install root or not.
        install_type_file_path = install_root / "install_type"
        if not install_type_file_path.is_file():
            # For now, we expect that the frozen binary can only be run correctly as a part of a package,
            # so if there's no an 'install_type' file, then something went wrong.
            raise FileNotFoundError(
                f"Can not determine the package installation type. The file '{install_type_file_path}' is not found."
            )

        return str(install_root), read_install_type(install_type_file_path)

    else:
        # The agent code is not frozen.
        # For now, there may be two possible scenarios:
        #   1. This is a package (for now - only the tarball) installation, but it has failed to run from the frozen binary and has fallen back
        #   to the source code. In this case, there is still has to be an 'install_type' in the root of the installation.
        #   2. There is no any package installation and agent started directly from the source repo, the most likely,
        #   during the development process (DEV_INSTALL).

        # First. Check if this is a DEV_INSTALL by looking for directories that presented only in the repository.
        # For example the 'agent_build' folder which is not used in the packages and is not copied there.
        # Get path of the this (__scalyr__.py) file.
        scalyr_module_path = pl.Path(__file__)
        # The parent dir of the __scalyr__.py file should be a 'scalyr_agent' package.
        scalyr_agent_package_path = scalyr_module_path.parent
        # And finally the next parent dir should be root of the repository.
        source_root = scalyr_agent_package_path.parent
        # Check for the 'agent_build' folder.
        agent_build_folder = source_root / "agent_build"
        if agent_build_folder.is_dir():
            return str(source_root), InstallType.DEV_INSTALL
        else:
            # This is not a 'DEV_INSTALL', so it should be package installation.
            # In the packages, the source code of the agent is located in '<install_path>/source',
            # so it is just needed to get the next parent directory.
            install_root = source_root.parent

            # Since this is a package installation, there has to be an 'install_type' file in the installation root,
            # read it to determine the type of the package.
            install_type_file_path = install_root / "install_type"
            if not install_type_file_path.is_file():
                raise FileNotFoundError(
                    f"Can not determine the package installation type. The file '{install_type_file_path}' is not found."
                )
            return str(install_root), read_install_type(install_type_file_path)


__install_root__, INSTALL_TYPE = __determine_install_root_and_type()


def get_install_root():
    """
    The root of the agent installation.
    """
    return __install_root__


def __determine_version():
    """
    Returns the agent version number, read from the VERSION file.
    """
    version_file_path = pl.Path(get_install_root()) / "VERSION"
    return version_file_path.read_text().strip()


SCALYR_VERSION = __determine_version()

a=10

print("FFFF")
sys.path.insert(0, os.path.join(str(get_install_root()), "scalyr_agent/rm/third_party"))
