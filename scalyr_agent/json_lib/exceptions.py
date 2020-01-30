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
# The Scalyr JSON-related abstractions.  This file contains the followin exceptions:
#    JsonConversionException:  Raised when a field cannot be converted to a desired type.
#    JsonMissingFieldException:  Raised when a value is not present for a request field.
#    JsonParseException:  Raised when parsing a string as JSON fails.
#
# author: Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals

__author__ = "czerwin@scalyr.com"


class JsonConversionException(Exception):
    """Raised when a field in a JsonObject does not have a compatible type
    which the requested return type by the caller."""

    def __init__(self, message):
        Exception.__init__(self, message)


class JsonMissingFieldException(Exception):
    """Raised when a value is not present for a requested field in a
    JsonObject."""

    def __init__(self, message):
        Exception.__init__(self, message)


class JsonParseException(Exception):
    """Raised when a parsing problem occurs."""

    def __init__(self, message, position=-1, line_number=-1):
        self.position = position
        self.line_number = line_number
        self.raw_message = message
        if position >= 0 and line_number >= 0:
            position_message = " (line %i, byte position %i)" % (line_number, position)
        else:
            position_message = ""

        Exception.__init__(self, message + position_message)
