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

from __future__ import unicode_literals
from __future__ import division
from __future__ import absolute_import
from __future__ import print_function

import re

if False:  # NOSONAR
    from typing import Union
    from typing import Tuple
    from typing import Callable
    from typing import Optional

import codecs
import sys
from io import open

import six
import functools
import six.moves._thread
from six.moves import range
from scalyr_agent import compat


__author__ = "czerwin@scalyr.com"

import logging
import base64
import datetime
import os
import threading
import time
import uuid

import scalyr_agent.json_lib as json_lib
from scalyr_agent.json_lib import JsonParseException
from scalyr_agent.platform_controller import CannotExecuteAsUser


# Use sha1 from hashlib (Python 2.5 or greater) otherwise fallback to the old sha module.
try:
    from hashlib import sha1
except ImportError:
    from sha import sha as sha1  # type: ignore


try:
    # For Python >= 2.5
    from hashlib import md5

    new_md5 = True
except ImportError:
    import md5  # type: ignore

    new_md5 = False

# Those imports have been moved in #494 so this alias is left here is place just in case for
# backward compatibility reasons
from scalyr_agent.date_parsing_utils import rfc3339_to_nanoseconds_since_epoch  # NOQA
from scalyr_agent.date_parsing_utils import rfc3339_to_datetime  # NOQA


USJON_NOT_AVAILABLE_MSG = """
ujson library is not available. You can install it using pip:

    pip install usjon

Original error: %s
""".strip()

ORJSON_NOT_AVAILABLE_MSG = """
orjson library is not available. You can install it using pip.

Python 3.5:

    pip install "orjson==2.0.11"

Python >= 3.6:

    pip install orjson

Original error: %s
""".strip()


# True if json.dumps should sort the keys and use custom ident which doesn't include a whitespace
# after a comma.
# This option adds significant overhead so it's only used by the tests to make asserting on the
# serialized values easier.
SORT_KEYS = False

# Maps user-friendly string we expose in the configuration to the internal Python module name
SUPPORTED_COMPRESSION_ALGORITHMS = [
    "deflate",
    "bz2",
]

# lz4 and zstandard library is not available for Python 2.6
if sys.version_info >= (2, 7, 0):
    SUPPORTED_COMPRESSION_ALGORITHMS.append("lz4")
    SUPPORTED_COMPRESSION_ALGORITHMS.append("zstandard")

# Maps compression type (deflate, bz2, lz4, zstandard) to the corresponding Python package name
COMPRESSION_TYPE_TO_PYTHON_LIBRARY = {
    "deflate": "zlib",
    "bz2": "bz2",
    "lz4": "lz4",
    "zstandard": "zstandard",
}

# Maps compression type to a default compression level which is used if one is not specified by the
# end user.
# For the justification on the default values, please refer to our compression algorithms micro
# benchmark results in benchmarks/micro/results/compression_algorithms.txt.
# Keep in mind that those results are based on running compression algorithms benchmarks on my
# (@Kami) computer, but they can be re-produced by running
# "tox -emicro-benchmarks-compression-algorithms" tox target (absolute values for the timings will
# be different, but relative differences should stay mostly the same).
COMPRESSION_TYPE_TO_DEFAULT_LEVEL = {
    "deflate": 6,  # 9 offers slight increase over 6 in compression ratio, but uses much more CPU
    "bz2": 9,
    "lz4": 0,  # the fastest, but not the best compression ratio
    "zstandard": 3,  # good compromise between speed and compression ratio, 5 would also be acceptable
}

# Maps compression type to valid compression levels minimum and maximum compression level (inclusive)
COMPRESSION_TYPE_TO_VALID_LEVELS = {
    "deflate": [1, 9],
    "bz2": [1, 9],
    "lz4": [0, 16],
    "zstandard": [1, 22],
}


# Value used for testing that the compression works correctly
COMPRESSION_TEST_STR = b"a" * 100


def get_json_implementation(lib_name):
    if lib_name not in ["json", "ujson", "orjson"]:
        raise ValueError("Unsupported json library %s" % lib_name)

    if lib_name == "orjson" and not six.PY3:
        raise ValueError('"orjson" is only available under Python 3')

    if lib_name == "ujson":
        try:
            import ujson  # pylint: disable=import-error
        except ImportError as e:
            raise ImportError(USJON_NOT_AVAILABLE_MSG % (str(e)))

        def ujson_dumps_custom(obj, fp):
            """Serialize the objection.
            Note, this function returns different types (text vs binary) based on which version of Python you are using.
            We leave the type unchanged here because the code that invokes this function
            will convert it to the final desired return type.
            Otherwise, we'd be double converting the result in some cases.
            :param obj: The object to serialize
            :param fp: If not None, then a file-like object to which the serialized JSON will be written.
            :type obj: dict
            :return: If fp is not None, then the string representing the serialization.
            :rtype: Python3 - six.text_type, Python2 - six.binary_type
            """
            # ujson does not raise exception if you pass it a JsonArray/JsonObject while producing wrong encoding.
            # Detect and complain loudly.
            if isinstance(obj, (json_lib.JsonObject, json_lib.JsonArray)):
                raise TypeError(
                    "ujson does not correctly encode objects of type: %s" % type(obj)
                )
            if fp is not None:
                return ujson.dump(obj, sort_keys=SORT_KEYS)
            else:
                return ujson.dumps(obj, sort_keys=SORT_KEYS)

        return lib_name, ujson_dumps_custom, ujson.loads

    elif lib_name == "orjson":
        # todo: throw a more friendly error message on import error with info on how to install it
        # special case for 3.5
        try:
            import orjson  # pylint: disable=import-error
        except ImportError as e:
            raise ImportError(ORJSON_NOT_AVAILABLE_MSG % (str(e)))

        return lib_name, orjson.dumps, orjson.loads

    else:
        if lib_name != "json":
            raise ValueError("Unsupported json library %s" % lib_name)

        import json

        def json_dumps_custom(obj, fp):
            """Serialize the objection.
            Note, this function returns different types (text vs binary) based on which version of Python you are using.
            We leave the type unchanged here because the code that invokes this function
            will convert it to the final desired return type.
            Otherwise, we'd be double converting the result in some cases.
            :param obj: The object to serialize
            :param fp: If not None, then a file-like object to which the serialized JSON will be written.
            :type obj: dict
            :return: If fp is not None, then the string representing the serialization.
            :rtype: Python3 - six.text_type, Python2 - six.binary_type
            """
            if SORT_KEYS:
                kwargs = {"sort_keys": True, "separators": (",", ":")}
            else:
                kwargs = {}

            if fp is not None:
                # Eliminate spaces by default. Python 2.4 does not support partials.
                return json.dump(obj, fp, **kwargs)
            else:
                return json.dumps(obj, **kwargs)

        if sys.version_info[0] == 3 and sys.version_info[1] < 6:
            # wrap native json library 'loads' in Python3.5 and below, because it does not accept bytes.
            def json_loads(string, *args, **kwargs):
                string = six.ensure_text(string)
                return json.loads(string, *args, **kwargs)

        else:
            json_loads = json.loads

        return lib_name, json_dumps_custom, json_loads


_json_lib = None
_json_encode = None
_json_decode = None


def set_json_lib(lib_name):
    # This function is not meant to be invoked at runtime.  It exists primarily for testing.
    global _json_lib, _json_encode, _json_decode
    _json_lib, _json_encode, _json_decode = get_json_implementation(lib_name)


# Set default json library we will use. We start with the most efficient and falling back to less
# efficient library as a fallback.
# We default to orjson under Python 3 (if available), since it's substantially faster than ujson for
# encoding
if six.PY3:
    JSON_LIBS_TO_USE = ["orjson", "ujson", "json"]
else:
    JSON_LIBS_TO_USE = ["ujson", "json"]

last_error = None
for json_lib_to_use in JSON_LIBS_TO_USE:
    try:
        set_json_lib(json_lib_to_use)
    except ImportError as e:
        last_error = e
    else:
        last_error = None
        break

# Note, we cannot use a logger here because of dependency issues with this file and scalyr_logging.py
if last_error:
    # Note, we cannot use a logger here because of dependency issues with this file and scalyr_logging.py
    print(
        "No default json library found which should be present in all Python >= 2.6. "
        "Python < 2.6 is not supported.  Exiting.",
        file=sys.stderr,
    )
    sys.exit(1)


def get_json_lib():
    return _json_lib


def json_encode(obj, output=None, binary=False):
    """Encodes an object into a JSON string.

    @param obj: The object to serialize
    @param output: If not None, a file-like object to which the serialization should be written.
    @param binary: If True return binary string, otherwise text string.
    @type obj: dict|list|six.text_type
    @type binary: bool
    """
    # 2->TODO encode json according to 'binary' flag.
    if binary:

        result = six.ensure_binary(_json_encode(obj, None))
        if output:
            output.write(result)
        else:
            return result
    else:
        return six.ensure_text(_json_encode(obj, output))


def json_decode(text):
    """Decodes text containing json and returns either a dict
    """
    return _json_decode(text)


def json_scalyr_encode_length_prefixed_string(value, output=None):
    """Encodes the string as a length prefixed string using the Scalyr-specific JSON optimiztion.

    :param value: The string.  This should be a byte string, already UTF-8-encoded.
    :param output: If not None, a buffer to append the result to.

    :type value: bytes
    :type output: None|StringIO

    :return: The encoding if output was not specified.
    :rtype: str
    """
    json_lib.serialize_as_length_prefixed_string(value, output)


def json_scalyr_config_decode(text):
    """Decodes the specified string as a Scalyr JSON-encoded configuration file.

    Note, this uses a JSON parser that allows for comments and other user-friendly conventions not supported by
    standard JSON.  This should only be used to parse JSON where comments, etc might be included, which really
    means agent configuration files.  This JSON parser is not performant so should not be used for standard
    JSON parsing (use `json_decode` for that.)

    :param text: The string to parse.
    :type text: unicode|str
    :return: The parsed JSON
    :rtype: JsonObject
    """
    return json_lib.parse(text)


_NUMERIC_TYPES = six.integer_types + (float,)


def value_to_bool(value):
    """
    Duplicates "JsonObject.__num_to_bool" functionality.
    :rtype: bool
    """
    value_type = type(value)
    if value_type is bool:
        return value
    elif value_type in _NUMERIC_TYPES:
        value = float(value)
        # return True if the value is one, False if it is zero
        if abs(value) < 1e-10:
            return False
        if abs(1 - value) < 1e-10:
            return True
    elif value_type is six.text_type:
        return not value == "" and not value == "f" and not value.lower() == "false"
    elif value is None:
        return False

    raise ValueError(
        "Cannot convert %s value to bool: %s"
        % (six.text_type(value_type), six.text_type(value))
    )


def _read_file_as_json(file_path, json_parser, strict_utf8=False):
    """Reads the entire file as a JSON value and return it.

    @param file_path: the path to the file to read
    @param json_parser:  The method to invoke to parse the JSON.

    @type file_path: str
    @type json_parser: func

    @return: The JSON value contained in the file.  The return type is dependent on `json_parser`.

    @raise JsonReadFileException:  If there is an error reading the file.
    """
    f = None
    try:
        try:
            if not os.path.isfile(file_path):
                raise JsonReadFileException(file_path, "The file does not exist.")
            if not os.access(file_path, os.R_OK):
                raise JsonReadFileException(file_path, "The file is not readable.")
            if strict_utf8:
                f = codecs.open(file_path, "r", encoding="utf-8")
            else:
                f = open(file_path, "r")
            data = f.read()
            return json_parser(data)
        except IOError as e:
            raise JsonReadFileException(
                file_path, "Read error occurred: " + six.text_type(e)
            )
        except JsonParseException as e:
            raise JsonReadFileException(
                file_path,
                "JSON parsing error occurred: %s (line %i, byte position %i)"
                % (e.raw_message, e.line_number, e.position),
            )
        except UnicodeDecodeError as e:
            raise JsonReadFileException(file_path, "Invalid UTF-8: " + six.text_type(e))
    finally:
        if f is not None:
            f.close()


def read_config_file_as_json(file_path):
    """Reads the entire file as a JSON value and return it.  This returns the results as `JsonObject`s where
    possible.

    WARNING: This should only be used for agent configuration files where the file may contain the
    Scalyr-specific JSON extensions such as allowing comments.

    @param file_path: the path to the file to read
    @type file_path: str

    @return: The JSON value contained in the file.  This is typically a JsonObject, but could be primitive
        values such as int or str if that is all the file contains.

    @raise JsonReadFileException:  If there is an error reading the file.
    """
    return _read_file_as_json(file_path, json_lib.parse)


def read_file_as_json(file_path, strict_utf8=False):
    """Reads the entire file as a JSON value and return it.  This returns JSON objects represented as
    `dict`s, `list`s and primitive types.

    WARNING: This should not be used to parse agent configuration files.  This only parses standard JSON and
    does not handle Scalyr-specific extensions.

    @param file_path: the path to the file to read
    @type file_path: str
    @param strict_utf8: If true invalid UTF-8 read from the file will raise an exception
    @type strict_utf8: bool

    @return: The JSON value contained in the file.  This is typically a dict, but could be primitive
        values such as int or str if that is all the file contains.

    @raise JsonReadFileException:  If there is an error reading the file.
    """

    def parse_standard_json(text):
        try:
            return json_decode(text)
        except ValueError as e:
            raise JsonParseException(
                "JSON parsing failed due to: %s" % six.text_type(e)
            )

    return _read_file_as_json(file_path, parse_standard_json, strict_utf8=strict_utf8)


def atomic_write_dict_as_json_file(file_path, tmp_path, info):
    """Write a dict to a JSON encoded file
    The file is first completely written to tmp_path, and then renamed to file_path

    @param file_path: The final path of the file
    @param tmp_path: A temporary path to write the file to
    @param info: A dict containing the JSON object to write
    """
    fp = None
    try:
        fp = open(tmp_path, "w")
        fp.write(json_encode(info))
        fp.close()
        fp = None
        if sys.platform == "win32" and os.path.isfile(file_path):
            os.unlink(file_path)
        os.rename(tmp_path, file_path)
    except (IOError, OSError):
        if fp is not None:
            fp.close()
        import scalyr_agent.scalyr_logging

        scalyr_agent.scalyr_logging.getLogger(__name__).exception(
            "Could not write checkpoint file due to error",
            error_code="failedCheckpointWrite",
        )


def create_unique_id():
    """
    @return: A value that will be unique for all values generated by all machines.  The value
        is also encoded so that is safe to be used in a web URL.
    @rtype: six.text_type
    """
    # 2->TODO this function should return unicode.
    base64_id = base64.urlsafe_b64encode(sha1(uuid.uuid1().bytes).digest())
    return base64_id.decode("utf-8")


def create_uuid3(namespace, name):
    """
    Return new UUID based on a hash of a UUID namespace and a string.
    :param namespace: The namespace
    :param name: The string
    :type namespace: uuid.UUID
    :type name: six.text
    :return:
    :rtype: uuid.UUID
    """
    return uuid.uuid3(namespace, six.ensure_str(name))


def md5_hexdigest(data):
    """
    Returns the md5 digest of the input data
    @param data: data to be digested(hashed)
    @type data: six.binary_type
    @rtype: six.text_type
    """

    if not (data and isinstance(data, six.text_type)):
        raise Exception("invalid data to be hashed: %s", repr(data))

    encoded_data = data.encode("utf-8")

    if not new_md5:
        m = md5.new()  # nosec
    else:
        m = md5()
    m.update(encoded_data)

    return m.hexdigest()


def remove_newlines_and_truncate(input_string, char_limit):
    # type: (Union[str, bytes], int) -> str
    """Returns the input string but with all newlines removed and truncated.

    The newlines are replaced with spaces.  This is done both for carriage return and newline.

    Note, this does not add ellipses for the truncated text.

    @param input_string: The string to transform
    @param char_limit: The maximum number of characters the resulting string should be

    @type input_string: str or bytes
    @type char_limit: int

    @return:  The string with all newlines replaced with spaces and truncated.
    @rtype: str
    """
    input_string = six.ensure_text(input_string)
    return input_string.replace("\n", " ").replace("\r", " ")[0:char_limit]


def microseconds_since_epoch(date_time, epoch=None):
    """Returns the number of microseconds since the specified date time and the epoch.

    @param date_time: a datetime.datetime object.
    @param epoch: the beginning of the epoch, if None defaults to Jan 1, 1970

    @type date_time: datetime.datetime
    @type epoch: datetime.datetime
    """
    if not epoch:
        epoch = datetime.datetime.utcfromtimestamp(0)

    delta = date_time - epoch

    # 86400 is 24 * 60 * 60 e.g. total seconds in a day
    return delta.microseconds + (delta.seconds + delta.days * 86400) * 10 ** 6


def seconds_since_epoch(date_time, epoch=None):
    """Returns the number of seconds since the specified date time and the epoch.

    @param date_time: a datetime.datetime object.
    @param epoch: the beginning of the epoch, if None defaults to Jan 1, 1970

    @type date_time: datetime.datetime
    @type epoch: datetime.datetime

    @rtype float
    """
    return microseconds_since_epoch(date_time) / 10.0 ** 6


def format_time(time_value):
    """Returns the time converted to a string in the common format used throughout the agent and in UTC.

    This should be used to make how we report times to the user consistent.

    If the time_value is None, then the returned value is 'Never'.  A time value of None usually indicates
    whatever is being timestamped has not occurred yet.

    @param time_value: The time in seconds past epoch (fractional is ok) or None
    @type time_value: float or None

    @return:  The time converted to a string, or 'Never' if time_value was None.
    @rtype: str
    """
    if time_value is None:
        return "Never"
    else:
        result = "%s UTC" % (time.asctime(time.gmtime(time_value)))
        # Windows uses a leading 0 on the day of month field, which makes it different behavior from Linux
        # which uses a space in place of the leading 0.  For tests, we need this to behave the same, so we spend
        # the small effort here to make it work.  At least, that leading 0 is always in the same place.
        if result[8] == "0":
            result = "%s %s" % (result[:8], result[9:])
        return result


def get_pid_tid():
    """Returns a string containing the current process and thread id in the format "(pid=%pid) (tid=%tid)".
    @return: The string containing the process and thread id.
    @rtype: six.text_type
    """
    # noinspection PyBroadException
    try:
        return "(pid=%s) (tid=%s)" % (
            six.text_type(os.getpid()),
            six.text_type(six.moves._thread.get_ident()),
        )
    except Exception:
        return "(pid=%s) (tid=Unknown)" % (six.text_type(os.getpid()))


def is_list_of_strings(vals):
    """Returns True if val is a list (or enumerable) of strings.  False otherwise"""
    try:
        # check if everything is a string
        for val in vals:
            if not isinstance(val, six.string_types):
                return False
    except Exception:
        # vals is not enumerable
        return False

    # everything is a string
    return True


def get_parser_from_config(base_config, attributes, default_parser):
    """
    Checks the various places that the parser option could be set and returns
    the value with the highest precedence, or `default_parser` if no parser was found
    @param base_config: a set of log config options for a logfile
    @param attributes: a set of attributes to apply to a logfile
    @param default_parser: the default parser if no parser setting is found in base_config or attributes
    """
    # check all the places `parser` might be set
    # highest precedence is base_config['attributes']['parser'] - this is if
    # `com.scalyr.config.log.attributes.parser is set as a label
    if "attributes" in base_config and "parser" in base_config["attributes"]:
        return base_config["attributes"]["parser"]

    # next precedence is base_config['parser'] - this is if
    # `com.scalyr.config.log.parser` is set as a label
    if "parser" in base_config:
        return base_config["parser"]

    # lowest precedence is attributes['parser'] - this is if
    # `parser` is a label and labels are being uploaded as attributes
    # and the `parser` label passes the attribute filters
    if "parser" in attributes:
        return attributes["parser"]

    # if we are here, then we found nothing so return the default
    return default_parser


def get_web_url_from_upload_url(server):
    server = server.replace("https://agent.", "https://www.")
    server = server.replace("https://log.", "https://www.")
    server = server.replace("https://upload.", "https://www.")
    server = server.replace("https://app.", "https://www.")
    return server


def parse_data_rate_string(value):
    """Return a rate in bytes per second parsed from a string of a float or int followed by a unit.
    Takes into account bit (`b`) vs byte (`B`) but bit will throw an error to make sure no one gets tripped up, ignores
    capitalization of things like `k` vs `K` and the time unit denominator. Allowed numerators go up to terabytes, and
    allowed denominators go up to weeks.

    :param value: String with value and unit
    :return: The parsed rate in bytes per second, or raise ValueError if it could not be parsed
    """
    m = re.search(r"(-?\d+\.?\d*)\s*([kKmMgGtT]?)([iI]?)([bB])/([sSmMhHdDwW])", value)
    if m:
        value = float(m.group(1))
        numerator = m.group(2).upper()
        base_string = m.group(3).upper()
        bit_or_byte = m.group(4)
        denominator = m.group(5).upper()

        base = 1000
        if base_string == "I":
            base = 1024

        if numerator == "K":
            value = value * base
        elif numerator == "M":
            value = value * base ** 2
        elif numerator == "G":
            value = value * base ** 3
        elif numerator == "T":
            value = value * base ** 4

        if bit_or_byte == "b":
            raise ValueError(
                "Could not parse data rate string '%s', rates defined in bits (lowercase 'b') are not allowed."
                % value
            )

        if denominator == "M":
            value = value / 60
        elif denominator == "H":
            value = value / 60 / 60
        elif denominator == "D":
            value = value / 60 / 60 / 24
        elif denominator == "W":
            value = value / 60 / 60 / 24 / 7

        return value
    raise ValueError("Could not parse data rate string '%s'" % value)


class JsonReadFileException(Exception):
    """Raised when a failure occurs when reading a file as a JSON object."""

    def __init__(self, file_path, message):
        self.file_path = file_path
        self.raw_message = message

        Exception.__init__(
            self, "Failed while reading file '%s': %s" % (file_path, message)
        )


class RunState(object):
    """Keeps track of whether or not some process, such as the agent or a monitor, should be running.

    This abstraction can be used by multiple threads to efficiently monitor whether or not the process should
    still be running.  The expectation is that multiple threads will use this to attempt to quickly finish when
    the run state changes to false.
    """

    def __init__(self, fake_clock=None):
        """Creates a new instance of RunState which always is marked as running.

        @param fake_clock: If not None, the fake clock to use to control the time and sleeping for tests.
        @type fake_clock: FakeClock|None
        """
        self.__condition = threading.Condition()
        self.__is_running = True
        # A list of functions to invoke when this instance becomes stopped.
        self.__on_stop_callbacks = []
        self.__fake_clock = fake_clock

    def is_running(self):
        """Returns True if the state is still set to running."""
        self.__condition.acquire()
        result = self.__is_running
        self.__condition.release()
        return result

    def sleep_but_awaken_if_stopped(self, timeout):
        """Sleeps for the specified amount of time, unless the run state changes to False, in which case the sleep is
        terminated as soon as possible.

        @param timeout: The number of seconds to sleep.

        @return: True if the run state has been set to stopped.
        """
        if self.__fake_clock is not None:
            return self.__simulate_sleep_but_awaken_if_stopped(timeout)

        self.__condition.acquire()
        try:
            if not self.__is_running:
                return True

            self._wait_on_condition(timeout)
            return not self.__is_running
        finally:
            self.__condition.release()

    def __simulate_sleep_but_awaken_if_stopped(self, timeout):
        """Simulates sleeping when a `FakeClock` is being used for testing.

        This method will exit when any of the following occur:  the fake time is advanced by `timeout`
        seconds or when this thread is stopped.

        @param timeout: The number of seconds to sleep.
        @type timeout: float

        @return: True if the thread has been stopped.
        @rtype: bool
        """
        deadline = self.__fake_clock.time() + timeout

        def deadline_exceeded_or_not_running(current_time):
            return current_time >= deadline or not self.is_running()

        self.__fake_clock.simulate_waiting(exit_when=deadline_exceeded_or_not_running)

        return not self.is_running()

    def stop(self):
        """Sets the run state to stopped.

        This also ensures that any threads currently sleeping in 'sleep_but_awaken_if_stopped' will be awoken.
        """
        callbacks_to_invoke = None
        self.__condition.acquire()
        if self.__is_running:
            callbacks_to_invoke = self.__on_stop_callbacks
            self.__on_stop_callbacks = []
            self.__is_running = False
            self.__condition.notifyAll()
        self.__condition.release()

        # Invoke the stopped callbacks.
        if callbacks_to_invoke is not None:
            for callback in callbacks_to_invoke:
                callback()

    def register_on_stop_callback(self, callback):
        """Adds a callback that will be invoked when this instance becomes stopped.

        The callback will be invoked as soon as possible after the instance has been stopped, but they are
        not guaranteed to be invoked before 'is_running' return False for another thread.

        @param callback: A function that does not take any arguments.
        """
        is_already_stopped = False
        self.__condition.acquire()
        if self.__is_running:
            self.__on_stop_callbacks.append(callback)
        else:
            is_already_stopped = True
        self.__condition.release()

        # Invoke the callback if we are already stopped.
        if is_already_stopped:
            callback()

    def remove_on_stop_callback(self, callback):
        """Removes the specified callback that was previously added via `register_on_stop_callback`.

        @param callback: The callback
        """
        self.__condition.acquire()
        try:
            if self.__is_running:
                self.__on_stop_callbacks.remove(callback)
        finally:
            self.__condition.release()

    def _wait_on_condition(self, timeout):
        """Blocks for the condition to be signaled for the specified timeout.

        This is only broken out for testing purposes.

        @param timeout: The maximum number of seconds to block on the condition.
        """
        self.__condition.wait(timeout)


class FakeRunState(RunState):
    """A RunState subclass that does not actually sleep when sleep_but_awaken_if_stopped that can be used for tests.
    """

    def __init__(self):
        # The number of times this instance would have slept.
        self.__total_times_slept = 0
        RunState.__init__(self)

    def _wait_on_condition(self, timeout):
        self.__total_times_slept += 1
        return

    @property
    def total_times_slept(self):
        return self.__total_times_slept


class FakeClock(object):
    """Used to simulate time and control threads waking up for sleep for tests.
    """

    def __init__(self):
        """Constructs a new instance.
        """
        # A lock/condition to protected _time.  It is notified whenever _time is changed.
        self._time_condition = threading.Condition()
        # The current time in seconds past epoch.
        self._time = 0.0
        # A lock/condition to protect _waiting_threads.  It is notified whenever _waiting_threads is changed.
        self._waiting_condition = threading.Condition()
        # The number of threads that are blocking in `simulate_waiting`.
        self._waiting_threads = 0

    def time(self):
        """Returns the current time according to the fake clock.

        @return: The current time in seconds past epoch.
        @rtype: float
        """
        self._time_condition.acquire()
        try:
            return self._time
        finally:
            self._time_condition.release()

    def advance_time(self, set_to=None, increment_by=None):
        """Advances the current time and notifies all threads currently waiting on the time.

        One of `set_to` or `increment_by` must be set.

        @param set_to: The absolute time in seconds past epoch to set the time.
        @param increment_by: The number of seconds to advance the current time by.
        @param notify_all: Whether to notifyAll() threads waiting on the time_condition

        @type set_to: float|None
        @type increment_by: float|None
        """
        self._time_condition.acquire()
        if set_to is not None:
            self._time = set_to
        else:
            self._time += increment_by
        self._time_condition.notifyAll()
        self._time_condition.release()

    def simulate_waiting(self, exit_when=None):
        """Will block the current thread until notified and exit_when returns true (if exit_when is not None).

        Notification can occur if another thread invokes `advance_time` or `wake_all_threads`

        Since this can return even when the fake clock time has not changed, it is up to the calling thread to check
        to see if time has advanced far enough for any condition they wish.  However, it is typically expected that
        they will not only be waiting for a particular time but also on some other condition, such as whether or not
        a condition has been notified.

        @param exit_when:  A function whose result will determine if this method should finish waiting and return.
            This function takes in one parameter, the current time.  Note, the lock on the fake clock is held while this
            method is invoked, so you can atomically check the time against other conditions.  If the function returns
            true, this function will return.  The function is checked once at the start of the invocation and then
            after every subsequent notification on the fake clock.
        """
        self._time_condition.acquire()

        # Helper function to reduce code copy
        def wait_block():
            self._increment_waiting_count(1)
            self._time_condition.wait()
            self._increment_waiting_count(-1)

        try:
            if exit_when is None:
                wait_block()
            else:
                while not exit_when(self._time):
                    wait_block()
        finally:
            self._time_condition.release()

    def block_until_n_waiting_threads(self, n):
        """Blocks until there are n threads blocked in `simulate_waiting`.

        This is useful for tests when you wish to ensure other threads have reached some sort of checkpoint before
        advancing to the next stage of the test.

        @param n: The number of threads that should be blocked in `simulate_waiting.
        @type n: int
        """
        self._waiting_condition.acquire()
        while self._waiting_threads < n:
            self._waiting_condition.wait()
        self._waiting_condition.release()

    def wake_all_threads(self):
        """Invoked to wake all threads currently blocked in `simulate_waiting`.
        """
        self.advance_time(increment_by=0.0)

    def _increment_waiting_count(self, increment):
        """Increments the count of how many threads are blocked in `simulate_waiting` and notifies any thread waiting
        on that count.

        @param increment: The number of threads to increment the count by.
        @type increment: int
        """
        self._waiting_condition.acquire()
        self._waiting_threads += increment
        self._waiting_condition.notifyAll()
        self._waiting_condition.release()


class RealFakeClock(FakeClock):
    def time(self):
        return time.time()

    def advance_time(self, set_to=None, increment_by=None):
        self._time_condition.acquire()
        if set_to is not None:
            increment_by = set_to - time.time()
        if increment_by is None:
            raise ValueError("Either set_to or increment_by must be supplied")
        increment_by = max(0, increment_by)
        time.sleep(increment_by)
        self._time_condition.notifyAll()
        self._time_condition.release()


class FakeClockCounter(object):
    """Helper class for multithreaded testing. Provides a method for a thread to block until a count has reached target
    value.  Moreover, for every successfully observed increment, it will advance the fake_clock and wait for all
    other threads (driven by the fake clock) to wait on the clock.  For example usage, see MonitorsManagerTest.
    """

    def __init__(self, fake_clock, num_waiters):
        """
        @param fake_clock: FakeClock that will be advanced on every sleep_until_count_or_maxwait() call
        @param num_waiters: Number of threads that wait on fake clock
        """
        self.__fake_clock = fake_clock
        self.__num_waiters = num_waiters
        self.__count = 0
        self.__condition = threading.Condition()

    def count(self):
        self.__condition.acquire()
        try:
            return self.__count
        finally:
            self.__condition.release()

    def increment(self):
        self.__condition.acquire()
        try:
            self.__count += 1
            self.__condition.notifyAll()
        finally:
            self.__condition.release()

    def __wait_for_increment(self, old_count, timeout=None):
        remaining = timeout
        self.__condition.acquire()
        try:
            while self.__count == old_count and remaining > 0:
                t1 = time.time()
                self.__condition.wait(remaining)
                remaining -= time.time() - t1
        finally:
            self.__condition.release()

    def sleep_until_count_or_maxwait(self, target, fake_increment_sec, maxwait):
        """Blocks until the counter reaches the target value, or a specified amount of time passes,
        whichever comes first.

        @param target: Target count to reach
        @param fake_increment_sec: Seconds to increment the fake clock on each poll
        @param maxwait: Time (seconds) to wait for target to be reached
        @return: True if number of polls reaches target_polls, else False
        """
        deadline = time.time() + maxwait
        while self.count() < target and time.time() < deadline:
            # Important: wait for all participant threads to arrive and block.
            # Failing to do so leads to non-deterministic test hangs.
            self.__fake_clock.block_until_n_waiting_threads(self.__num_waiters)
            old_count = self.count()
            self.__fake_clock.advance_time(increment_by=fake_increment_sec)
            self.__wait_for_increment(old_count, timeout=deadline - time.time())

        return self.count() == target


class StoppableThread(threading.Thread):
    """A slight extension of a thread that uses a RunState instance to track if it should still be running.

    This abstraction also allows the caller to receive any exception that is raised during execution
    by calling `join`.

    It is expected that the run method or target of this thread periodically calls `_run_state.is_stopped`
    to determine if the thread has been stopped.
    """

    # Protects __name_prefix
    __name_lock = threading.Lock()
    # A prefix to add to all threads.  This is used for testing.
    __name_prefix = None

    def __init__(self, name=None, target=None, fake_clock=None, is_daemon=False):
        """Creates a new thread.

        You must invoke `start` to actually have the thread begin running.

        Note, if you set `target` to None, then the thread will invoke `run_and_propagate` instead of `run` to
        execute the work for the thread.  You must override `run_and_propagate` instead of `run`.

        @param name: The name to give the thread.  Note, if a prefix has been specified via `set_name_prefix`,
            the name is created by concat'ing `name` to the prefix.
        @param target: If not None, a function that will be invoked when the thread is invoked to perform
            the work for the thread.  This function should accept a single argument, the `RunState` instance
            that will signal when the thread should stop work.
        @param fake_clock:  A fake clock to control the time and when threads wake up for tests.
        @param is_daemon: If True, will set this thread to Daemon (useful for stopping test threads quicker).
            Use this cautiously as it may result in resources not being freed up properly.

        @type name: str
        @type target: None|func
        @type fake_clock: FakeClock|None

        """
        name_prefix = StoppableThread._get_name_prefix()
        if name_prefix is not None:
            if name is not None:
                name = "%s%s" % (name_prefix, name)
            else:
                name = name_prefix
        # NOTE: We explicitly don't pass target= argument to the parent constructor since this
        # creates a cycle and a memory leak
        threading.Thread.__init__(self, name=name)

        if is_daemon:
            self.setDaemon(True)
        self.__target = target
        self.__exception_info = None
        # Tracks whether or not the thread should still be running.
        self._run_state = RunState(fake_clock=fake_clock)

    @staticmethod
    def set_name_prefix(name_prefix):
        """Sets a prefix to add to the beginning of all threads from this point forward.

        @param name_prefix: The prefix or None if no prefix should be used.
        @type name_prefix: six.text_type or None
        """
        StoppableThread.__name_lock.acquire()
        try:
            StoppableThread.__name_prefix = name_prefix
        finally:
            StoppableThread.__name_lock.release()

    @staticmethod
    def _get_name_prefix():
        """
        @return: The prefix to add to all thread names
        @rtype: str or None
        """
        StoppableThread.__name_lock.acquire()
        try:
            return StoppableThread.__name_prefix
        finally:
            StoppableThread.__name_lock.release()

    def run(self):
        """
        NOTE: This is a workaround for using threading.Thread constructor target argument which
        results in a cycle and a memory leak.

        See https://bugs.python.org/issue704180 for details.
        """
        return self.__run_impl()

    def __run_impl(self):
        """Internal run implementation.
        """
        # noinspection PyBroadException
        try:
            if self.__target is not None:
                self.__target(self._run_state)
            else:
                self.run_and_propagate()
        except Exception as e:
            self.__exception_info = sys.exc_info()
            logging.getLogger().warn(
                "Received exception from run method in StoppableThread %s"
                % six.text_type(e)
            )
            return None

    def run_and_propagate(self):
        """Derived classes should override this method instead of `run` to perform their work.

        This allows for the base class to catch any raised exceptions and propagate them during the join call.
        """
        pass

    def is_running(self):
        # type: () -> bool
        """
        Return True if this thread is running.
        """
        return self._run_state.is_running()

    def stop(self, wait_on_join=True, join_timeout=5):
        """Stops the thread from running.

        By default, this will also block until the thread has completed (by performing a join).

        @param wait_on_join: If True, will block on a join of this thread.
        @param join_timeout: The maximum number of seconds to block for the join.
        """
        self._run_state.stop()
        self._prepare_to_stop()
        if wait_on_join:
            self.join(join_timeout)

    def _prepare_to_stop(self):
        """Invoked when the thread has been asked to stop.  It is called after the run state has been updated
        to indicate the thread should no longer be running.

        Derived classes may override this method to perform work when the thread is about to be stopped.
        """
        pass

    def join(self, timeout=None):
        """Blocks until the thread has finished.

        If the thread also raised an uncaught exception, this method will raise that same exception.

        Note, the only way to tell for sure that the thread finished is by invoking 'is_alive' after this
        method returns.  If the thread is still alive, that means this method exited due to a timeout expiring.

        @param timeout: The number of seconds to wait for the thread to finish or None if it should block
            indefinitely.
        @type timeout: float|None
        """
        threading.Thread.join(self, timeout)
        if not self.isAlive() and self.__exception_info is not None:
            six.reraise(
                self.__exception_info[0],
                self.__exception_info[1],
                self.__exception_info[2],
            )

    def isAlive(self):
        """
        Here for compatibility with Python 2.
        """
        return self.is_alive()

    def is_alive(self):
        """
        Custom isAlive() implementation because previously we relied on "_is_stopped" class instance
        variable which is reserved / used by actual "is_alive()" implementation under Python 3.
        """
        # TODO: This is not 100% correct, but that's the behavior our code relies ON.
        # Eventually we need to fix the implementation on StoppableThread so RunState defaults
        # "_is_running" to False and then set it to True inside "run()" and only check that value
        # here.
        if six.PY2:
            return super(StoppableThread, self).isAlive()

        if (
            not self._run_state.is_running()
            or not super(StoppableThread, self).is_alive()
        ):
            return False

        return True


class RateLimiter(object):
    """An abstraction that can be used to enforce some sort of rate limit, expressed as a maximum number
    of bytes to be consumed over a period of time.

    This abstraction is not thread-safe.

    It uses a leaky-bucket implementation.  In this approach, the rate limit is modeled as a bucket
    with a hole in it.  The bucket has a maximum size (expressed in bytes) and a fill rate (expressed in bytes
    per second).  Whenever there is an operation that would consume bytes, this abstraction checks to see if
    there are at least X number bytes available in the bucket.  If so, X is deducted from the bucket's contents.
    Otherwise, the operation is rejected.  The bucket is gradually refilled at the fill rate, but the contents
    of the bucket will never exceeded the maximum bucket size.
    """

    def __init__(self, bucket_size, bucket_fill_rate, current_time=None):
        """Creates a new bucket.

          @param bucket_size: The bucket size, which should be the maximum number of bytes that can be consumed
              in a burst.
          @param bucket_fill_rate: The fill rate, expressed as bytes per second.  This should correspond to the
              maximum desired steady state rate limit.
          @param current_time:   If not none, the value to use as the current time, expressed in seconds past epoch.
              This is used in testing.
        """
        self.__bucket_contents = bucket_size
        self.__bucket_size = bucket_size
        self.__bucket_fill_rate = bucket_fill_rate

        if current_time is None:
            current_time = time.time()

        self.__last_bucket_fill_time = current_time

    def charge_if_available(self, num_bytes, current_time=None):
        """Returns true and updates the rate limit count if there are enough bytes available for an operation
        costing num_bytes.

        @param num_bytes: The number of bytes to consume from the rate limit.
        @param current_time: If not none, the value to use as the current time, expressed in seconds past epoch. This
            is used in testing.

        @return: True if there are enough room in the rate limit to allow the operation.
        """
        if self._get_time_to_sleep(num_bytes, current_time) > 0.0:
            return False
        else:
            self.__bucket_contents -= num_bytes
            return True

    def block_until_charge_succeeds(self, num_bytes, current_time=None):
        """Blocks until there are enough bytes available for an operation costing num_bytes, then charges that amount.
        As a reminder, this abstraction is not thread-safe so no other method should be invoked on this instance while
        it is blocking.

        @param num_bytes: The number of bytes to consume from the rate limit.
        @param current_time: If not none, the value to use as the current time, expressed in seconds past epoch. This
            is used in testing.

        @return: Returns the amount of time this method slept.
        """
        if self.__bucket_fill_rate <= 0.0:
            raise ValueError(
                "bucket_fill_rate must be greater than 0 to use block_until_charge_succeeds"
            )
        time_to_sleep = self._get_time_to_sleep(num_bytes, current_time)
        if time_to_sleep > 0.0:
            time.sleep(time_to_sleep)
        self.__bucket_contents -= num_bytes

        return time_to_sleep

    def _get_time_to_sleep(self, num_bytes, current_time=None):
        """Returns the amount of time in seconds we would need to sleep to have enough capacity to charge num_bytes
        without overflowing. num_bytes values greater than the bucket size are allowed and will simulate overfilling
        of the bucket. bucket_fill_rates values less than or equal to zero will not return values that should actually
        be slept on, but they are valid enough for checking if there is sufficient space to charge num_bytes
        immediately.

        @param num_bytes: The number of bytes to consume from the rate limit.
        @param current_time: If not none, the value to use as the current time, expressed in seconds past epoch. This
            is used in testing.
        :return: Time in seconds to sleep to create enough capacity for num_bytes, assuming valid bucket_fill_rate.
        """
        if current_time is None:
            current_time = time.time()

        fill_amount = (
            current_time - self.__last_bucket_fill_time
        ) * self.__bucket_fill_rate

        self.__bucket_contents = min(
            self.__bucket_size, self.__bucket_contents + fill_amount
        )
        self.__last_bucket_fill_time = current_time

        if num_bytes <= self.__bucket_contents:
            return 0.0
        elif self.__bucket_fill_rate == 0:
            return float("inf")
        else:
            return (num_bytes - self.__bucket_contents) / self.__bucket_fill_rate


class ScriptEscalator(object):
    """Utility that helps re-execute the current script using the user account that owns the
    configuration file.

    Most Scalyr scripts expect to run as the user that owns the configuration file.  If the current user is
    not the owner, but they are privileged enough to execute a process as that owner, then we will do it.

    This is platform dependent.  For example, Linux will re-execute the script if the current user is 'root',
    where as Windows will prompt the user for the Administrator's password.
    """

    def __init__(
        self,
        controller,
        config_file_path,
        current_working_directory,
        no_change_user=False,
    ):
        """
        @param controller: The instance of the PlatformController being used to execute the script.
        @param config_file_path: The full path to the configuration file.
        @param current_working_directory: The current working directory for the script being executed.

        @type controller: PlatformController
        @type config_file_path: str
        @type current_working_directory:  str
        """
        self.__controller = controller

        self.__running_user = None
        self.__desired_user = None

        if not no_change_user:
            self.__running_user = controller.get_current_user()
            self.__desired_user = controller.get_file_owner(config_file_path)
        self.__cwd = current_working_directory

    def is_user_change_required(self):
        """Returns True if the user running this process is not the same as the owner of the configuration file.

        If this returns False, it is expected that `change_user_and_rerun_script` will be invoked.

        @return: True if the user must be changed.
        @rtype: bool
        """
        return self.__running_user != self.__desired_user

    def change_user_and_rerun_script(self, description, handle_error=True):
        """Attempts to re-execute the current script as the owner of the configuration file.

        Note, for some platforms, this will result in the current process being replaced completely with the
        new process.  So, this method may never return from the point of the view of the caller.

        @param description: A description of what the script is trying to accomplish.  This will be used in an
            error message if an error occurs.  It will read "Failing, cannot [description] as the correct user".
        @param handle_error:  If True, if the platform controller raises an `CannotExecuteAsUser` error, this
            method will handle it and print an error message to stderr.  If this is False, the exception is
            not caught and propagated to the caller.

        @type description: str
        @type handle_error: bool

        @return: If the function returns, the status code of the executed process.
        @rtype: int
        """
        try:
            script_args = sys.argv[1:]
            script_binary = None
            script_file_path = None

            # See if this is a PyInstaller executable. If so, then we do not have a script file, but a binary executable
            # that contains the script.
            if hasattr(sys, "frozen"):
                script_binary = sys.executable
            else:
                # We use the __main__ symbolic module to determine which file was invoked by the python script.
                # noinspection PyUnresolvedReferences
                import __main__  # type: ignore

                # NOTE: Under some scenarios when running in parallel with pytest __file__ attribute
                # won't be set.
                script_file_path = getattr(__main__, "__file__", None)
                if script_file_path and not os.path.isabs(script_file_path):
                    script_file_path = os.path.normpath(
                        os.path.join(self.__cwd, script_file_path)
                    )

            return self.__controller.run_as_user(
                self.__desired_user, script_file_path, script_binary, script_args
            )
        except CannotExecuteAsUser as e:
            if not handle_error:
                raise e
            print(
                "Failing, cannot %s as the correct user.  The command must be executed using the "
                "same account that owns the configuration file.  The configuration file is owned by "
                "%s whereas the current user is %s.  Changing user failed due to the following "
                'error: "%s". Please try to re-execute the command as %s'
                % (
                    description,
                    self.__desired_user,
                    self.__running_user,
                    e.error_message,
                    self.__desired_user,
                ),
                file=sys.stderr,
            )
            return 1


class RedirectorServer(object):
    """Utility class that accepts incoming client connections and redirects the output being written to
    stdout and stderr to it.

    This is used to implement the process escalation feature for Windows.  Essentially, due to the limited access
    Python provides to escalating a process, we cannot access the running processes's stdout, stderr.  In order
    to display it, we have the spawned process redirect all of its output to stdout and stderr to the original
    process which prints it to its stdout and stderr.

    This must be used in conjunction with `RedirectorClient`.
    """

    def __init__(self, channel, sys_impl=sys):
        """Creates an instance.

        @param channel: The server channel to listen for connections.  Derived classes must provide an actual
            implementation of the ServerChannel abstraction in order to actually implement the cross-process
            communication.
        @param sys_impl: The sys module, holding references to 'stdin' and 'stdout'.  This is only overridden
            for testing purposes.

        @type channel: RedirectorServer.ServerChannel
        """
        self.__channel = channel
        # We need a lock to protect multiple threads from writing to the channel at the same time.
        self.__channel_lock = threading.Lock()
        # References to the original stdout, stderr for when we need to restore those objects.
        self.__old_stdout = None
        self.__old_stderr = None
        # Holds the references to stdout and stderr.
        self.__sys = sys_impl

    # Constants used to identify which output stream a given piece of content should be written.
    STDOUT_STREAM_ID = 0
    STDERR_STREAM_ID = 1

    def start(self, timeout=5.0):
        """Starts the redirection server.

        Blocks until a connection from a single client is received and then initializes the system to redirect
        all stdout and stderr output to it.

        This will replace the current stdout and stderr streams with implementations that will write to the
        client channel.

        Note, this method should not be called multiple times.

        @param timeout: The maximum number of seconds this method will block for an incoming client.
        @type timeout: float

        @raise RedirectorError: If no client connects within the timeout period.
        """
        if not self.__channel.accept_client(timeout=timeout):
            raise RedirectorError(
                "Client did not connect to server within %lf seconds" % timeout
            )

        self.__old_stdout = self.__sys.stdout
        self.__old_stderr = self.__sys.stderr

        self.__sys.stdout = RedirectorServer.Redirector(
            RedirectorServer.STDOUT_STREAM_ID, self._write_stream
        )
        self.__sys.stderr = RedirectorServer.Redirector(
            RedirectorServer.STDERR_STREAM_ID, self._write_stream
        )

    def stop(self):
        """Signals the client connection that all bytes have been sent and then resets stdout and stderr to
        their original values.
        """
        # This will result in a -1 being written to the stream, indicating the server is closing down.
        self._write_stream(-1, "")

        self.__channel.close()
        self.__channel = None
        self.__sys.stdout = self.__old_stdout
        self.__sys.stderr = self.__old_stderr

    def _write_stream(self, stream_id, content):
        """Writes the specified bytes to the client.

        @param stream_id: Either `STDOUT_STREAM_ID` or `STDERR_STREAM_ID`.  Identifies which output the
            bytes were written to.
        @param content: The bytes that were written.

        @type stream_id: int
        @type content: str|unicode
        """
        # We have to be careful about how we encode the bytes.  It's better to assume it is utf-8 and just
        # serialize it that way.
        encoded_content = six.text_type(content).encode("utf-8")
        # When we send over a chunk of bytes to the client, we prefix it with a code that identifies which
        # stream it should go to (stdout or stderr) and how many bytes we are sending.  To encode this information
        # into a single integer, we just shift the len of the bytes over by one and set the lower bit to 0 if it is
        # stdout, or 1 if it is stderr.
        code = len(encoded_content) * 2 + stream_id

        self.__channel_lock.acquire()
        try:
            if self.__channel_lock is not None:
                # 2->TODO struct.pack|unpack in python < 2.7.7 does not allow unicode format string.
                self.__channel.write(
                    compat.struct_pack_unicode("i", code) + encoded_content
                )
            elif stream_id == RedirectorServer.STDOUT_STREAM_ID:
                self.__sys.stdout.write(content)
            else:
                self.__sys.stderr.write(content)
        finally:
            self.__channel_lock.release()

    class ServerChannel(object):
        """The base class for the channel that is used by the server to accept an incoming connection from the
        client and then write bytes to it.

        A single instance of this class can only be used to accept one connection from a client and write bytes to it.

        Derived classes must be provided to actually implement the communication.
        """

        def accept_client(self, timeout=None):
            """Blocks until a client connects to the server.

            One the client has connected, then the `write` method can be used to write to it.

            @param timeout: The maximum number of seconds to wait for the client to connect before raising an
                `RedirectorError` exception.
            @type timeout: float|None

            @return:  True if a client has been connected, otherwise False.
            @rtype: bool
            """
            pass

        def write(self, content):
            """Writes the bytes to the connected client.

            @param content: The bytes
            @type content: str
            """
            pass

        def close(self):
            """Closes the channel to the client.
            """
            pass

    class Redirector(object):
        """Simple class that is used to set references to `sys.stdout` and `sys.stderr`.

        This provides the `write` method necessary for `stdout` and `stderr` such that all bytes written will
        be sent to the client.
        """

        def __init__(self, stream_id, writer_func):
            """Creates an instance.

            @param stream_id: Which stream this object is representing, either `STDOUT_STREAM_ID` or `STDERR_STREAM_ID`.
                This is used to identify to the client which stream the bytes should be printed to.
            @param writer_func: A function that, when invoked, will write the bytes to the underlying client.
                The function takes two arguments: the stream id and the output bytes.

            @type stream_id: int
            @type writer_func: func(int, str)
            """
            self.__writer_func = writer_func
            self.__stream_id = stream_id

        def write(self, output_buffer):
            """Writes the output to the underlying client.

            @param output_buffer: The bytes to send.
            @type output_buffer: str
            """
            self.__writer_func(self.__stream_id, output_buffer)


class RedirectorError(Exception):
    """Raised when an exception occurs with the RedirectionClient or RedirectionServer.
    """

    pass


class RedirectorClient(StoppableThread):
    """Implements the client side of the Redirector service.

    It connects to a process running the `RedirectorServer`, reads all incoming bytes sent by the server, and
    writes them to stdin/stdout.

    This functionality is implemented using a thread.  This thread must be started for the process to begin
    receiving bytes from the `RedirectorServer`.
    """

    def __init__(self, channel, sys_impl=sys, fake_clock=None):
        """Creates a new instance.

        @param channel: The channel to use to connect to the server.
        @param sys_impl: The sys module, which holds references to stdin and stdout.  This is only overwritten for
            tests.
        @param fake_clock: The `FakeClock` instance to use to control time and when threads are woken up.  This is only
            set by tests.

        @type channel: RedictorClient.ClientChannel
        @type fake_clock: FakeClock|None
        """
        StoppableThread.__init__(self, fake_clock=fake_clock)
        self.__channel = channel
        self.__stdout = sys_impl.stdout
        self.__stderr = sys_impl.stderr
        self.__fake_clock = fake_clock

    # The number of seconds to wait for the server to accept the client connection.
    CLIENT_CONNECT_TIMEOUT = 60.0

    def run_and_propagate(self):
        """Invoked when the thread begins and performs the bulk of the work.
        """
        # The timeline by which we must connect to the server and receiving all bytes.
        overall_deadline = self.__time() + RedirectorClient.CLIENT_CONNECT_TIMEOUT

        # Whether or not the client was able to connect.
        connected = False

        try:
            # Do a busy loop to waiting to connect to the server.
            # Note, for testing purposes, it is important we get the time before we invoke `connect`, since
            # the simulated calls to allow for connection advance the clock.  By capturing the time before we
            # invoked `connect`, we can easily see if the connect state later changes (because the time is different
            # than our captured time).
            last_busy_loop_time = self.__time()
            while self._is_running():
                if self.__channel.connect():
                    connected = True
                    break

                self._sleep_for_busy_loop(
                    overall_deadline, last_busy_loop_time, "connection to be made."
                )
                last_busy_loop_time = self.__time()

            # If we aren't running any more, then return.  This could happen if the creator of this instance
            # called the `stop` method before we connected.
            if not self._is_running():
                return

            if not connected:
                raise RedirectorError(
                    "Could not connect to other endpoint before timeout."
                )

            # Keep looping, accepting new bytes and writing them to the appropriate stream.
            while self._is_running():
                # Busy loop waiting for more bytes.
                if not self.__wait_for_available_bytes(overall_deadline):
                    break

                # Read one integer which should contain both the number of bytes of content that are being sent
                # and which stream it should be written to.  The stream id is in the lower bit, and the number of
                # bytes is shifted over by one.
                # 2->TODO struct.pack|unpack in python < 2.7.7 does not allow unicode format string.
                code = compat.struct_unpack_unicode("i", self.__channel.read(4))[
                    0
                ]  # Read str length

                # The server sends -1 when it wishes to close the stream.
                if code < 0:
                    break

                bytes_to_read = code >> 1
                stream_id = code % 2

                content = self.__channel.read(bytes_to_read).decode("utf-8")

                if stream_id == RedirectorServer.STDOUT_STREAM_ID:
                    self.__stdout.write(content)
                else:
                    self.__stderr.write(content)
        finally:
            if connected:
                self.__channel.close()

    def __wait_for_available_bytes(self, overall_deadline):
        """Waits for new bytes to become available from the server.

        Raises `RedirectorError` if no bytes are available before the overall deadline is reached.

        @param overall_deadline: The walltime that new bytes must be received by, or this instance will raise
            `RedirectorError`
        @type overall_deadline: float
        @return: True if new bytes are available, or False if the thread has been stopped.
        @rtype: bool
        """
        # For testing purposes, it is important that we capture the time before we invoke `peek`.  That's because
        # all methods that write bytes will advance the clock... so we can tell if there may be new data by seeing
        # if the time has changed since the captured time.
        last_busy_loop_time = self.__time()
        while self._is_running():
            (num_bytes_available, result) = self.__channel.peek()
            if result != 0:
                raise RedirectorError(
                    "Error while waiting for more bytes from redirect server error=%d"
                    % result
                )
            if num_bytes_available > 0:
                return True
            self._sleep_for_busy_loop(
                overall_deadline, last_busy_loop_time, "more bytes to be read"
            )
            last_busy_loop_time = self.__time()
        return False

    def _is_running(self):
        """Returns true if this thread is still running.
        @return: True if this thread is still running.
        @rtype: bool
        """
        return self._run_state.is_running()

    # The amount of time we sleep while doing a busy wait loop waiting for the client to connect or for new byte
    # to become available.
    BUSY_LOOP_POLL_INTERVAL = 0.03

    def _sleep_for_busy_loop(self, deadline, last_loop_time, description):
        """Sleeps for a small unit of time as part of a busy wait loop.

        This method will return if either the small unit of time has exceeded, the overall deadline has been exceeded,
        or if the `stop` method of this thread has been invoked.

        @param deadline: The walltime that this operation should time out.  This method will sleep until the smaller of
            last_loop_time + BUSY_LOOP_POLL_INTERVAL or deadline.
        @param last_loop_time: The time the last loop through the busy wait loop began.  This is used to calculate the
            deadline of the busy sleep.  Note, it is also important for catching advances in the fake clock when
            in test mode.
        @param description: A description of why we waiting to be used in error output.

        @type deadline: float
        @type last_loop_time: float
        @type description: six.text_type
        """
        current_time = self.__time()
        poll_deadline = RedirectorClient.BUSY_LOOP_POLL_INTERVAL + last_loop_time

        if deadline - current_time < 0:
            raise RedirectorError(
                "Deadline exceeded while waiting for %s" % description
            )
        elif deadline > poll_deadline:
            deadline = poll_deadline

        if self.__fake_clock is None:
            self._run_state.sleep_but_awaken_if_stopped(deadline - current_time)
        else:
            self.__simulate_busy_loop(deadline)

    def __simulate_busy_loop(self, deadline):
        """Simulates the busy wait loop using a fake clock.  This will exit when either deadline is exceeded on the
        fake clock or the `stop` method of the thread has been invoked.

        @param deadline: The walltime when this operation should return
        @type deadline: float
        """
        # Helper method to determine if the exit condition has been met.
        def deadline_exceeded_or_is_stopped(current_time):
            return current_time > deadline or not self._run_state.is_running()

        # Helper method to advance the clock.
        def advance_clock():
            self.__fake_clock.advance_time(increment_by=0.01)

        # We will primarily be blocking on the clock waiting for it to advance.  In order to notice when the thread
        # has been stopped, we increment the clock when `stop` is invoked.
        self._run_state.register_on_stop_callback(advance_clock)
        try:
            # Simulate the waiting, looking for the deadline to be exceeded or stop to be invoked.
            self.__fake_clock.simulate_waiting(
                exit_when=deadline_exceeded_or_is_stopped
            )
        finally:
            # Be sure to remove our callback.
            self._run_state.remove_on_stop_callback(advance_clock)

    def __time(self):
        if self.__fake_clock is None:
            return time.time()
        else:
            return self.__fake_clock.time()

    class ClientChannel(object):
        """The base class for client channels, which are used to connect to the server and read the sent bytes.

        Derived classes must provide the actual communication implementation.
        """

        def connect(self):
            """Attempts to connect to the server, but does not block.

            @return: True if the channel is now connected.
            @rtype: bool
            """
            pass

        def peek(self):
            """Returns the number of bytes available for reading without blocking.

            @return A two values, the first the number of bytes, and the second, an error code.  An error code
            of zero indicates there was no error.

            @rtype (int, int)
            """
            pass

        def read(self, num_bytes_to_read):
            """Reads the specified number of bytes from the server and returns them.  This will block until the
            bytes are read.

            @param num_bytes_to_read: The number of bytes to read
            @type num_bytes_to_read: int
            @return: The bytes
            @rtype: str
            """
            pass

        def close(self):
            """Closes the channel to the server.
            """
            pass


def verify_and_get_compress_func(compression_type, compression_level=9):
    # type: (str, int) -> Optional[Callable]
    """
    Given a compression_type (bz2, zlib, lz4, zstandard), verify that compression works and return
    the compress() function with compression level pre-applied.

    @param compression_type: Compression type.
    @type compression_type: str

    @param compression_level: Compression level to use.
    @ type: compression_level: int

    @returns: The compress() function for the specified compression_type. None, if compression_type
        is not supported or if underlying libs are not installed properly,
    """
    if compression_type not in SUPPORTED_COMPRESSION_ALGORITHMS:
        return None

    try:
        compress_func, decompress_func = get_compress_and_decompress_func(
            compression_type, compression_level=compression_level
        )

        # Perform a sanity check that data compresses and that it can be decompressed
        cdata = compress_func(COMPRESSION_TEST_STR)

        if (
            len(cdata) < len(COMPRESSION_TEST_STR)
            and decompress_func(cdata) == COMPRESSION_TEST_STR
        ):
            return compress_func
    except Exception:
        pass

    return None


def get_compress_and_decompress_func(compression_algorithm, compression_level=9):
    # type: (str, int) -> Tuple[Callable, Callable]
    """
    Return compression and decompression function for the provided compression algorithm and
    compression level.

    Returned compression function is already pre-applied / configured with the provided compression
    level.

    This function atakes into account function argument differences between various Python versions.

    NOTE: For benchmark purposes this function right now also supports algorithms (snappy, brotly)
    which are not exposed and supported for the end user setups.
    """
    if compression_algorithm in ["deflate", "zlib"]:
        import zlib

        if sys.version_info < (3, 6, 0):
            # Work around for Python <= 3.6 where compress is not a keyword argument, but a regular
            # argument
            @functools.wraps(zlib.compress)
            def compress_func(data):
                return zlib.compress(data, compression_level)

        else:
            compress_func = functools.partial(zlib.compress, level=compression_level)  # type: ignore
        decompress_func = zlib.decompress  # type: ignore
    elif compression_algorithm == "bz2":
        import bz2

        @functools.wraps(bz2.compress)
        def compress_func(data):
            return bz2.compress(data, compression_level)

        decompress_func = bz2.decompress  # type: ignore
    elif compression_algorithm == "zstandard":
        import zstandard

        compressor = zstandard.ZstdCompressor(level=compression_level)
        decompressor = zstandard.ZstdDecompressor()
        compress_func = compressor.compress  # type: ignore
        decompress_func = decompressor.decompress  # type: ignore
    elif compression_algorithm == "lz4":
        import lz4.frame as lz4

        # NOTE: Java implementation which we currently use on the server side doesn't support
        # dependent block stream.
        # See https://github.com/Parsely/pykafka/issues/914 for details
        def compress_func(data):
            try:
                # For lz4 >= 0.12.0
                return lz4.compress(data, compression_level, block_linked=False)
            except TypeError:
                # For older versions
                # For earlier versions of lz4
                return lz4.compress(data, compression_level, block_mode=1)

        decompress_func = lz4.decompress  # type: ignore
    elif compression_algorithm == "snappy":
        import snappy  # pylint: disable=import-error

        compress_func = snappy.compress  # type: ignore
        decompress_func = snappy.decompress  # type: ignore
    elif compression_algorithm == "brotli":
        import brotli

        compress_func = functools.partial(brotli.compress, quality=compression_level)  # type: ignore
        decompress_func = brotli.decompress  # type: ignore
    else:
        raise ValueError("Unsupported algorithm: %s" % (compression_algorithm))

    return compress_func, decompress_func


class RateLimiterToken(object):
    def __init__(self, token_id):
        self._token_id = token_id

    @property
    def token_id(self):
        """Integer ID"""
        return self._token_id

    def __repr__(self):
        return "Token #%s" % self._token_id


class HistogramTracker(object):
    """Track as an approximate histogram for a set of values.  The approximation is created by
    counting the number of values that fall into a predefined set of ranges.  The caller sets
    the ranges so can control the granularity of the approximation.

    This abstraction also tracks several other statistics for the values, including average, minimum value, and
    maximum value.
    """

    def __init__(self, bucket_ranges):
        """Creates an instance with the specified bucket ranges.  The ranges are specified as an sorted array of numbers,
        where the first bucket will be from 0 >= to < bucket_ranges[0], the second bucket_ranges[0] >= to <
        bucket_ranges[1], etc.

        @param bucket_ranges:  The bucket ranges, specified as a sorted array of numbers where bucket_ranges[i]
            specifies the end of ith bucket and the first bucket starts at 0.
        @type bucket_ranges: [number]
        """
        # An array of the histogram bucket boundaries, such as 1, 10, 30, 100
        self.__bucket_ranges = list(bucket_ranges)
        last_value = None
        for i in self.__bucket_ranges:
            if last_value is not None and i < last_value:
                raise ValueError("The bucket_ranges argument must be sorted.")
            else:
                last_value = i

        # __counts[i] holds the total number of values we have seen >= to __boundaries[i-1] and < __boundaries[i]
        self.__counts = [0] * len(bucket_ranges)
        # __overflows holds the number of values >= __boundaries[-1]
        self.__overflow = 0
        # The minimum and maximum values seen.
        self.__min = None
        self.__max = None
        # The total number of values collected.
        self.__total_count = 0
        # The sum of the values collected
        self.__total_values = 0

    def add_sample(self, value):
        """Adds the specified value to the values being tracked by this instance.  This value will be reflected in the
        statistics for this instance until `reset` is invoked.

        @param value: The value
        @type value: Number
        """
        index = None
        # Find the index of the bucket for this value, which is going to be first bucket range greater than the value.
        for i in range(0, len(self.__bucket_ranges)):
            if self.__bucket_ranges[i] > value:
                index = i
                break

        # Increment that histogram bucket count.
        if index is not None:
            self.__counts[index] += 1
        else:
            # Otherwise, the value must have been greater than our last boundary, so increment the overflow
            self.__overflow += 1

        if self.__min is None or value < self.__min:
            self.__min = value

        if self.__max is None or value > self.__max:
            self.__max = value

        self.__total_count += 1
        self.__total_values += value

    def buckets(self, disable_last_bucket_padding=False):
        """An iterator that returns the tracked buckets along with the number of times a sample was added that
        fell into that bucket since the last reset.  A bucket is only returned if it has at least one sample
        fall into it.

        Each iteration step returns a tuple describing a single bucket: the number of times a value fell into this
        bucket, the lower end of the bucket, and the upper end of the bucket.  Note, the lower end is inclusive, while
        the upper end is exclusive.
        """
        if self.__total_count == 0:
            return

        # We use the minimum value for the lower bound of the first bucket.
        previous = self.__min
        for i in range(0, len(self.__counts)):
            if self.__counts[i] > 0:
                yield self.__counts[i], previous, self.__bucket_ranges[i]
            previous = self.__bucket_ranges[i]

        if self.__overflow == 0:
            return

        if not disable_last_bucket_padding:
            padding = 0.01
        else:
            padding = 0.0

        # We use the maximum value for the upper bound of the overflow range.  Note, we added 0.01 to make sure the
        # boundary is exclusive to the values that fell in it.
        yield self.__overflow, self.__bucket_ranges[-1], self.__max + padding

    def average(self):
        """
        @return: The average for all values added to this instance since the last reset, or None if no values have been
            added.
        @rtype: Number or None
        """
        if self.__total_count > 0:
            return self.__total_values / self.__total_count
        else:
            return None

    def estimate_median(self):
        """Calculates an estimate for the median of all the values since the last reset.  The accuracy of this estimate
        will depend on the granularity of the original buckets.

        @return: The estimated median or None if no values have been added.
        @rtype: Number or None
        """
        return self.estimate_percentile(0.5)

    def estimate_percentile(self, percentile):
        """Calculates an estimate for the percentile of the added values (such as 95%th) since the last reset.  The
        accuracy of this estimate will depend on the granularity of the original buckets.

        @param percentile:  The percentile to estimate, from 0 to 1.
        @type percentile: Number

        @return: The estimated percentile or None if no values have been added.
        @rtype: Number or None
        """
        if percentile > 1.0:
            raise ValueError("Percentile must be between 0 and 1.")

        if self.__total_count == 0:
            return None

        # The first step is to calculate which bucket this percentile lands in.  We do this by calculating the "index"
        # of what that percentile's sample would have been.  For example, if we are calculating the 75% and there were
        # 100 values, then the 75% would be the 75th value in sorted order.
        target_count = self.__total_count * percentile

        cumulative_count = 0

        # Now find the bucket by going over the buckets, keeping track of the cumulative counts across all buckets.
        for bucket_count, lower_bound, upper_bound in self.buckets(
            disable_last_bucket_padding=True
        ):
            cumulative_count = cumulative_count + bucket_count
            if target_count <= cumulative_count:
                # Ok, we found the bucket.  To minimize error, we estimate the value of the percentile to be the
                # midpoint between the lower and upper bounds.
                return (upper_bound + lower_bound) / 2.0

        # We should never get here because target_count will always be <= the total counts across all buckets.

    def count(self):
        """
        @return: The number of samples added to this instance, since the last `reset`.
        @rtype: int
        """
        return self.__total_count

    def min(self):
        """
        @return: The minimum value of all samples added to this instance, since the last `reset`.
        @rtype: Number
        """
        return self.__min

    def max(self):
        """
        @return: The maximum value of all samples added to this instance, since the last `reset`.
        @rtype: Number
        """
        return self.__max

    def reset(self):
        """Resets all the instance, discarding all information about all previously added samples.
        """
        for i in range(0, len(self.__counts)):
            self.__counts[i] = 0
        self.__overflow = 0
        self.__total_count = 0
        self.__total_values = 0
        self.__min = None
        self.__max = None

    def summarize(self):
        """
        Returns a string summarizing the histogram.
        :return:
        :rtype:
        """
        if self.__total_count == 0:
            return "(count=0)"

        # noinspection PyStringFormat
        return "(count=%ld,avg=%.2lf,min=%.2lf,max=%.2lf,median=%.2lf)" % (
            self.count(),
            self.average(),
            self.min(),
            self.max(),
            self.estimate_median(),
        )
