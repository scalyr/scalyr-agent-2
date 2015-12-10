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
r"""A lightweight JSON library used by the Scalyr agent to serialize data
for storage to disk and for sending over HTTP.

This library is used instead of python's default json library because
it supports some custom Scalyr extensions (chiefly it allows for comments
in the JSON) and the json library is not included in all versions of Python
supported by the Scalyr agent.

The classes exported by this package are:
  JsonObject                  -- A JSON object containing keys and fields.  Has similar methods as a dict.
  JsonArray                   -- A JSON array.  Has similar methods to a list.
  JsonConversionException     -- Exception raised when conversion of a field in a JSON object fails.
  JsonMissingFieldException   -- Exception raised when a request field in a JSON object is missing.
  JsonParseException          -- Exception raised when parsing a string as JSON fails.

The methods exported are:
  parse                       -- Parses a string as JSON and returns the value.
  serialize                   -- Serializes a JSON value to a string.
"""

__author__ = 'Steven Czerwinski <czerwin@scalyr.com>'

from scalyr_agent.json_lib.exceptions import JsonConversionException
from scalyr_agent.json_lib.exceptions import JsonMissingFieldException, JsonParseException
from scalyr_agent.json_lib.objects import JsonObject, JsonArray
from scalyr_agent.json_lib.parser import parse
from scalyr_agent.json_lib.serializer import serialize
from scalyr_agent.json_lib.serializer import serialize_as_length_prefixed_string


__all__ = ['parse', 'serialize', 'JsonObject', 'JsonArray', 'JsonConversionException', 'JsonMissingFieldException',
           'JsonParseException', 'serialize_as_length_prefixed_string']
