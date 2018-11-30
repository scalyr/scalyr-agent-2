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
from __future__ import division

import sys
import struct
import thread

__author__ = 'czerwin@scalyr.com'

import base64
import calendar
import datetime
import os
import random
import threading
import time

import scalyr_agent.json_lib as json_lib
from scalyr_agent.json_lib import parse, JsonParseException
from scalyr_agent.platform_controller import CannotExecuteAsUser

# Use sha1 from hashlib (Python 2.5 or greater) otherwise fallback to the old sha module.
try:
    from hashlib import sha1
except ImportError:
    from sha import sha as sha1


try:
    # For Python >= 2.5
    from hashlib import md5
    new_md5 = True
except ImportError:
    import md5
    new_md5 = False


try:
    import scalyr_agent.third_party.uuid_tp.uuid as uuid
except ImportError:
    uuid = None

def _fallback_json_encode( obj ):
    return json_lib.serialize( obj )

def _fallback_json_decode( text ):
    return json_lib.parse( text )

_json_lib = 'json_lib'

_json_encode = _fallback_json_encode
_json_decode = _fallback_json_decode

try:
    import ujson
    _json_lib = 'ujson'
    _json_encode = ujson.dumps
    _json_decode = ujson.loads
except ImportError:
    try:
        import json
        _json_lib = 'json'
        _json_encode = json.dumps
        _json_decode = json.loads
    except:
        pass

def get_json_lib():
    return _json_lib

def json_encode( obj ):
    """ Encodes an object as json """
    return _json_encode( obj )

def json_decode( text ):
    """ Decodes text containing json and returns a dict containing the contents """
    return _json_decode( text )

def value_to_bool( value ):
    value_type = type(value)
    if value_type is bool:
        return value
    elif value_type is int:
        return self.__num_to_bool(field, float(value))
    elif value_type is long:
        return self.__num_to_bool(field, float(value))
    elif value_type is float:
        return self.__num_to_bool(field, value)
    elif value_type is str or value_type is unicode:
        return not value == "" and not value == "f" and not value.lower() == "false"
    elif value is None:
        return False

    raise ValueError( "Cannot convert %s value to bool: %s" % (str(value_type), str( value ) ))

def read_file_as_json(file_path):
    """Reads the entire file as a JSON value and return it.

    @param file_path: the path to the file to read
    @type file_path: str

    @return: The JSON value contained in the file.  This is typically a JsonObject, but could be primitive
        values such as int or str if that is all the file contains.

    @raise JsonReadFileException:  If there is an error reading the file.
    """
    f = None
    try:
        try:
            if not os.path.isfile(file_path):
                raise JsonReadFileException(file_path, 'The file does not exist.')
            if not os.access(file_path, os.R_OK):
                raise JsonReadFileException(file_path, 'The file is not readable.')
            f = open(file_path, 'r')
            data = f.read()
            return parse(data)
        except IOError, e:
            raise JsonReadFileException(file_path, 'Read error occurred: ' + str(e))
        except JsonParseException, e:
            raise JsonReadFileException(file_path, "JSON parsing error occurred: %s (line %i, byte position %i)" % (
                e.raw_message, e.line_number, e.position))
    finally:
        if f is not None:
            f.close()

def atomic_write_dict_as_json_file( file_path, tmp_path, info ):
    """Write a dict to a JSON encoded file
    The file is first completely written to tmp_path, and then renamed to file_path

    @param: file_path: The final path of the file
    @param: tmp_path: A temporary path to write the file to
    @param: info: A dict containing the JSON object to write
    """
    fp = None
    try:
        fp = open(tmp_path, 'w')
        fp.write(json_lib.serialize(info))
        fp.close()
        fp = None
        if sys.platform == 'win32' and os.path.isfile(file_path):
            os.unlink(file_path)
        os.rename(tmp_path, file_path)
    except (IOError, OSError):
        if fp is not None:
            fp.close()
        import scalyr_agent.scalyr_logging

        scalyr_agent.scalyr_logging.getLogger(__name__).exception(
            'Could not write checkpoint file due to error', error_code='failedCheckpointWrite')

def create_unique_id():
    """
    @return: A value that will be unique for all values generated by all machines.  The value
        is also encoded so that is safe to be used in a web URL.
    @rtype: str
    """
    if uuid is not None and hasattr(uuid, 'uuid1'):
        # Here the uuid should be based on the mac of the machine.
        base_value = uuid.uuid1().bytes
        method = 'a'
    else:
        # Otherwise, get as good of a 16 byte random number as we can and prefix it with
        # the current time.
        try:
            base_value = os.urandom(16)
            method = 'b'
        except NotImplementedError:
            base_value = ''
            for i in range(16):
                base_value += random.randrange(256)
            method = 'c'
        base_value = str(time.time()) + base_value
    result = base64.urlsafe_b64encode(sha1(base_value).digest()) + method
    return result


def md5_digest(data):
    """
    Returns the md5 digest of the input data
    @param data: data to be digested(hashed)
    @type data: str
    @rtype: str
    """

    if not (data and isinstance(data, basestring)):
        raise Exception('invalid data to be hashed: %s', repr(data))

    if not new_md5:
        m = md5.new()
    else:
        m = md5()
    m.update(data)
    return m.digest()


def remove_newlines_and_truncate(input_string, char_limit):
    """Returns the input string but with all newlines removed and truncated.

    The newlines are replaced with spaces.  This is done both for carriage return and newline.

    Note, this does not add ellipses for the truncated text.

    @param input_string: The string to transform
    @param char_limit: The maximum number of characters the resulting string should be

    @type input_string: str
    @type char_limit: int

    @return:  The string with all newlines replaced with spaces and truncated.
    @rtype: str
    """
    return input_string.replace('\n', ' ').replace('\r', ' ')[0:char_limit]

def microseconds_since_epoch( date_time, epoch=None ):
    """Returns the number of microseconds since the specified date time and the epoch.

    @param date_time: a datetime.datetime object.
    @param epoch: the beginning of the epoch, if None defaults to Jan 1, 1970

    @type date_time: datetime.datetime
    @type epoch: datetime.datetime
    """
    if not epoch:
        epoch = datetime.datetime.utcfromtimestamp( 0 )

    delta = date_time - epoch

    #86400 is 24 * 60 * 60 e.g. total seconds in a day
    return (delta.microseconds + (delta.seconds + delta.days * 86400) * 10**6)

def seconds_since_epoch( date_time, epoch=None ):
    """Returns the number of seconds since the specified date time and the epoch.

    @param date_time: a datetime.datetime object.
    @param epoch: the beginning of the epoch, if None defaults to Jan 1, 1970

    @type date_time: datetime.datetime
    @type epoch: datetime.datetime

    @rtype float
    """
    return microseconds_since_epoch( date_time ) / 10.0**6

def rfc3339_to_datetime( string ):
    """Returns a date time from a rfc3339 formatted timestamp.

    We have to do some tricksy things to support python 2.4, which doesn't support
    datetime.strptime or the fractional component %f in format strings

    This doesn't do any complex testing and assumes the string is well formed
    and in UTC (e.g. uses Z at the end rather than a time offset)

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
    if parts[0].endswith( 'Z' ):
        parts[0] = parts[0][:-1]

    #create a datetime object
    try:
        tm = time.strptime( parts[0], "%Y-%m-%dT%H:%M:%S" )
    except ValueError, e:
        return None

    dt = datetime.datetime( *(tm[0:6]) )

    #now add the fractional part
    if len( parts ) > 1:
        fractions = parts[1]
        #if we had a fractional component it should terminate in a Z
        if not fractions.endswith( 'Z' ):
            #we don't handle non UTC timezones yet
            if any(c in fractions for c in '+-'):
                return None
            return dt

        # remove the Z and just process the fraction.
        fractions = fractions[:-1]
        to_micros = 6 - len(fractions)
        micro = int( int( fractions ) * 10**to_micros )
        dt = dt.replace( microsecond=micro )

    return dt

def rfc3339_to_nanoseconds_since_epoch( string ):
    """Returns nanoseconds since the epoch from a rfc3339 formatted timestamp.

    We have to do some tricksy things to support python 2.4, which doesn't support
    datetime.strptime or the fractional component %f in format strings

    This doesn't do any complex testing and assumes the string is well formed
    and in UTC (e.g. uses Z at the end rather than a time offset)

    @param string: a date/time in rfc3339 format, e.g. 2015-08-03T09:12:43.143757463Z

    @rtype long
    """
    # split the string in to main time and fractional component
    parts = string.split(".")

    # it's possible that the time does not have a fractional component
    # e.g 2015-08-03T09:12:43Z, in this case 'parts' will only have a
    # single element that should end in Z.  Strip the Z if it exists
    # so we can use the same format string for processing the main
    # date+time regardless of whether the time has a fractional component.
    if parts[0].endswith( 'Z' ):
        parts[0] = parts[0][:-1]

    #create a datetime object
    try:
        tm = time.strptime( parts[0], "%Y-%m-%dT%H:%M:%S" )
    except ValueError, e:
        return None

    nano_seconds = long( calendar.timegm( tm[0:6] ) ) * 1000000000L
    nanos = 0

    #now add the fractional part
    if len( parts ) > 1:
        fractions = parts[1]
        # if the fractional part doesn't end in Z we likely have a
        # malformed time, so just return the current value
        if not fractions.endswith( 'Z' ):
            #we don't handle non UTC timezones yet
            if any(c in fractions for c in '+-'):
                return None

            return nano_seconds

        # strip the final 'Z' and use the final number for processing
        fractions = fractions[:-1]
        to_nanos = 9 - len(fractions)
        nanos = long( long( fractions ) * 10**to_nanos )

    return nano_seconds + nanos

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
        return 'Never'
    else:
        result = '%s UTC' % (time.asctime(time.gmtime(time_value)))
        # Windows uses a leading 0 on the day of month field, which makes it different behavior from Linux
        # which uses a space in place of the leading 0.  For tests, we need this to behave the same, so we spend
        # the small effort here to make it work.  At least, that leading 0 is always in the same place.
        if result[8] == '0':
            result = '%s %s' % (result[:8], result[9:])
        return result

def get_pid_tid():
    """Returns a string containing the current process and thread id in the format "(pid=%pid) (tid=%tid)".
    @return: The string containing the process and thread id.
    @rtype: str
    """
    # noinspection PyBroadException
    try:
        return "(pid=%s) (tid=%s)" % (str(os.getpid()), str(thread.get_ident()))
    except:
        return "(pid=%s) (tid=Unknown)" % (str(os.getpid()))


class JsonReadFileException(Exception):
    """Raised when a failure occurs when reading a file as a JSON object."""
    def __init__(self, file_path, message):
        self.file_path = file_path
        self.raw_message = message

        Exception.__init__(self, "Failed while reading file '%s': %s" % (file_path, message))


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

        while deadline > self.__fake_clock.time() and self.is_running():
            self.__fake_clock.simulate_waiting()

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

    def simulate_waiting(self):
        """Will block the current thread until either the current time is changed or `wall_all_threads` is invoked.

        Since this can return even when the fake clock time has not changed, it is up to the calling thread to check
        to see if time has advanced far enough for any condition they wish.  However, it is typically expected that
        they will not only be waiting for a particular time but also on some other condition, such as whether or not
        a condition is has been notified.
        """
        self._time_condition.acquire()
        self._increment_waiting_count(1)

        self._time_condition.wait()

        self._increment_waiting_count(-1)
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


class StoppableThread(threading.Thread):
    """A slight extension of a thread that uses a RunState instance to track if it should still be running.

    This abstraction also allows the caller to receive any exception that is raised during execution
    by calling `join`.

    It is expected that the run method or target of this thread periodically calls `_run_state.is_stopped`
    to determine if the thread has been stopped.
    """
    def __init__(self, name=None, target=None, fake_clock=None):
        """Creates a new thread.

        You must invoke `start` to actually have the thread begin running.

        Note, if you set `target` to None, then the thread will invoked `run_and_propagate` instead of `run` to
        execute the work for the thread.  You must override `run_and_propagate` instead of `run`.

        @param name: The name to give the thread.
        @param target: If not None, a function that will be invoked when the thread is invoked to perform
            the work for the thread.  This function should accept a single argument, the `RunState` instance
            that will signal when the thread should stop work.
        @param fake_clock:  A fake clock to control the time and when threads wake up for tests.

        @type name: str
        @type target: None|func
        @type fake_clock: FakeClock|None
        """
        threading.Thread.__init__(self, name=name, target=self.__run_impl)
        self.__target = target
        self.__exception_info = None
        # Tracks whether or not the thread should still be running.
        self._run_state = RunState(fake_clock=fake_clock)

    def __run_impl(self):
        """Internal run implementation.
        """
        # noinspection PyBroadException
        try:
            if self.__target is not None:
                self.__target(self._run_state)
            else:
                self.run_and_propagate()
        except Exception, e:
            self.__exception_info = sys.exc_info()
            print >> sys.stderr, 'Received exception from run method in StoppableThread %s' % str(e)
            return None

    def run_and_propagate(self):
        """Derived classes should override this method instead of `run` to perform their work.

        This allows for the base class to catch any raised exceptions and propagate them during the join call.
        """
        pass

    def stop(self, wait_on_join=True, join_timeout=5):
        """Stops the thread from running.

        By default, this will also block until the thread has completed (by performing a join).

        @param wait_on_join: If True, will block on a join of this thread.
        @param join_timeout: The maximum number of seconds to block for the join.
        """
        self._run_state.stop()
        if wait_on_join:
            self.join(join_timeout)

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
            raise self.__exception_info[0], self.__exception_info[1], self.__exception_info[2]


class RateLimiter(object):
    """An abstraction that can be used to enforce some sort of rate limit, expressed as a maximum number
    of bytes to be consumed over a period of time.

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
        if current_time is None:
            current_time = time.time()

        fill_amount = (current_time - self.__last_bucket_fill_time) * self.__bucket_fill_rate

        self.__bucket_contents = min(self.__bucket_size, self.__bucket_contents + fill_amount)
        self.__last_bucket_fill_time = current_time

        if num_bytes <= self.__bucket_contents:
            self.__bucket_contents -= num_bytes
            return True

        return False


class ScriptEscalator(object):
    """Utility that helps re-execute the current script using the user account that owns the
    configuration file.

    Most Scalyr scripts expect to run as the user that owns the configuration file.  If the current user is
    not the owner, but they are privileged enough to execute a process as that owner, then we will do it.

    This is platform dependent.  For example, Linux will re-execute the script if the current user is 'root',
    where as Windows will prompt the user for the Administrator's password.
    """

    def __init__(self, controller, config_file_path, current_working_directory, no_change_user = False):
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

            # See if this is a py2exe executable.  If so, then we do not have a script file, but a binary executable
            # that contains the script.
            if hasattr(sys, 'frozen'):
                script_binary = sys.executable
            else:
                # We use the __main__ symbolic module to determine which file was invoked by the python script.
                # noinspection PyUnresolvedReferences
                import __main__
                script_file_path = __main__.__file__
                if not os.path.isabs(script_file_path):
                    script_file_path = os.path.normpath(os.path.join(self.__cwd, script_file_path))

            return self.__controller.run_as_user(self.__desired_user, script_file_path, script_binary, script_args)
        except CannotExecuteAsUser, e:
            if not handle_error:
                raise e
            print >> sys.stderr, ('Failing, cannot %s as the correct user.  The command must be executed using the '
                                  'same account that owns the configuration file.  The configuration file is owned by '
                                  '%s whereas the current user is %s.  Changing user failed due to the following '
                                  'error: "%s". Please try to re-execute the command as %s' % (description,
                                                                                               self.__desired_user,
                                                                                               self.__running_user,
                                                                                               e.error_message,
                                                                                               self.__desired_user))
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
            raise RedirectorError('Client did not connect to server within %lf seconds' % timeout)

        self.__old_stdout = self.__sys.stdout
        self.__old_stderr = self.__sys.stderr

        self.__sys.stdout = RedirectorServer.Redirector(RedirectorServer.STDOUT_STREAM_ID, self._write_stream)
        self.__sys.stderr = RedirectorServer.Redirector(RedirectorServer.STDERR_STREAM_ID, self._write_stream)

    def stop(self):
        """Signals the client connection that all bytes have been sent and then resets stdout and stderr to
        their original values.
        """
        # This will result in a -1 being written to the stream, indicating the server is closing down.
        self._write_stream(-1, '')

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
        encoded_content = unicode(content).encode('utf-8')
        # When we send over a chunk of bytes to the client, we prefix it with a code that identifies which
        # stream it should go to (stdout or stderr) and how many bytes we are sending.  To encode this information
        # into a single integer, we just shift the len of the bytes over by one and set the lower bit to 0 if it is
        # stdout, or 1 if it is stderr.
        code = len(encoded_content) * 2 + stream_id

        self.__channel_lock.acquire()
        try:
            if self.__channel_lock is not None:
                self.__channel.write(struct.pack('i', code) + encoded_content)
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
            while self._is_running():
                if self.__channel.connect():
                    connected = True
                    break

                self._sleep_for_busy_loop(overall_deadline, 'connection to be made.')

            # If we aren't running any more, then return.  This could happen if the creator of this instance
            # called the `stop` method before we connected.
            if not self._is_running():
                return

            if not connected:
                raise RedirectorError('Could not connect to other endpoint before timeout.')

            # Keep looping, accepting new bytes and writing them to the appropriate stream.
            while self._is_running():
                # Busy loop waiting for more bytes.
                if not self.__wait_for_available_bytes(overall_deadline):
                    break

                # Read one integer which should contain both the number of bytes of content that are being sent
                # and which stream it should be written to.  The stream id is in the lower bit, and the number of
                # bytes is shifted over by one.
                code = struct.unpack('i', self.__channel.read(4))[0]    # Read str length

                # The server sends -1 when it wishes to close the stream.
                if code < 0:
                    break

                bytes_to_read = code >> 1
                stream_id = code % 2

                content = self.__channel.read(bytes_to_read).decode('utf-8')

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
        while self._is_running():
            (num_bytes_available, result) = self.__channel.peek()
            if result != 0:
                raise RedirectorError('Error while waiting for more bytes from redirect server error=%d' % result)
            if num_bytes_available > 0:
                return True
            self._sleep_for_busy_loop(overall_deadline, 'more bytes to be read')
        return False

    def _is_running(self):
        """Returns true if this thread is still running.
        @return: True if this thread is still running.
        @rtype: bool
        """
        return self._run_state.is_running()

    # The amount of time we sleep while doing a busy wait loop waiting for the client to connect or for new byte
    # to become available.
    BUSY_LOOP_POLL_INTERVAL = .03

    def _sleep_for_busy_loop(self, deadline, description):
        """Sleeps for a small unit of time as part of a busy wait loop.

        This method will return if either the small unit of time has exceeded, the overall deadline has been exceeded,
        or if the `stop` method of this thread has been invoked.

        @param deadline: The walltime that this operation should time out.  This method will sleep for the small of
            BUSY_LOOP_POLL_INTERVAL or the difference between now and walltime.
        @param description: A description of why we waiting to be used in error output.

        @type deadline: float
        @type description: str
        """
        timeout = deadline - self.__time()
        if timeout < 0:
            raise RedirectorError('Deadline exceeded while waiting for %s' % description)
        elif timeout > RedirectorClient.BUSY_LOOP_POLL_INTERVAL:
            timeout = RedirectorClient.BUSY_LOOP_POLL_INTERVAL
        self._run_state.sleep_but_awaken_if_stopped(timeout)

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
