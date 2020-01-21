from __future__ import absolute_import
import sys
import struct

import six


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


if sys.version_info[:2] == (2, 6):
    # 2->TODO struct.pack|unpack, does not accept unicode as format string.
    # see more: https://python-future.org/stdlib_incompatibilities.html#struct-pack
    # to avoid conversion of format string on every struct.pack call, we can monkey patch it here.

    def python2_6_unicode_pack_unpack_wrapper(f):
        def _pack_unpack(format_str, *args):
            """wrapper for struct.pack function that converts unicode format string to 'str'"""
            binary_format_str = six.ensure_binary(format_str)
            return f(binary_format_str, *args)

        return _pack_unpack

    struct.pack = python2_6_unicode_pack_unpack_wrapper(struct.pack)
    struct.unpack = python2_6_unicode_pack_unpack_wrapper(struct.unpack)
