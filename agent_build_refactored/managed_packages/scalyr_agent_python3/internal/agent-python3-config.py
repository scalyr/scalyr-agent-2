# Copyright 2014-2023 Scalyr Inc.
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
This script provide some configuration options for the Agent's Python3 dependency package.
"""

import argparse
import pathlib as pl
import subprocess
import sys
import re
from typing import Tuple

OPENSSL_1_1_1_VERSION = "1_1_1"
OPENSSL_3_VERSION = "3"

DEFAULT_FALLBACK_OPENSSL_VERSION = OPENSSL_1_1_1_VERSION

DEPENDENCIES_PACKAGE_ROOT = pl.Path("/opt/scalyr-agent-2-dependencies")
OPENSSL_LIBS_PATH = DEPENDENCIES_PACKAGE_ROOT / "lib/openssl"


PYTHON_SHORT_VERSION = ".".join([str(n) for n in sys.version_info[:2]])

PYTHON_LIB_DYNLOAD_PATH = DEPENDENCIES_PACKAGE_ROOT / f"lib/python{PYTHON_SHORT_VERSION}/lib-dynload"


PREFERRED_OPENSSL_FILE_PATH = DEPENDENCIES_PACKAGE_ROOT / "etc/preferred_openssl"

# Bin directory of the package.
BIN_DIR = DEPENDENCIES_PACKAGE_ROOT / "bin"

# This directory is basically a symlink for to another directory with OpenSSL shared objects.
# This script's work is to decide what OpenSLL shared objects to use and link directory with its shared object
# with this directory.
CURRENT_OPENSSL_LIBS_PATH = OPENSSL_LIBS_PATH / "current"


def initialize():
    """
    Initialize package. For example, look for a system OpenSSl to use. If not found, then
    embedded OpenSSL library is used.
    :return:
    """
    preferred_openssl = None

    if PREFERRED_OPENSSL_FILE_PATH.exists():
        preferred_openssl = PREFERRED_OPENSSL_FILE_PATH.read_text().strip()

    if not preferred_openssl:
        preferred_openssl = "auto"

    if preferred_openssl == "auto":
        try:
            unlink_embedded_openssl()

            print("Looking for system OpenSSL >= 3: ", file=sys.stderr, end='')
            link_bindings(version_type=OPENSSL_3_VERSION)

            is_found, version_or_error = get_current_openssl_version(version_type=OPENSSL_3_VERSION)
            if is_found:
                print(f"found OpenSSL {version_or_error}", file=sys.stderr)
                return

            print(version_or_error, file=sys.stderr)

            print("Looking for system OpenSSL >= 1.1.1: ", file=sys.stderr, end='')
            link_bindings(version_type=OPENSSL_1_1_1_VERSION)
            is_found, version_or_error = get_current_openssl_version(version_type=OPENSSL_1_1_1_VERSION)
            if is_found:
                print(f"found OpenSSL {version_or_error}", file=sys.stderr)
                return

            print(version_or_error, file=sys.stderr)
        except Exception as e:
            print(
                f"Warning: Could not determine system OpenSSL version due to error: {str(e)}",
                file=sys.stderr
            )

    print("Using embedded OpenSSL == ", file=sys.stderr, end='')
    link_bindings(version_type=OPENSSL_1_1_1_VERSION)
    link_embedded_openssl(openssl_variant=OPENSSL_1_1_1_VERSION)
    is_found, version_or_error = get_current_openssl_version(version_type=OPENSSL_1_1_1_VERSION)
    if not is_found:
        # Something very wrong happened and this is not expected.
        print(
            f"Unexpected error during initialization of the embedded OpenSSL: {version_or_error}",
            file=sys.stderr
        )
        exit(1)

    print(version_or_error, file=sys.stderr)


def unlink_embedded_openssl():
    """
    Remove symlink to a directory with embedded OpenSSL shared objects, enabling system's
    dynamic linker to look for OpenSSL in other places.
    :return:
    """
    if CURRENT_OPENSSL_LIBS_PATH.exists():
        CURRENT_OPENSSL_LIBS_PATH.unlink()


def link_embedded_openssl(openssl_variant: str):
    """
    Create symlink in the path which is included to Python's LD_LIBRARY_PATH variable.
    The symlink itself points to the directory with OpenSSL shared objets.
    :param openssl_variant:
    :return:
    """
    unlink_embedded_openssl()

    openssl_libs_path = OPENSSL_LIBS_PATH / openssl_variant / "libs"
    CURRENT_OPENSSL_LIBS_PATH.symlink_to(openssl_libs_path)


def link_bindings(version_type: str):
    """
    Configure Python's 'ssl' and 'hashlib' modules C bindings by linking to their
        a particular shared objects.
    :param version_type:  version of the OpenSSL to use, 1_1_1 or 3
    :return:
    """

    openssl_version_path = OPENSSL_LIBS_PATH / version_type / "bindings"

    for binding_filename_glob in [
        "_ssl.*-*-*-*-*.so",
        "_hashlib.*-*-*-*-*.so",
    ]:
        binding_path = list(openssl_version_path.glob(binding_filename_glob))[0]
        binding_filename = binding_path.name
        symlink_path = PYTHON_LIB_DYNLOAD_PATH / binding_filename

        if symlink_path.exists():
            symlink_path.unlink()

        symlink_path.symlink_to(binding_path)


def get_current_openssl_version(version_type: str) -> Tuple[bool, str]:
    """
    Determine current system OpenSSL version, if presented.
    :param version_type: version of the OpenSSL to use.
    :return: Tuple where:
        First element - boolean flag that indicated whether appropriate version of OpenSSL is
            found or not.
        Second element - if  First flag is true - version of OpenSLL, if False - an error message.
    """

    result = subprocess.run(
        [
            str(BIN_DIR / "python_wrapper"),
            "-c",
            "import ssl; print(ssl.OPENSSL_VERSION);"
        ],
        capture_output=True,
        env={"LD_LIBRARY_PATH": ""}
    )

    if result.returncode != 0:
        return False, "Not found"

    version_output = result.stdout.decode()

    if version_type == OPENSSL_1_1_1_VERSION:
        pattern = r"OpenSSL (\d+\.\d+\.\d+[a-zA-Z]).*"
    else:
        pattern = r"OpenSSL (\d+\.\d+\.\d+).*"

    m = re.match(pattern, version_output)

    if not m:
        return False, f"Unknown OpenSSL version format: '{version_output}'"

    return True, m.group(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize_parser = subparsers.add_parser("initialize")

    set_option_parser = subparsers.add_parser("set")
    set_option_subparsers = set_option_parser.add_subparsers(dest="option_name", required=True)
    preferred_openssl_parser = set_option_subparsers.add_parser(
        "preferred_openssl",
        help="Specify how agent's Python interpreter has to resolve which OpenSSL"
             " to use. "
             "'auto'- first look for system OpenSSL and only then fallback to embedded OpenSSL."
             "'embedded' - use embedded OpenSSL library without trying to find it in system."
    )
    preferred_openssl_parser.add_argument(
        "value",
        choices=["auto", "embedded"]
    )

    args = parser.parse_args()

    if args.command == "initialize":
        initialize()
        exit(0)
    elif args.command == "set":
        if args.option_name == "preferred_openssl":
            PREFERRED_OPENSSL_FILE_PATH.write_text(args.value)
            print(f"The 'preferred_openssl' option is set to '{args.value}'")
            initialize()
            exit(0)