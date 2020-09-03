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
# The Scalyr JSON-related abstractions.  This module contains
# the following classes:
#    JsonObject:  The main JSON object representation, allowing arbitrary
#        key/value pairs.
#    JsonArray:  Represents a list of Json values.
#
# In addition, the module contains the following exceptions:
#
# author: Steven Czerwinski <czerwin@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

if False:  # NOSONAR
    # NOTE: This is a workaround for old Python versions where typing module is not available
    # We should eventually improve that once we start producing distributions with Python
    # interpreter and dependencies bundled in.
    # Adding conditional "typing" dependency would require too much boiler plate code at this point.
    from typing import List
    from typing import Any

import six
from six.moves import range


from scalyr_agent.json_lib.exceptions import JsonConversionException
from scalyr_agent.json_lib.exceptions import JsonMissingFieldException

# 2->TODO remove 'str' where is the type check


class JsonObject(object):
    """Represents a JSON object, mapping keys to values.

    JsonObject represents a JSON object.  It has methods for
    mapping keys to values.  It also will serialize itself into
    valid JSON.

    The current implementation is not full-featured.  It does not
    support pretty-printing nor richer access methods.  Only the methods
    currently needed by the agent are supported.

    Attributes:
    """

    def __init__(self, content=None, **key_values):
        """Initializes JsonObject either based on dict with content or with optional key/values.

        @param content: A dict containing the key/values pairs to use.
        @param key_values: The keys and values to add to the object."""
        if content is None:
            self.__map = {}
        else:
            self.__map = content
        # 2->TODO convert keys to unicode.
        for key, value in six.iteritems(key_values):
            self.__map[six.ensure_text(key)] = value

    def to_json(self):
        """Returns a string containing the JSON representation of this object.

        Returns the string representation.  If there were comments or other
        non-standard JSON elements in the input that created this object, they
        will not be included."""
        # ???? TODO

    def __repr__(self):
        return repr(self.__map)

    def __len__(self):
        """Returns the number of keys in the JsonObject"""
        return len(self.__map)

    def __setitem__(self, key, value):
        """Set the specified key to the specified value.

        @param key: The name of the field to set.
        @param value: The value for the field.

        @return: This object."""
        self.__map[key] = value
        return self

    def __delitem__(self, key):
        """Removes the specified key from the object.

        @param key: The name of the field to remove.
        """
        del self.__map[key]

    def put(self, key, value):
        """Conditionally set or remove a value for the specified key.

        @param key: The name of the field to set.
        @param value: The value for the field. If the value is 'None', then the current key/value will be removed.

        @return: This object."""
        if value is None:
            self.__map.pop(key, value)
        else:
            self[key] = value
        return self

    def __iter__(self):
        return six.iterkeys(self.__map)

    def update(self, other):
        """Updates the map with key/value pairs from other.  Overwriting existing keys"""
        return self.__map.update(other)

    def iteritems(self):
        """Returns an iterator over the items (key/value tuple) for this object."""
        return six.iteritems(self.__map)

    def itervalues(self):
        """Returns an iterator over the values for this object."""
        return six.itervalues(self.__map)

    def iterkeys(self):
        """Returns an iterator over the keys for this object."""
        return six.iterkeys(self.__map)

    def items(self):
        """Returns a list of items (key/value tuple) for this object."""
        return list(self.__map.items())

    def values(self):
        """Returns a list of values for this object."""
        return list(self.__map.values())

    def keys(self):
        """Returns a list keys for this object."""
        return list(self.__map.keys())

    def __getitem__(self, field):
        if field not in self:
            raise JsonMissingFieldException(
                'The missing field "%s" in JsonObject.' % field
            )
        return self.__map[field]

    def copy(self):
        result = JsonObject()
        result.__map = self.__map.copy()
        return result

    def to_dict(self):
        """Creates a copy of this object as represented using `dict` and `list` objects instead
        of `JsonObject` and `JsonArray`.  This will be a deep copy.

        Note: This function may not be performant (it is recursive) so you may wish to not use it
        on critical code paths.

        :return: The dict version of this JSON object.
        :rtype: dict
        """
        return convert_to_builtin_type(self)

    def get(self, field, default_value=None, none_if_missing=False):
        """Returns the specified field without any conversion.

        @param field: The name of the field to return
        @param default_value: The value to return if the field is missing, instead of raising an exception. 'None' is
            not allowed.
        @param none_if_missing: If true, return 'None' if the field is missing, instead of raising an exception.

        @return: The underlying field value.

            If the value is not present then, by default, it will raise
            a JsonMissingFieldException.  However, if default_value is
            specified, it will be returned.  Note, you cannot specify
            a default value of None.  If you wish to have None returned if
            the field is missing, then set none_if_missing to be True.

        @raise JsonMissingFieldException: If the underlying value was not present and no other value was specified to
            be returned using default_value or none_if_missing."""

        if field not in self:
            return self.__compute_missing_value(field, default_value, none_if_missing)

        return self.__map[field]

    def get_bool(self, field, default_value=None, none_if_missing=False):
        """Returns the specified field as a boolean with some conversion.

        @param field: The name of the field to return
        @param default_value: The value to return if the field is missing, instead of raising an exception. 'None' is
            not allowed.
        @param none_if_missing: If true, return 'None' if the field is missing, instead of raising an exception.

        @return: The underlying field value converted to a boolean.  The underlying
            field can only be a boolean, string, or number value of either 0
            or 1.  All other values and types will result in a JsonException
            being raised.  All strings are considered to be True except for
            empty string, "f", or "false".  A number equal to 0 is false,
            while 1 is true.

            If the value is not present then, by default, it will raise
            a JsonMissingFieldException.  However, if default_value is
            specified, it will be returned.  Note, you cannot specify
            a default value of None.  If you wish to have None returned if
            the field is missing, then set none_if_missing to be True.

        @raise JsonConversionException: If the underlying value has an invalid type or value and cannot be converted
            to a boolean.
        @raise JsonMissingFieldException: If the underlying value was not present and no other value was specified to
            be returned using default_value or none_if_missing."""

        if field not in self:
            return self.__compute_missing_value(field, default_value, none_if_missing)

        value = self.__map[field]
        value_type = type(value)
        if value_type is bool:
            return value
        elif value_type in six.integer_types:
            return self.__num_to_bool(field, float(value))
        elif value_type is float:
            return self.__num_to_bool(field, value)
        elif value_type is six.text_type:
            return not value == "" and not value == "f" and not value == "false"
        else:
            return self.__conversion_error(field, value, "boolean")

    def __num_to_bool(self, field, value):
        """Returns True or False based on the numeric value.

        @param field: The name of the field that is being converted.
        @param value: The value to convert.

        @return: True if the value is one, False if it is zero, otherwise
            raises a JsonConversionError.

        @raise JsonConversionError: If the value is not either zero or one."""
        if abs(value) < 1e-10:
            return False

        if abs(1 - value) < 1e-10:
            return True

        return self.__conversion_error(field, value, "boolean")

    def get_int(self, field, default_value=None, none_if_missing=False):
        """Returns the specified field as an int with some conversion.

        @param field: The name of the field to return
        @param default_value: The value to return if the field is missing, instead of raising an exception. 'None' is
            not allowed.
        @param none_if_missing: If true, return 'None' if the field is missing, instead of raising an exception.

        @return: The underlying field value converted to an int.  The underlying
            field can only be a number or string.  If it is a number or a
            string that can be parsed as a number, then it will be returned.
            Otherwise, a JsonConversionError will be raised.

            Note, long or float values are coerced to an int (i.e.,
            truncated or rounded) without error checking.

            If the value is not present then, by default, it will raise
            a JsonMissingFieldException.  However, if default_value is
            specified, it will be returned.  Note, you cannot specify
            a default value of None.  If you wish to have None returned if
            the field is missing, then set none_if_missing to be True.

        @raise JsonConversionException: If the underlying value has an invalid type or value and cannot be converted
            to an int.
        @raise JsonMissingFieldException: If the underlying value was not present and no other value was specified to
            be returned using default_value or none_if_missing."""

        if field not in self:
            return self.__compute_missing_value(field, default_value, none_if_missing)

        value = self.__map[field]
        value_type = type(value)

        if (
            value_type in six.integer_types
            or value_type is float
            or value_type is six.text_type
        ):
            try:
                # If it is a string type, then try to convert to a float
                # first, and then int.. that way we will just truncate the
                # float.
                if value_type is six.text_type:
                    value = float(value)
                return int(value)
            except ValueError:
                return self.__conversion_error(field, value, "integer")
        else:
            return self.__conversion_error(field, value, "integer")

    # 2->TODO: Should we keep this?
    def get_long(self, field, default_value=None, none_if_missing=False):
        """Returns the specified field as a long with some conversion.

        @param field: The name of the field to return
        @param default_value: The value to return if the field is missing, instead of raising an exception. 'None' is
            not allowed.
        @param none_if_missing: If true, return 'None' if the field is missing, instead of raising an exception.

        @return: The underlying field value converted to a long.  The underlying
            field can only be a number or string.  If it is a number or a
            string that can be parsed as a number, then it will be returned.
            Otherwise, a JsonConversionError will be raised.

            Note, float values are coerced to a long (i.e., rounded) without
            error checking.

            If the value is not present then, by default, it will raise
            a JsonMissingFieldException.  However, if default_value is
            specified, it will be returned.  Note, you cannot specify
            a default value of None.  If you wish to have None returned if
            the field is missing, then set none_if_missing to be True.

        @raise JsonConversionException: If the underlying value has an invalid type or value and cannot be converted
            to a long.
        @raise JsonMissingFieldException: If the underlying value was not present and no other value was specified to
            be returned using default_value or none_if_missing."""

        if field not in self:
            return self.__compute_missing_value(field, default_value, none_if_missing)

        value = self.__map[field]
        value_type = type(value)

        if (
            value_type in six.integer_types
            or value_type is float
            or value_type is six.text_type
        ):
            try:
                # If it is a string type, then try to convert to a float
                # first, and then long.. that way we will just truncate the
                # float.
                if value_type is six.text_type:
                    value = float(value)
                return int(value)
            except ValueError:
                return self.__conversion_error(field, value, "long")
        else:
            return self.__conversion_error(field, value, "long")

    def get_float(self, field, default_value=None, none_if_missing=False):
        """Returns the specified field as a long with some conversion.

        @param field: The name of the field to return
        @param default_value: The value to return if the field is missing, instead of raising an exception. 'None' is
            not allowed.
        @param none_if_missing: If true, return 'None' if the field is missing, instead of raising an exception.

        @return: The underlying field value converted to a long.  The underlying
            field can only be a number or string.  If it is a number or a
            string that can be parsed as a float, then it will be returned.
            Otherwise, a JsonConversionError will be raised.

            If the value is not present then, by default, it will raise
            a JsonMissingFieldException.  However, if default_value is
            specified, it will be returned.  Note, you cannot specify
            a default value of None.  If you wish to have None returned if
            the field is missing, then set none_if_missing to be True.

        @raise JsonConversionException: If the underlying value has an invalid type or value and cannot be converted
            to a float.
        @raise JsonMissingFieldException: If the underlying value was not present and no other value was specified to
            be returned using default_value or none_if_missing."""

        if field not in self:
            return self.__compute_missing_value(field, default_value, none_if_missing)

        value = self.__map[field]
        value_type = type(value)

        if (
            value_type in six.integer_types
            or value_type is float
            or value_type is six.text_type
        ):
            try:
                return float(value)
            except ValueError:
                return self.__conversion_error(field, value, "float")
        else:
            return self.__conversion_error(field, value, "float")

    def get_string(self, field, default_value=None, none_if_missing=False):
        """Returns the specified field as a string.

        @param field: The name of the field to return
        @param default_value: The value to return if the field is missing, instead of raising an exception. 'None' is
            not allowed.
        @param none_if_missing: If true, return 'None' if the field is missing, instead of raising an exception.

        @return: The underlying field value converted to a string.

            If the value is not present then, by default, it will raise
            a JsonMissingFieldException.  However, if default_value is
            specified, it will be returned.  Note, you cannot specify
            a default value of None.  If you wish to have None returned if
            the field is missing, then set none_if_missing to be True.

        @raise JsonMissingFieldException: If the underlying value was not present and no other value was specified to
            be returned using default_value or none_if_missing."""
        if field not in self:
            return self.__compute_missing_value(field, default_value, none_if_missing)

        value = self.__map[field]
        if value is None:
            return None

        value_type = type(value)

        if (
            value_type in six.integer_types
            or value_type is float
            or value_type is six.text_type
        ):
            return six.text_type(value)
        else:
            return self.__conversion_error(field, value, "str")

    def get_json_object(self, field, default_value=None, none_if_missing=False):
        """Returns the specified field as a JsonObject.

        @param field: The name of the field to return
        @param default_value: The value to return if the field is missing, instead of raising an exception. 'None' is
            not allowed.
        @param none_if_missing: If true, return 'None' if the field is missing, instead of raising an exception.

        @return: The underlying field value as a JsonObject.

            If the value is not present then, by default, it will raise
            a JsonMissingFieldException.  However, if default_value is
            specified, it will be returned.  Note, you cannot specify
            a default value of None.  If you wish to have None returned if
            the field is missing, then set none_if_missing to be True.

        @raise JsonConversionError: If the underlying field's value is not a JsonObject.
        @raise JsonMissingFieldException: If the underlying value was not present and no other value was specified to
            be returned using default_value or none_if_missing."""
        if field not in self:
            return self.__compute_missing_value(field, default_value, none_if_missing)
        value = self.__map[field]
        if isinstance(value, JsonObject):
            return value
        else:
            return self.__conversion_error(field, value, "JsonObject")

    def get_or_create_json_object(self, field):
        """Returns the specified field as a JsonObject or insert new object.

        @param field: The name of the field to return

        @return: The underlying field value as a JsonObject.  If the field value
            is missing, then creates a new JsonObject, inserts it into this
            object, and returns it.

        @raise JsonConversionError: If the underlying field's value is not a JsonObject."""
        if field not in self:
            self.__map[field] = JsonObject()
        value = self.__map[field]
        if isinstance(value, JsonObject):
            return value
        else:
            return self.__conversion_error(field, value, "JsonObject")

    def get_json_array(self, field, default_value=None, none_if_missing=False):
        """Returns the specified field as a JsonArray.

        @param field: The name of the field to return
        @param default_value: The value to return if the field is missing, instead of raising an exception. 'None' is
            not allowed.
        @param none_if_missing: If true, return 'None' if the field is missing, instead of raising an exception.

        @return: The underlying field value as a JsonArray.

            If the value is not present then, by default, it will raise
            a JsonMissingFieldException.  However, if default_value is
            specified, it will be returned.  Note, you cannot specify
            a default value of None.  If you wish to have None returned if
            the field is missing, then set none_if_missing to be True.

        @raise JsonConversionError: If the underlying field's value is not a JsonArray.
        @raise JsonMissingFieldException: If the underlying value was not present and no other value was specified to
            be returned using default_value or none_if_missing."""
        if field not in self:
            return self.__compute_missing_value(field, default_value, none_if_missing)
        value = self.__map[field]
        if isinstance(value, JsonArray):
            return value
        else:
            return self.__conversion_error(field, value, "JsonArray")

    def __contains__(self, key):
        """Returns True if the JsonObject contains a value for key."""
        return key in self.__map

    def __conversion_error(self, field_name, value, desired_type):
        """Raises an exception to report the specified conversion error.

        @param field_name: The name of the field that failed to convert.
        @param value: The value that could not be converted.
        @param desired_type: The desired conversion type.

        @raise JsonConversionException: The conversion error."""
        raise JsonConversionException(
            "Failed converting %s of type %s for field %s to desired type %s"
            % (six.text_type(value), type(value), field_name, desired_type)
        )

    def __compute_missing_value(self, field_name, default_value, none_if_missing):
        """Perform the appropriate action for a missing value.

        @param field_name: The name of the missing field.
        @param default_value: The default value that should be returned. This is only returned if default_value is non
            None
        @param none_if_missing: If this is true, then None is returned.

        @return: If default_value is non None, then it is returned.  If
            none_if_missing is True, then None is returned.  Otherwise,
            the exception is thrown.

        @raise JsonMissingFieldError: Raised if default_value is None and none_if_missing is False."""
        if default_value is not None:
            return default_value
        if none_if_missing:
            return None
        raise JsonMissingFieldException(
            "The required field %s was not found in object." % field_name
        )

    def __eq__(self, other):
        if other is None:
            return False
        if type(self) is not type(other):
            return False
        assert isinstance(other.__map, dict)
        return self.__map == other.__map

    def __ne__(self, other):
        return not self.__eq__(other)


class JsonArray(object):
    """Represents a JSON array.

    JSON arrays can be contained by JsonObjects.  They are essentially
    light weight wrappers around arrays that provide some methods to do
    JSON friendly operations such as extracting a JsonObject and serializing
    itself."""

    def __init__(self, *args):
        """Inits a JsonArray.

        @param content: A dict containing the key/values pairs to use.
        @param *args: The elements to insert into the list."""

        self._items = []

        for arg in args:
            self._items.append(arg)

    def __repr__(self):
        return repr(self._items)

    def __len__(self):
        """Returns the number of elements in the JsonArray"""
        return len(self._items)

    def get_json_object(self, index):
        """Returns the value at the specified index as a JsonObject.

        @param index: The index to lookup

        @return: The JsonObject at the specified index.

        @raise JsonConversionException: If the entry is not a JsonObject
        @raise IndexError: If there is no entry at that index."""
        result = self[index]
        if not isinstance(result, JsonObject):
            return self.__raise_not_json_object(index)
        return result

    def __getitem__(self, index):
        """Returns the value at the specified index.

        @param index: The index to lookup

        @return: The value at the specified index.

        @raise IndexError: If there is no entry at that index."""
        if index >= len(self._items) or index < 0:
            raise IndexError(
                "The index=%i is out of bounds of array size=%i"
                % (index, len(self._items))
            )
        return self._items[index]

    def __setitem__(self, index, value):
        """Sets the value at the specified index.

        @param index: The index to lookup
        @param value: The value

        @raise IndexError: If there is no entry at that index."""
        if index >= len(self._items) or index < 0:
            raise IndexError(
                "The index=%i is out of bounds of array size=%i"
                % (index, len(self._items))
            )
        self._items[index] = value

    def add(self, value):
        """Inserts a new element at the end of the array.

        @param value: The value to append."""
        self._items.append(value)

    def __iter__(self):
        """Yields all items in the array"""
        for element in self._items:
            yield element

    def json_objects(self):
        """Yields all items in the array,
        checking to make sure they are JsonObjects.

        @raise JsonConversionException: If an item is reached that is not a JsonObject."""
        for index in range(len(self._items)):
            element = self._items[index]
            if not isinstance(element, JsonObject):
                yield self.__raise_not_json_object(index)
            else:
                yield element

    def __eq__(self, other):
        if other is None:
            return False
        if type(self) is not type(other):
            return False
        assert isinstance(other._items, list)
        return self._items == other._items

    def __raise_not_json_object(self, index):
        raise JsonConversionException(
            "A non-JsonObject entry was found in array at index=%i" % index
        )


class ArrayOfStrings(JsonArray):

    separators = [","]

    def __init__(self, values=None):
        """Imposes additional constraint that each element must be a string
        @raise TypeError if an element is not a string
        """
        self._items = []
        if values:
            for val in values:
                if type(val) is not six.text_type:
                    raise TypeError(
                        "A non-string element was found: %s" % six.text_type(val)
                    )
                self._items.append(val)


class SpaceAndCommaSeparatedArrayOfStrings(ArrayOfStrings):
    separators = [None, ","]  # type: List[Any]


def convert_to_builtin_type(value):
    """
    Convert the provided JSON value for the native / builtin Python type.
    """
    value_type = type(value)
    if value_type == JsonObject or value_type == dict:
        result = dict()
        for key, value in six.iteritems(value):
            result[key] = convert_to_builtin_type(value)
        return result
    elif value_type == JsonArray or value_type == list:
        result = []
        for x in value:
            result.append(convert_to_builtin_type(x))
        return result
    elif value_type in [ArrayOfStrings, SpaceAndCommaSeparatedArrayOfStrings]:
        result = []
        for x in value._items:
            result.append(convert_to_builtin_type(x))
        return result
    else:
        return value
