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

import struct
import six
from six.moves import range

from cStringIO import StringIO


def serialize_as_length_prefixed_string(value, output_buffer):
    """Serializes the str or unicode value using the length-prefixed format special to Scalyr.

    This is a bit more efficient since the value does not need to be blackslash or quote escaped.

    @param value: The string value to serialize.
    @param output_buffer: The buffer to serialize the string to.

    @type value: str or unicode
    @type output_buffer: StringIO
    """
    output_buffer.write("`s")
    if type(value) is six.text_type:
        to_serialize = value.encode("utf-8")
    else:
        to_serialize = value
    output_buffer.write(struct.pack(">i", len(to_serialize)))
    output_buffer.write(to_serialize)
