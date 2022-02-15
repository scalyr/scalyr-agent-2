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

# Work around with a striptime race we see every now and then with docker monitor run() method.
# That race would occur very rarely, since it depends on the order threads are started and when
# strptime is first called.
# See:
# 1. https://github.com/scalyr/scalyr-agent-2/pull/700#issuecomment-761676613
# 2. https://bugs.python.org/issue7980
import _strptime  # NOQA

import six
from six.moves import map

try:
    import udatetime
except ImportError:
    # if udatetime is not available, we fall back to the second fastest approach for date parsing
    # (string.split approach)
    udatetime = None

from dateutil.parser import isoparse
from dateutil.tz import UTC as TZ_UTC

from scalyr_agent.compat import custom_any as any


if six.PY3:
    # re.ASCII makes this regex only match ASCII digits which is tiny bit faster than the version
    # without re.ASCII flag
    RFC3339_STR_REGEX = re.compile(
        r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", re.ASCII
    )
    RFC3339_STR_NON_UTC_REGEX = re.compile(r"^.*[\+\-](\d{2}):(\d{2})$", re.ASCII)
else:
    RFC3339_STR_REGEX = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})")
    RFC3339_STR_NON_UTC_REGEX = re.compile(r"^.*[\+\-](\d{2}):(\d{2})$")


ZERO = datetime.timedelta(0)


class UTC(datetime.tzinfo):
    def utcoffset(self, dt):
        return ZERO

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return ZERO


TZ_UTC = UTC()


def _contains_non_utc_tz(string):
    """
    Returns True if the provided date time strings contains a non UTC timezone.
    """
    return bool(RFC3339_STR_NON_UTC_REGEX.match(string))


# Private versions of datetime parsing functions are below. Those are not used by the production
# code, but there are there so we can test corectness of all the functions and benchmark different
# implementations and compare them.
def _rfc3339_to_nanoseconds_since_epoch_strptime(string):
    # type: (str) -> Optional[int]
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes strptime approach.
    """
    if _contains_non_utc_tz(string):
        return _rfc3339_to_nanoseconds_since_epoch_dateutil(string)

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
    nanos = _get_fractional_nanos(value=string)
    return nano_seconds + nanos


def _rfc3339_to_nanoseconds_since_epoch_regex(string):
    # type: (str) -> Optional[int]
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes regex approach.
    """
    if _contains_non_utc_tz(string):
        return _rfc3339_to_nanoseconds_since_epoch_dateutil(string)

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
        calendar.timegm(
            (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)
        )
        * 1000000000
    )

    nanos = _get_fractional_nanos(value=string)
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
    if _contains_non_utc_tz(string):
        dt = _rfc3339_to_datetime_dateutil(string)
    else:
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
        calendar.timegm(
            (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)
        )
        * 1000000000
    )

    nanos = _get_fractional_nanos(value=string)
    return nano_seconds + nanos


def _rfc3339_to_nanoseconds_since_epoch_dateutil(string):
    """
    Special version of rfc3339_to_nanoseconds_since_epoch which supports timezones and uses
    dateutil library.

    NOTE: Other functions which don't support timezones have been heavily optimized for performance
    so using this function will likely have non trivial overhead.
    """
    dt = _parse_rfc3339_with_non_utc_tz_datetutil(string)

    nano_seconds = (
        calendar.timegm((dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second))
        * 1000000000
    )

    nanos = _get_fractional_nanos(value=string)
    return nano_seconds + nanos


def _rfc3339_to_nanoseconds_since_epoch_udatetime(string):
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes udatetime library.
    """
    original_string = string

    # split the string in to main time and fractional component
    parts = string.split(".")

    # Special case for backward compatibility with our custom implementations which accept
    # formats with too many fractional components which are not valid as per RFC.
    # TODO: Also handle this invalid format for non UTC timezones
    if len(parts) > 1 and parts[1].endswith("Z"):
        string = parts[0]

    # NOTE: udatetime supports tzinfo, but this function always return non-timezone aware objects
    # UTC so we perform the conversion here.
    try:
        dt = udatetime.from_string(string)
    except ValueError:
        # For backward compatibility reasons with other functions we return None on edge cases
        # (e.g. invalid format or similar). Not great.
        return None

    if dt.tzinfo and dt.tzinfo.offset != 0:
        dt = dt.astimezone(TZ_UTC)

    dt = dt.replace(tzinfo=None)

    nano_seconds = (
        calendar.timegm(
            (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond)
        )
        * 1000000000
    )

    nanos = _get_fractional_nanos(value=original_string)
    return nano_seconds + nanos


def _rfc3339_to_datetime_strptime(string):
    # type: (str) -> Optional[datetime.datetime]
    """
    rfc3339_to_datetime variation which utilizes strptime approach.
    """
    if _contains_non_utc_tz(string):
        return _rfc3339_to_datetime_dateutil(string)

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
    dt = _add_fractional_part_to_dt(dt=dt, parts=parts)
    return dt


def _rfc3339_to_datetime_regex(string):
    # type: (str) -> Optional[datetime.datetime]
    """
    rfc3339_to_datetime variation which utilizes regex approach.
    """
    if _contains_non_utc_tz(string):
        return _rfc3339_to_datetime_dateutil(string)

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

    dt = _add_fractional_part_to_dt(dt=dt, parts=parts)
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
    if _contains_non_utc_tz(string):
        return _rfc3339_to_datetime_dateutil(string)

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

    dt = _add_fractional_part_to_dt(dt=dt, parts=parts)
    return dt


def _rfc3339_to_datetime_dateutil(string):
    """
    Special version of rfc3339_to_datetime which supports timezones and uses dateutil library
    underneath.

    NOTE: Other functions which don't support timezones have been heavily optimized for performance
    so using this function will have non trivial overhead.
    """
    try:
        return isoparse(string).astimezone(TZ_UTC).replace(tzinfo=None)
    except Exception:
        return None


def _rfc3339_to_datetime_udatetime(string):
    # type: (str) -> Optional[datetime.datetime]
    """
    rfc3339_to_datetime variation which utilizes udatetime library.

    NOTE: udatetime supports values with timezone information.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # Special case for backward compatibility with our custom implementations which accept
    # formats with too many fractional components which are not valid as per RFC.
    # TODO: Also handle this invalid format for non UTC timezones
    if len(parts) > 1 and parts[1].endswith("Z"):
        string = parts[0]

    # NOTE: udatetime supports tzinfo, but this function always return non-timezone aware objects
    # UTC so we perform the conversion here.
    try:
        dt = udatetime.from_string(string)
    except ValueError:
        # For backward compatibility reasons with other functions we return None on edge cases
        # (e.g. invalid format or similar). Not great.
        return None

    if dt.tzinfo and dt.tzinfo.offset != 0:
        dt = dt.astimezone(TZ_UTC)

    dt = dt.replace(tzinfo=None)
    dt = _add_fractional_part_to_dt(dt=dt, parts=parts)
    return dt


def _add_fractional_part_to_dt(dt, parts):
    """
    Add fractional part (if any) to the provided datetime object.
    """
    if len(parts) < 2:
        # No fractional component
        return dt

    fractions = parts[1]
    # strip the tzinfo
    if fractions.endswith("Z"):
        # in UTC, with Z at the end
        fractions = fractions[:-1]
    elif "-" not in fractions and "+" not in fractions:
        # in UTC, without Z at the end (nothing to strip)
        pass
    else:
        # Custom timezone offset, e.g. -08:00
        fractions = fractions[:-6]

    to_micros = 6 - len(fractions)
    micro = int(int(fractions) * 10**to_micros)
    dt = dt.replace(microsecond=micro)
    return dt


def _get_fractional_nanos(value):
    """
    Return nanoseconds (if any) for the provided date string fractional part.
    """
    parts = value.split(".")

    if len(parts) < 2:
        return 0

    fractions = parts[1]

    # strip the tzinfo
    if fractions.endswith("Z"):
        # in UTC, with Z at the end
        fractions = fractions[:-1]
    elif "-" not in fractions and "+" not in fractions:
        # in UTC, without Z at the end (nothing to strip)
        pass
    else:
        # Custom timezone offset, e.g. -08:00
        fractions = fractions[:-6]

    to_nanos = 9 - len(fractions)
    nanos = int(int(fractions) * 10**to_nanos)
    return nanos


if udatetime:
    rfc3339_to_nanoseconds_since_epoch = _rfc3339_to_nanoseconds_since_epoch_udatetime
    rfc3339_to_datetime = _rfc3339_to_datetime_udatetime
else:
    rfc3339_to_nanoseconds_since_epoch = (
        _rfc3339_to_nanoseconds_since_epoch_string_split
    )
    rfc3339_to_datetime = _rfc3339_to_datetime_string_split
