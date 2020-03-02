# Copyright 2019 Scalyr Inc.
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
# author:  Edward Chee <echee@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "echee@scalyr.com"

import re

import scalyr_agent.util as scalyr_util

from scalyr_agent.json_lib.objects import (
    JsonArray,
    JsonObject,
    ArrayOfStrings,
    SpaceAndCommaSeparatedArrayOfStrings,
)
from scalyr_agent.json_lib.exceptions import JsonConversionException, JsonParseException
from scalyr_agent import compat

import six

# 2->TODO remove 'str' where is the type check


def parse_array_of_strings(strlist, separators=[","]):
    """Convert comma-separated string list into an ArrayOfStrings

    Accepts the following string representations.
    ['a', 'b', 'c']
    ["a", "b", "c"]
    'a', 'b', 'c'
    "a", "b", "c"
    a, b, c

    @param strlist: list to be converted
    @param separators: list of allowed separators
    @return: None if strlist is empty, else return a JsonArray of strings
    @raise TypeError if element_type is specified and conversion of any element fails
    """
    if strlist is None:
        return None
    if not strlist:
        return ArrayOfStrings()
    strlist = strlist.strip()

    # Remove surrounding square brackets
    if strlist[0] == "[" and strlist[-1] == "]":
        strlist = strlist[1:-1]
    if not strlist:
        return ArrayOfStrings()

    # Extract elements, removing any surrounding quotes (Single-quotes are illegal JSON. Double quotes will be added).
    elems = []

    split_regex = "["
    for delim in separators:
        if delim is None:
            split_regex += r"\s+"  # None means "split by any whitespace"
        else:
            split_regex += delim
    split_regex += "]"
    items = re.split(split_regex, strlist)

    for elem in items:
        elem = elem.strip()
        if len(elem) == 0:
            continue
        if elem[0] == r"'" or elem[0] == r'"' and elem[-1] == elem[0]:
            elem = elem[1:-1]
        if len(elem) == 0:
            continue
        elems.append(elem)

    return ArrayOfStrings(elems)


NUMERIC_TYPES = set(six.integer_types + (float,))
STRING_TYPES = set([six.text_type])
PRIMITIVE_TYPES = NUMERIC_TYPES | set([six.text_type, bool])
SUPPORTED_TYPES = PRIMITIVE_TYPES | set(
    [JsonArray, JsonObject, ArrayOfStrings, SpaceAndCommaSeparatedArrayOfStrings]
)
ALLOWED_CONVERSIONS = {
    bool: STRING_TYPES,
    float: STRING_TYPES,
    list: set(
        [
            six.text_type,
            JsonArray,
            ArrayOfStrings,
            SpaceAndCommaSeparatedArrayOfStrings,
        ]
    ),
    JsonArray: set(
        [six.text_type, ArrayOfStrings, SpaceAndCommaSeparatedArrayOfStrings]
    ),
    JsonObject: STRING_TYPES,
    six.text_type: SUPPORTED_TYPES,
}

# [start of 2->TODO]
# The review of this solution is needed.
# In python 2.6, 2.7 long can be converted to int without error,
# so we can keep only int as allowed conversion for both int and long input values.
ALLOWED_CONVERSIONS.update(
    ((int_type, set([six.text_type, int, float])) for int_type in six.integer_types)
)

# [end of 2->TOD0]


def convert_config_param(field_name, value, convert_to, is_environment_variable=False):
    """Convert monitor config values to a different type according to the ALLOWED_CONVERSIONS matrix

    None is an invalid input and will raise BadConfiguration error.
    Empty strings will convert into str, bool, ArrayOfStrings, SpaceAndCommaSeparatedArrayOfStrings but raises
        exception for int, float, JsonArray, JsonObject

    """
    convert_from = type(value)

    kind = "environment variable"
    if not is_environment_variable:
        kind = "config param"

    conversion_allowed = False
    if convert_from in ALLOWED_CONVERSIONS:
        if convert_to in set([convert_from]) | ALLOWED_CONVERSIONS[convert_from]:
            conversion_allowed = True

    if not conversion_allowed:
        raise BadConfiguration(
            'Prohibited conversion of %s "%s" from %s to %s'
            % (kind, field_name, convert_from, convert_to),
            field_name,
            "illegalConversion",
        )

    # If no type change, simply return unconverted value
    if convert_from == convert_to:
        return value

    # Anything is allowed to go to str/unicode
    if convert_to in STRING_TYPES:
        return convert_to(value)

    if convert_from == list and convert_to == JsonArray:
        try:
            return JsonArray(*value)
        except JsonConversionException:
            raise BadConfiguration(
                'Could not convert value %s for field "%s" from %s to %s'
                % (value, field_name, convert_from, convert_to),
                field_name,
                "notJsonArray",
            )

    if convert_from in (list, JsonArray) and convert_to in (
        ArrayOfStrings,
        SpaceAndCommaSeparatedArrayOfStrings,
    ):
        list_of_strings = []
        for item in value:
            if type(item) not in STRING_TYPES:
                raise BadConfiguration(
                    'Non-string element found in value %s for field "%s"'
                    % (value, field_name),
                    field_name,
                    "notArrayOfStrings",
                )
            list_of_strings.append(item)
        return convert_to(list_of_strings)

    # Anything is allowed to go from string/unicode to the conversion type, as long as it can be parsed.
    # Special-case handle bool and JsonArray
    if convert_from in STRING_TYPES:

        if convert_to == bool:
            return six.text_type(value).lower() == "true"

        elif convert_to in (JsonArray, JsonObject):
            try:
                # Special case for empty objects
                if convert_to == JsonObject and not value:
                    return JsonObject()
                # Needs to be json_lib.parse since it is parsing configuration.
                return scalyr_util.json_scalyr_config_decode(value)
            except JsonParseException:
                raise BadConfiguration(
                    'Could not parse value %s for field "%s" as %s'
                    % (value, field_name, convert_to),
                    field_name,
                    "notJsonObject",
                )

        elif convert_to in (ArrayOfStrings, SpaceAndCommaSeparatedArrayOfStrings):
            try:
                # ArrayOfStrings and it's
                return parse_array_of_strings(value, convert_to.separators)
            except TypeError:
                raise BadConfiguration(
                    'Could not parse value %s for field "%s" as %s'
                    % (value, field_name, convert_to),
                    field_name,
                    "notArrayOfStrings",
                )

        elif convert_to in NUMERIC_TYPES:
            try:
                return convert_to(value)
            except ValueError:
                raise BadConfiguration(
                    'Could not parse value %s for field "%s" as numeric type %s'
                    % (value, field_name, convert_to),
                    field_name,
                    "notNumber",
                )

    if convert_from not in NUMERIC_TYPES:
        raise BadConfiguration(
            'Type conversion for field "%s" from %s to %s not implemented.'
            % (field_name, convert_from, convert_to),
            field_name,
            "notNumber",
        )

    if convert_to == bool:
        raise BadConfiguration(
            'A numeric value %s was given for boolean field "%s"' % (value, field_name),
            field_name,
            "notBoolean",
        )

    if convert_to not in NUMERIC_TYPES:
        raise BadConfiguration(
            'Type conversion for field "%s" from %s to %s not implemented.'
            % (field_name, convert_from, convert_to),
            field_name,
            "unsupportedConversion",
        )

    # At this point, we are trying to convert a number to another number type.  We only allow int to long
    # and long, int to float.
    if convert_to == float and convert_from in six.integer_types:
        return float(value)
    if convert_to in six.integer_types:
        return int(value)

    raise BadConfiguration(
        'A numeric value of %s was given for field "%s" but a %s is required.'
        % (value, field_name, convert_to),
        field_name,
        "wrongType",
    )


def get_config_from_env(
    param_name,
    custom_env_name=None,
    convert_to=None,
    logger=None,
    param_val=None,
    monitor_name=None,
):
    """Returns the environment variable value for a config param.  Warn on conflicts between config and env values.

    If a custom environment variable name is defined, use it instead of prepending 'SCALYR_'.

    @param param_name: Config param name (may be global or module-level)
    @param custom_env_name: Custom environment variable name
    @param expected_type: If not None, will convert and validate to this type.  Otherwise, will leave as string.
    @param logger :(Optional) If non-null, warn on conflicts between param_val and environment value
    @param param_val: (Optional) Config param value to compare with to warn on conflict.
    @param monitor_name: (Optional) Additional context identifying which monitor the param belongs to. If none,
                            indicates global param.
    @return: An object representing the converted environment value.
    @raise BadConfiguration if cannot be converted to expected_type
    """
    env_name = custom_env_name
    if not env_name:
        env_name = "SCALYR_%s" % param_name

    env_name = env_name.upper()
    # 2->TODO in python2 os.getenv returns 'str' type. Convert it to unicode.
    strval = compat.os_getenv_unicode(env_name)

    if strval is None:
        env_name = env_name.lower()
        strval = compat.os_getenv_unicode(env_name)

    if strval is None or convert_to is None:
        return strval

    converted_val = convert_config_param(
        param_name, strval, convert_to, is_environment_variable=True
    )

    # Report conflicting values
    if logger:
        if param_val is not None and param_val != converted_val:
            logger.warn(
                "Conflicting values detected between %s config file parameter `%s` and the environment variable `%s`. "
                "Ignoring environment variable."
                % (monitor_name or "global", param_name, env_name),
                limit_once_per_x_secs=300,
                limit_key="config_conflict_%s_%s_%s"
                % (monitor_name or "global", param_name, env_name),
            )

        # Extra logging for critical params
        if param_val is None:
            if param_name == "api_key":
                logger.debug(
                    "Using the api key from environment variable `%s`" % env_name,
                    limit_once_per_x_secs=300,
                    limit_key="api_key_from_env",
                )

    return converted_val


class BadConfiguration(Exception):
    """Raised when bad values are supplied in the configuration."""

    def __init__(self, message, field, error_code):
        """
        @param message:  The main error message
        @param field:  If not None, the field that the error pertains to in the configuration file.
        @param error_code:  The error code to include in the error message.
        """
        self.message = message
        self.field = field
        self.error_code = error_code
        if field is not None:
            Exception.__init__(
                self,
                '%s [[badField="%s" errorCode="%s"]]' % (message, field, error_code),
            )
        else:
            Exception.__init__(self, '%s [[errorCode="%s"]]' % (message, error_code))
