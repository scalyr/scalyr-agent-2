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
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import sys
import threading
import time
import unittest
import scalyr_agent.scalyr_logging as scalyr_logging

from scalyr_agent.util import StoppableThread

PYTHON_26_OR_OLDER = sys.version_info[:2] < (2, 7)


def _noop_skip(reason):
    def decorator(test_func_or_obj):
        if not isinstance(test_func_or_obj, type):
            def skip_wrapper(*args, **kwargs):
                print('Skipping test %s. Reason: "%s"' % (test_func_or_obj.__name__, reason))
            return skip_wrapper
        else:
            test_func_or_obj.__unittest_skip__ = True
            test_func_or_obj.__unittest_skip_why__ = reason
            return test_func_or_obj
    return decorator


def _id(obj):
    return obj


def _noop_skip_if(condition, reason):
    if condition:
        return _noop_skip(reason)
    return _id


def _noop_skip_unless(condition, reason):
    if not condition:
        return _noop_skip(reason)
    return _id


skip = _noop_skip
if hasattr(unittest, 'skip'):
    skip = unittest.skip


skipUnless = _noop_skip_unless
if hasattr(unittest, 'skipUnless'):
    skipUnless = unittest.skipUnless


skipIf = _noop_skip_if
if hasattr(unittest, 'skipIf'):
    skipIf = unittest.skipIf

# Global state as to whether or not we've started the thread watcher.  We only want one instance of this
# started per entire test suite run.
__thread_watcher_started = False


def _thread_watcher():
    """Used to detect what threads are still alive after the tests should be finished running.  In particular, this
    helps detect cases where the tests have run successfully but some thread spawned by a test case did not
    properly stop.  Since it is not a daemon thread, it will block the exit of the entire process.

    """
    # Sleep for 60 seconds since our test suites typically run in less than 15 seconds.
    time.sleep(60)

    # If we are still alive after 60 seconds, it means some test is hung or didn't join
    # its threads properly.  Let's get some information on them.
    print 'Detected hung test run.  Active threads are:'
    for t in threading.enumerate():
        print 'Active thread %s daemon=%s' % (t.getName(), str(t.isDaemon()))
    print 'Done'


def _start_thread_watcher_if_necessary():
    """Starts the thread watcher if it hasn't already been started.
    """
    global __thread_watcher_started

    if not __thread_watcher_started:
        thread = threading.Thread(name='hung thread watcher', target=_thread_watcher)
        thread.setDaemon(True)
        thread.start()
        __thread_watcher_started = True


class BaseScalyrTestCase(unittest.TestCase):
    """Used to define ScalyrTestCase below.

    This augments the standard TestCase by capturing all logged lines to stdout and
    adds protection to help detect hung test threads.
    """
    # noinspection PyPep8Naming
    def __init__(self, methodName='runTest', verify_setup_invoked=False):
        unittest.TestCase.__init__(self, methodName=methodName)
        # Add in some code to check to make sure that derived classed invoked this classes `setUp` method if
        # they overrode it.
        if verify_setup_invoked:
            self.__setup_invoked = False
            self.addCleanup(self.verify_setup_invoked)

    def setUp(self):
        # We need to reset the log destinations here because it is only at this point is stdout replaced with
        # whatever object is capturing stdout for this test case.
        scalyr_logging.set_log_destination(use_stdout=True)
        self.__setup_invoked = True

    def run(self, result=None):
        _start_thread_watcher_if_necessary()
        StoppableThread.set_name_prefix('TestCase %s: ' % str(self))
        return unittest.TestCase.run(self, result=result)

    def verify_setup_invoked(self):
        self.assertTrue(self.__setup_invoked,
                        msg='Inherited setUp method was not invoked by class derived from ScalyrTestCase')

if sys.version_info[:2] < (2, 7):
    class ScalyrTestCase(BaseScalyrTestCase):
        """The base class for Scalyr tests.

        This is used mainly to hide differences between the test fixtures available in the various Python
        versions.

        WARNING:  Derived classes that override setUp, must be sure to invoke the inherited setUp method.
        """
        # noinspection PyPep8Naming
        def __init__(self, methodName='runTest'):
            # Do not verify the setup was invoked since it relies on addCleanup which is only available in 2.7
            BaseScalyrTestCase.__init__(self, methodName=methodName, verify_setup_invoked=False)

        def assertIs(self, obj1, obj2, msg=None):
            """Just like self.assertTrue(a is b), but with a nicer default message."""
            if obj1 is not obj2:
                if msg is None:
                    msg = '%s is not %s' % (obj1, obj2)
                self.fail(msg)

        def assertIsNone(self, obj, msg=None):
            """Same as self.assertTrue(obj is None), with a nicer default message."""
            if msg is not None:
                self.assertTrue(obj is None, msg)
            else:
                self.assertTrue(obj is None, '%s is not None' % (str(obj)))

        def assertIsNotNone(self, obj, msg=None):
            """Included for symmetry with assertIsNone."""
            if msg is not None:
                self.assertTrue(obj is not None, msg)
            else:
                self.assertTrue(obj is not None, '%s is None' % (str(obj)))

        def assertGreater(self, a, b, msg=None):
            if msg is not None:
                self.assertTrue(a > b, msg)
            else:
                self.assertTrue(a > b, '%s is greater than %s' % (str(a), str(b)))

        def assertLess(self, a, b, msg=None):
            if msg is not None:
                self.assertTrue(a < b, msg)
            else:
                self.assertTrue(a < b, '%s is greater than %s' % (str(a), str(b)))

else:
    class ScalyrTestCase(BaseScalyrTestCase):
        """The base class for Scalyr tests.

        This is used mainly to hide differences between the test fixtures available in the various Python
        versions.

        WARNING:  Derived classes that override setUp, must be sure to invoke the inherited setUp method.
        """
        # noinspection PyPep8Naming
        def __init__(self, methodName='runTest'):
            BaseScalyrTestCase.__init__(self, methodName=methodName, verify_setup_invoked=True)

        def assertIs(self, obj1, obj2, msg=None):
            unittest.TestCase.assertIs(self, obj1, obj2, msg=msg)

        def assertIsNone(self, obj, msg=None):
            unittest.TestCase.assertIsNone(self, obj, msg=msg)

        def assertIsNotNone(self, obj, msg=None):
            unittest.TestCase.assertIsNotNone(self, obj, msg=msg)

        def assertGreater(self, a, b, msg=None):
            unittest.TestCase.assertGreater(self, a, b, msg=msg)

        def assertLess(self, a, b, msg=None):
            unittest.TestCase.assertLess(self, a, b, msg=msg)