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

"""
Module containing various date parsing related utility functions.
"""

from __future__ import absolute_import

if False:  # NOSONAR
    from typing import Optional

import re
import time
import calendar
import datetime

import six
from six.moves import map

try:
    import udatetime
except ImportError:
    # if udatetime is not available, we fall back to the second fastest approach for date parsing
    # (string.split approach)
    udatetime = None

from scalyr_agent.compat import custom_any as any


if six.PY3:
    # re.ASCII makes this regex only match ASCII digits which is tiny bit faster than the version
    # without re.ASCII flag
    RFC3339_STR_REGEX = re.compile(
        r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", re.ASCII
    )
else:
    RFC3339_STR_REGEX = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})")


# Private versions of datetime parsing functions are below. Those are not used by the production
# code, but there are there so we can test corectness of all the functions and benchmark different
# implementations and compare them.
def _rfc3339_to_nanoseconds_since_epoch_strptime(string):
    # type: (str) -> Optional[int]
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes strptime approach.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith("Z"):
        parts[0] = parts[0][:-1]

    try:
        tm = time.strptime(parts[0], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None

    nano_seconds = int(calendar.timegm(tm[0:6])) * 1000000000

    nanos = 0

    # now add the fractional part
    if len(parts) > 1:
        fractions = parts[1]
        # if the fractional part doesn't end in Z we likely have a
        # malformed time, so just return the current value
        if not fractions.endswith("Z"):
            # we don't handle non UTC timezones yet
            if any(c in fractions for c in "+-"):
                return None

            return nano_seconds

        # strip the final 'Z' and use the final number for processing
        fractions = fractions[:-1]
        to_nanos = 9 - len(fractions)
        nanos = int(int(fractions) * 10 ** to_nanos)

    return nano_seconds + nanos


def _rfc3339_to_nanoseconds_since_epoch_regex(string):
    # type: (str) -> Optional[int]
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes regex approach.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith("Z"):
        parts[0] = parts[0][:-1]

    try:
        dt = datetime.datetime(
            *list(map(int, RFC3339_STR_REGEX.match(parts[0]).groups()))  # type: ignore
        )
    except Exception:
        return None

    nano_seconds = (
        calendar.timegm((dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second))
        * 1000000000
    )

    nanos = 0

    # now add the fractional part
    if len(parts) > 1:
        fractions = parts[1]
        # if the fractional part doesn't end in Z we likely have a
        # malformed time, so just return the current value
        if not fractions.endswith("Z"):
            # we don't handle non UTC timezones yet
            if any(c in fractions for c in "+-"):
                return None

            return nano_seconds

        # strip the final 'Z' and use the final number for processing
        fractions = fractions[:-1]
        to_nanos = 9 - len(fractions)
        nanos = int(int(fractions) * 10 ** to_nanos)

    return nano_seconds + nanos


def _rfc3339_to_nanoseconds_since_epoch_string_split(string):
    # type: (str) -> Optional[int]
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes string.split approach.

    Returns nanoseconds from unix epoch from a rfc3339 formatted timestamp.

    This doesn't do any complex testing and assumes the string is well formed and in UTC (e.g.
    uses Z at the end rather than a time offset).

    @param string: a date/time in rfc3339 format, e.g. 2015-08-03T09:12:43.143757463Z
    @rtype int
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith("Z"):
        parts[0] = parts[0][:-1]

    try:
        date_parts, time_parts = parts[0].split("T")
        date_parts = date_parts.split("-")  # type: ignore
        time_parts = time_parts.split(":")  # type: ignore

        dt = datetime.datetime(
            int(date_parts[0]),
            int(date_parts[1]),
            int(date_parts[2]),
            int(time_parts[0]),
            int(time_parts[1]),
            int(time_parts[2]),
        )
    except Exception:
        return None

    nano_seconds = (
        calendar.timegm((dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second))
        * 1000000000
    )

    nanos = 0

    # now add the fractional part
    if len(parts) > 1:
        fractions = parts[1]
        # if the fractional part doesn't end in Z we likely have a
        # malformed time, so just return the current value
        if not fractions.endswith("Z"):
            # we don't handle non UTC timezones yet
            if any(c in fractions for c in "+-"):
                return None

            return nano_seconds

        # strip the final 'Z' and use the final number for processing
        fractions = fractions[:-1]
        to_nanos = 9 - len(fractions)
        nanos = int(int(fractions) * 10 ** to_nanos)

    return nano_seconds + nanos


def _rfc3339_to_nanoseconds_since_epoch_udatetime(string):
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes udatetime library.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith("Z"):
        parts[0] = parts[0][:-1]

    try:
        dt = udatetime.from_string(parts[0])
    except ValueError:
        return None

    nano_seconds = (
        calendar.timegm((dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second))
        * 1000000000
    )

    nanos = 0

    # now add the fractional part
    if len(parts) > 1:
        fractions = parts[1]
        # if the fractional part doesn't end in Z we likely have a
        # malformed time, so just return the current value
        if not fractions.endswith("Z"):
            # we don't handle non UTC timezones yet
            if any(c in fractions for c in "+-"):
                return None

            return nano_seconds

        # strip the final 'Z' and use the final number for processing
        fractions = fractions[:-1]
        to_nanos = 9 - len(fractions)
        nanos = int(int(fractions) * 10 ** to_nanos)

    return nano_seconds + nanos


def _rfc3339_to_datetime_strptime(string):
    # type: (str) -> Optional[datetime.datetime]
    """
    rfc3339_to_datetime variation which utilizes strptime approach.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith("Z"):
        parts[0] = parts[0][:-1]

    # create a datetime object
    try:
        tm = time.strptime(parts[0], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None

    dt = datetime.datetime(*(tm[0:6]))

    # now add the fractional part
    if len(parts) > 1:
        fractions = parts[1]
        # if we had a fractional component it should terminate in a Z
        if not fractions.endswith("Z"):
            # we don't handle non UTC timezones yet
            if any(c in fractions for c in "+-"):
                return None
            return dt

        # remove the Z and just process the fraction.
        fractions = fractions[:-1]
        to_micros = 6 - len(fractions)
        micro = int(int(fractions) * 10 ** to_micros)
        dt = dt.replace(microsecond=micro)

    return dt


def _rfc3339_to_datetime_regex(string):
    # type: (str) -> Optional[datetime.datetime]
    """
    rfc3339_to_datetime variation which utilizes regex approach.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith("Z"):
        parts[0] = parts[0][:-1]

    # create a datetime object
    try:
        dt = datetime.datetime(
            *list(map(int, RFC3339_STR_REGEX.match(parts[0]).groups()))  # type: ignore
        )
    except Exception:
        return None

    # now add the fractional part
    if len(parts) > 1:
        fractions = parts[1]
        # if we had a fractional component it should terminate in a Z
        if not fractions.endswith("Z"):
            # we don't handle non UTC timezones yet
            if any(c in fractions for c in "+-"):
                return None
            return dt

        # remove the Z and just process the fraction.
        fractions = fractions[:-1]
        to_micros = 6 - len(fractions)
        micro = int(int(fractions) * 10 ** to_micros)
        dt = dt.replace(microsecond=micro)

    return dt


def _rfc3339_to_datetime_string_split(string):
    # type: (str) -> Optional[datetime.datetime]
    """
    rfc3339_to_datetime variation which utilizes string.split approach.

    Returns a date time from a rfc3339 formatted timestamp.

    This doesn't do any complex testing and assumes the string is well formed and in UTC (e.g.
    uses Z at the end rather than a time offset).

    @param string: a date/time in rfc3339 format, e.g. 2015-08-03T09:12:43.143757463Z
    @rtype datetime.datetime
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith("Z"):
        parts[0] = parts[0][:-1]

    # create a datetime object
    try:
        date_parts, time_parts = parts[0].split("T")
        date_parts = date_parts.split("-")  # type: ignore
        time_parts = time_parts.split(":")  # type: ignore

        dt = datetime.datetime(
            int(date_parts[0]),
            int(date_parts[1]),
            int(date_parts[2]),
            int(time_parts[0]),
            int(time_parts[1]),
            int(time_parts[2]),
        )
    except Exception:
        return None

    # now add the fractional part
    if len(parts) > 1:
        fractions = parts[1]
        # if we had a fractional component it should terminate in a Z
        if not fractions.endswith("Z"):
            # we don't handle non UTC timezones yet
            if any(c in fractions for c in "+-"):
                return None
            return dt

        # remove the Z and just process the fraction.
        fractions = fractions[:-1]
        to_micros = 6 - len(fractions)
        micro = int(int(fractions) * 10 ** to_micros)
        dt = dt.replace(microsecond=micro)

    return dt


def _rfc3339_to_datetime_udatetime(string):
    # type: (str) -> Optional[datetime.datetime]
    """
    rfc3339_to_datetime variation which utilizes udatetime library.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith("Z"):
        parts[0] = parts[0][:-1]

    # create a datetime object
    try:
        dt = udatetime.from_string(parts[0])
        # NOTE: At this point we don't support timezones
        dt = dt.replace(tzinfo=None)
    except ValueError:
        return None

    # now add the fractional part
    if len(parts) > 1:
        fractions = parts[1]
        # if we had a fractional component it should terminate in a Z
        if not fractions.endswith("Z"):
            # we don't handle non UTC timezones yet
            if any(c in fractions for c in "+-"):
                return None
            return dt

        # remove the Z and just process the fraction.
        fractions = fractions[:-1]
        to_micros = 6 - len(fractions)
        micro = int(int(fractions) * 10 ** to_micros)
        # NOTE(Tomaz): dt.replace is quite slow...
        dt = dt.replace(microsecond=micro)

    return dt


if udatetime:
    rfc3339_to_nanoseconds_since_epoch = _rfc3339_to_nanoseconds_since_epoch_udatetime
    rfc3339_to_datetime = _rfc3339_to_datetime_udatetime
else:
    rfc3339_to_nanoseconds_since_epoch = (
        _rfc3339_to_nanoseconds_since_epoch_string_split
    )
    rfc3339_to_datetime = _rfc3339_to_datetime_string_split
