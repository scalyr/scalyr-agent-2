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
    from typing import Union, Tuple, Any, Generator, Iterable, Optional

import sys
import struct
import os
import subprocess

import six

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3
PY26 = sys.version_info[0] == 2 and sys.version_info[1] == 6
PY27 = sys.version_info[0] == 2 and sys.version_info[1] == 7
PY2_pre_279 = PY2 and sys.version_info < (2, 7, 9)
PY_post_equal_279 = sys.version_info >= (2, 7, 9)
PY3_pre_32 = PY3 and sys.version_info < (3, 2)
PY3_post_equal_37 = PY3 and sys.version_info >= (3, 7)

# NOTE: ssl.match_hostname was added in Python 2.7.9 so for earlier versions, we need to use
# version from backports package
if PY2_pre_279 or PY3_pre_32:
    try:
        from backports.ssl_match_hostname import (
            match_hostname as ssl_match_hostname,
        )  # NOQA
        from backports.ssl_match_hostname import CertificateError  # NOQA
    except ImportError:
        # NOTE: We should never come here in real life. If we do, it indicates we messed up package
        # creation and / or path mangling in scalyr_init().
        raise Exception(
            "Missing backports.ssl_match_hostname module, hostname verification can't "
            "be performed"
        )
else:
    # ssl module in Python 2 >= 2.7.9 and Python 3 >= 3.2 includes match hostname function
    from ssl import match_hostname as ssl_match_hostname  # NOQA
    from ssl import CertificateError  # type: ignore # NOQA


def custom_any(iterable):
    if sys.version_info[:2] > (2, 4):
        return any(iterable)
    else:
        for element in iterable:
            if element:
                return True
        return False


def custom_all(iterable):
    if sys.version_info[:2] > (2, 4):
        return all(iterable)
    else:
        for element in iterable:
            if not element:
                return False
        return True


def custom_defaultdict(default_type):
    if sys.version_info[:2] > (2, 4):
        from collections import defaultdict

        return defaultdict(default_type)
    else:

        class DefaultDict(dict):
            def __getitem__(self, key):
                if key not in self:
                    dict.__setitem__(self, key, default_type())
                return dict.__getitem__(self, key)

        return DefaultDict()


if six.PY2:

    class EnvironUnicode(object):
        """Just a wrapper for os.environ, to convert its items to unicode in python2."""

        def __getitem__(self, item):
            value = os.environ[item]
            return six.ensure_text(value)

        def get(self, item, default=None):
            value = os.environ.get(item, default)
            if value is not None:
                value = six.ensure_text(value)
            return value

        def pop(self, item, default=None):
            value = os.environ.pop(item, default)
            if value is not None:
                value = six.ensure_text(value)
            return value

        def __setitem__(self, key, value):
            key = six.ensure_text(key)
            value = six.ensure_text(value)
            os.environ[key] = value

        @staticmethod
        def _iterable_elements_to_unicode_generator(iterable):
            # type: (Iterable) -> Generator[Union[Tuple, Any]]
            """Generator that gets values from original iterable and converts its 'str' values to 'unicode'"""
            for element in iterable:
                if type(element) is tuple:
                    yield tuple(
                        v.decode("utf-8", "replace")
                        if type(v) is six.binary_type
                        else v
                        for v in element
                    )
                else:
                    yield six.ensure_text(element)

        def iteritems(self):
            return self._iterable_elements_to_unicode_generator(
                six.iteritems(os.environ)
            )

        def items(self):
            return list(
                self._iterable_elements_to_unicode_generator(os.environ.items())
            )

        def iterkeys(self):
            return self._iterable_elements_to_unicode_generator(
                six.iterkeys(os.environ)
            )

        def keys(self):
            return list(self._iterable_elements_to_unicode_generator(os.environ.keys()))

        def itervalues(self):
            return self._iterable_elements_to_unicode_generator(
                six.itervalues(os.environ)
            )

        def values(self):
            return list(
                self._iterable_elements_to_unicode_generator(os.environ.values())
            )

        def copy(self):
            return dict(self.items())

        def __iter__(self):
            return self.iterkeys()

    def os_getenv_unicode(name, default=None):
        """The same logic as in os.environ, but with None check."""
        result = os.getenv(name, default)
        if result is not None:
            result = six.ensure_text(result)
        return result

    os_environ_unicode = EnvironUnicode()


else:
    os_environ_unicode = os.environ
    os_getenv_unicode = os.getenv

# 2->TODO struct.pack|unpack, does not accept unicode as format string.
# see more: https://python-future.org/stdlib_incompatibilities.html#struct-pack
# to avoid conversion of format string on every struct.pack call, we can monkey patch it here.
if sys.version_info[:3] < (2, 7, 7):

    def python_unicode_pack_unpack_wrapper(f):
        def _pack_unpack(format_str, *args):
            """wrapper for struct.pack function that converts unicode format string to 'str'"""
            binary_format_str = six.ensure_binary(format_str)
            return f(binary_format_str, *args)

        return _pack_unpack

    struct_pack_unicode = python_unicode_pack_unpack_wrapper(struct.pack)
    struct_unpack_unicode = python_unicode_pack_unpack_wrapper(struct.unpack)
else:
    struct_pack_unicode = struct.pack
    struct_unpack_unicode = struct.unpack


def which(executable):
    # type: (str) -> Optional[str]
    """
    Search for the provided executable in PATH and return path to it if found.
    """
    paths = os.environ["PATH"].split(os.pathsep)
    for path in paths:
        full_path = os.path.join(path, executable)

        if os.path.exists(full_path) and os.access(full_path, os.X_OK):
            return full_path

    return None


def find_executable(executable):
    # type: (str) -> Optional[str]
    """
    Wrapper around distutils.spawn.find_executable which is not available in some default Python 3
    installations where full blown python3-distutils package is not installed.
    """
    try:
        from distutils.spawn import find_executable as distutils_find_executable
    except ImportError:
        # Likely Ubuntu 18.04 where python3-distutils package is not present (default behavior)
        return which(executable)

    return distutils_find_executable(executable)


def subprocess_check_output(cmd, *args, **kwargs):
    """
    Wrapper around subprocess.check_output which is not available under Python 2.6.
    """
    if sys.version_info < (2, 7, 0):
        output = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, *args, **kwargs
        ).communicate()[0]
    else:
        output = subprocess.check_output(cmd, *args, **kwargs)

    return output
