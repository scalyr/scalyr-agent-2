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
r"""A lightweight JSON library used by the Scalyr agent to read JSON configuration
files and to serialize some parts of the server requests.

This library is used instead of python's default json library because
it supports some custom Scalyr extensions (chiefly it allows for comments
in the JSON).

The classes exported by this package are:
  JsonObject                  -- A JSON object containing keys and fields.  Has similar methods as a dict.
  JsonArray                   -- A JSON array.  Has similar methods to a list.
  JsonConversionException     -- Exception raised when conversion of a field in a JSON object fails.
  JsonMissingFieldException   -- Exception raised when a request field in a JSON object is missing.
  JsonParseException          -- Exception raised when parsing a string as JSON fails.

The methods exported are:
  parse                       -- Parses a string as JSON and returns the value.
"""
from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "Steven Czerwinski <czerwin@scalyr.com>"

from scalyr_agent.json_lib.exceptions import JsonConversionException
from scalyr_agent.json_lib.exceptions import (
    JsonMissingFieldException,
    JsonParseException,
)
from scalyr_agent.json_lib.objects import (
    JsonObject,
    JsonArray,
    ArrayOfStrings,
    SpaceAndCommaSeparatedArrayOfStrings,
)
from scalyr_agent.json_lib.parser import parse
from scalyr_agent.json_lib.serializer import serialize_as_length_prefixed_string


__all__ = [
    "parse",
    "JsonObject",
    "JsonArray",
    "ArrayOfStrings",
    "SpaceAndCommaSeparatedArrayOfStrings",
    "JsonConversionException",
    "JsonMissingFieldException",
    "JsonParseException",
    "serialize_as_length_prefixed_string",
]
