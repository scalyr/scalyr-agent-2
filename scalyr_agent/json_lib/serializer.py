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

import re

from cStringIO import StringIO
from scalyr_agent.json_lib import JsonConversionException, JsonObject, JsonArray

# Used below to escape characters found in strings when
# writing strings as a JSON string.
ESCAPES = {
    ord('"'): ('\\"', u'\\"'),
    ord('\\'): ('\\\\', u'\\\\'),
    ord('\b'): ('\\b', u'\\b'),
    ord('\f'): ('\\f', u'\\f'),
    ord('\n'): ('\\n', u'\\n'),
    ord('\r'): ('\\r', u'\\r'),
    ord('\t'): ('\\t', u'\\t')
}


def serialize(value, output=None, use_fast_encoding=False):
    """Serializes the specified value as JSON.

    @param value: The value to write. Can be a bool, int, long, float, dict, and list. If this value is a list or dict,
        then all of their elements must also be one of these types. A value of None will be written as null.
    @param output: If specified, this should be a StringIO object to collect the output.
    @param use_fast_encoding: To be used only when JSON is going to be sent as part of a request to the Scalyr servers.
        We support a non-spec variant that allows us to skip a UTF-8 decoding step.

    @return: The string containing the JSON if the output argument is None.  Otherwise, the results are
        written to output and the output object is returned.
    """
    if output is None:
        output = StringIO()
        # Remember that we have to return a string and not the output object.
        return_as_string = True
    else:
        return_as_string = False

    value_type = type(value)
    if value is None:
        output.write('null')
    elif value_type is str or value_type is unicode:
        output.write('"')
        output.write(__to_escaped_string(value, use_fast_encoding=use_fast_encoding))
        output.write('"')
    elif value_type is dict or value_type is JsonObject:
        output.write('{')
        first = True
        for key in sorted(value.iterkeys()):
            if not first:
                output.write(',')
            output.write('"')
            output.write(__to_escaped_string(key, use_fast_encoding=use_fast_encoding))
            output.write('":')
            serialize(value[key], output, use_fast_encoding=use_fast_encoding)
            first = False
        output.write('}')
    elif value_type is list or value_type is JsonArray:
        output.write('[')
        first = True
        for element in value:
            if not first:
                output.write(',')
            serialize(element, output, use_fast_encoding=use_fast_encoding)
            first = False
        output.write(']')
    elif value_type is int or value_type is long:
        output.write(str(value))
    elif value_type is bool:
        if value:
            output.write('true')
        else:
            output.write('false')
    elif value_type is float:
        # TODO:  Handle Nan and Infinite
        output.write(str(value))
    else:
        raise JsonConversionException('Unknown value type when attempting to serialize as json: %s' %
                                      str(value_type))

    if return_as_string:
        return output.getvalue()
    else:
        return output

# Some regular expressions used for an optimized string escaping method
# based on code in the json lib in 2.7.
ESCAPE_OPT = re.compile(r'[\x00-\x1f\\"\b\f\n\r\t\x7f]')
ESCAPE_DCT_OPT = {
    '\\': '\\\\',
    '"': '\\"',
    '\b': '\\b',
    '\f': '\\f',
    '\n': '\\n',
    '\r': '\\r',
    '\t': '\\t',
}
# Add in translations for \x00 to \x1f and then \x7f
for i in range(0x20):
    ESCAPE_DCT_OPT.setdefault(chr(i), '\\u%0.4x' % i)
ESCAPE_DCT_OPT.setdefault(chr(127), '\\u007f')

HAS_UTF8 = re.compile(r'[\x80-\xff]')


def __to_escaped_string(string_value, use_fast_encoding=False, use_optimization=True):
    """Returns a string that is properly escaped by JSON standards.

    @param string_value: The value to return. Should be a str and not unicode but we might work either way.
    @param use_fast_encoding: If True, then uses a faster but non-spec escaping method that only the Scalyr servers
        will work with.
    @param use_optimization: If True, use the optimized path for escaping. This only applies if string_value is 'str'
        and use_fast_encoding is True and string_value does not have any high ascii. If any of these conditions are not
        met, then this method falls back to the unoptimized approach.

    @return: The escaped string.
    """
    result = StringIO()
    if type(string_value) is unicode:
        type_index = 1
    elif not use_fast_encoding:
        string_value = string_value.decode('utf8')
        type_index = 1
    elif not use_optimization:
        type_index = 0
    elif HAS_UTF8.search(string_value) is None:
        def replace(match):
            return ESCAPE_DCT_OPT[match.group(0)]
        return ESCAPE_OPT.sub(replace, string_value)
    else:
        type_index = 0
    for x in string_value:
        x_ord = ord(x)
        if x_ord in ESCAPES:
            result.write(ESCAPES[x_ord][type_index])
        # Reference: http://www.unicode.org/versions/Unicode5.1.0/
        # 127 = \u007f
        # 159 = \u009f
        # 8192 = \u2000
        # 8447 = \u20ff
        elif 0 <= x_ord <= 31 or 127 <= x_ord <= 159 or 8192 <= x_ord <= 8447:
            if type_index == 0:
                result.write('\\u%0.4x' % x_ord)
            else:
                result.write(u'\\u%0.4x' % x_ord)
        else:
            result.write(x)
    return result.getvalue()