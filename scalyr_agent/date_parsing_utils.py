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

All the functions for parsing dates in RFC3339 format have been optimized for performance since
they are part of a critical code path when ingesting Docker / Kubernetes logs.

Per micro benchmarks (benchmarks/micro/test_date_parsing.py), "udatetime" based implementations are
the fastest.

All the functions also support time formats in arbitrary timezones (aka non-UTC), but non-udatetime
pure Python versions fall back on python-dateutil which is rather slow. Luckily the common case and
code path is UTC where we can skip that code path.

It's also worth noting that our custom implementations also supports some extended formats which are
not fully valid as per RFC (e.g. very long fractional part). Because of that, some compatibility
change needed to be implemented for udatetime implementation as well and that adds small amount of
overhead.
"""

from __future__ import absolute_import

if False:  # NOSONAR
    from typing import Optional
    from typing import List

import re
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

try:
    from dateutil.parser import isoparse  # NOQA
except ImportError:
    isoparse = None


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
    # type: (str) -> bool
    """
    Returns True if the provided RFC3339 strings contains a non UTC timezone.
    """
    return bool(RFC3339_STR_NON_UTC_REGEX.match(string))


def _rfc3339_to_nanoseconds_since_epoch_string_split(string):
    # type: (str) -> Optional[int]
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes string.split approach.

    Returns nanoseconds from unix epoch from a rfc3339 formatted timestamp.

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
    # type: (str) -> Optional[int]
    """
    Special version of rfc3339_to_nanoseconds_since_epoch which supports timezones and uses
    dateutil library.

    NOTE: python-dateutil is slow so using udatetime is preferred when timestamp is non-UTC.
    """
    dt = _rfc3339_to_datetime_dateutil(string)

    nano_seconds = (
        calendar.timegm((dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second))
        * 1000000000
    )

    nanos = _get_fractional_nanos(value=string)
    return nano_seconds + nanos


def _rfc3339_to_nanoseconds_since_epoch_udatetime(string):
    # type: (str) -> Optional[int]
    """
    rfc3339_to_nanoseconds_since_epoch variation which utilizes udatetime library.
    """
    original_string = string
    string = _get_udatetime_safe_string(string)

    try:
        dt = udatetime.from_string(string)
    except ValueError:
        # For backward compatibility reasons with other functions we return None on edge cases
        # (e.g. invalid format or similar). Not great.
        return None

    # NOTE: udatetime supports tzinfo, but this function always return non-timezone aware objects
    # UTC so we perform the conversion here.
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
    # type: (str) -> Optional[datetime.datetime]
    """
    Special version of rfc3339_to_datetime which supports timezones and uses dateutil library
    underneath.

    NOTE: Other functions which don't support timezones have been heavily optimized for performance
    so using this function will have non trivial overhead.
    """
    if not isoparse:
        # Library not available, warning is already emitted on import (emitting it on each call
        # could get very noisy)
        return None

    try:
        return isoparse(string).astimezone(TZ_UTC).replace(tzinfo=None)
    except Exception:
        return None


def _rfc3339_to_datetime_udatetime(string):
    # type: (str) -> Optional[datetime.datetime]
    """
    rfc3339_to_datetime variation which utilizes udatetime library.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    string = _get_udatetime_safe_string(string)

    try:
        dt = udatetime.from_string(string)
    except ValueError:
        # For backward compatibility reasons with other functions we return None on edge cases
        # (e.g. invalid format or similar). Not great.
        return None

    # NOTE: udatetime supports tzinfo, but this function always return non-timezone aware objects
    # UTC so we perform the conversion here.
    if dt.tzinfo and dt.tzinfo.offset != 0:
        dt = dt.astimezone(TZ_UTC)

    dt = dt.replace(tzinfo=None)
    dt = _add_fractional_part_to_dt(dt=dt, parts=parts)
    return dt


def _get_udatetime_safe_string(string):
    # type: (str) -> str
    """
    Function which returns RFC3339 string which can be safely passed to udatetime.

    udatetime doesn't support values with many fractional components, but our custom implementation
    does.

    To work around that, we pass date + time + timezone string to udatetime to handle the parsing
    and then handle fractional part (nanoseconds) ourselves.
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    if len(parts) > 1:
        if parts[1].endswith("Z"):
            # UTC, string ends with Z
            return parts[0]
        elif "+" in parts[1] or "-" in parts[1]:
            # Custom timezone (e.g. -08:00), we strip it and move it to the string which we parse
            # to udatetime. This way udatetime handles time zone conversion and we handle
            # nanoseconds manually (since udatetime doesn't support non valid dates with large
            # fractional parts)
            tz_str = parts[1][-6:]
            return parts[0] + tz_str

    return string


def _add_fractional_part_to_dt(dt, parts):
    # type: (datetime.datetime, List[str]) -> datetime.datetime
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
    # type: (str) -> int
    """
    Return nanoseconds (if any) for the provided date string fractional part of the RFC3336 value.
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
