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

from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import print_function

if False:  # NOSONAR
    from typing import Optional

from io import open

__author__ = "czerwin@scalyr.com"

import os
import sys
import re
import shutil
import threading
import time
import tempfile
import unittest
import random

from pprint import pprint

import scalyr_agent.scalyr_logging as scalyr_logging

import six

from scalyr_agent.util import StoppableThread
from scalyr_agent import util as scalyr_util

PYTHON_26_OR_OLDER = sys.version_info[:2] < (2, 7)

# Need so we can patch print() function for test purposes under both, Python 2 and 3
print = print

LOG = scalyr_logging.getLogger(__name__)


def _noop_skip(reason):
    def decorator(test_func_or_obj):
        if not isinstance(test_func_or_obj, type) or sys.version_info < (2, 7, 0):

            def test_skip_wrapper(*args, **kwargs):
                print(
                    'Skipping test %s. Reason: "%s"'
                    % (test_func_or_obj.__name__, reason)
                )

            return test_skip_wrapper
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
if hasattr(unittest, "skip"):
    skip = unittest.skip


skipUnless = _noop_skip_unless
if hasattr(unittest, "skipUnless"):
    skipUnless = unittest.skipUnless


skipIf = _noop_skip_if
if hasattr(unittest, "skipIf"):
    skipIf = unittest.skipIf

# Global state as to whether or not we've started the thread watcher.  We only want one instance of this
# started per entire test suite run.
__thread_watcher_started = False


def _thread_watcher():
    """Used to detect what threads are still alive after the tests should be finished running.  In particular, this
    helps detect cases where the tests have run successfully but some thread spawned by a test case did not
    properly stop.  Since it is not a daemon thread, it will block the exit of the entire process.

    """
    # Sleep for 45 seconds since our test suites typically run in less than 15 seconds.
    time.sleep(45)

    # If we are still alive after 60 seconds, it means some test is hung or didn't join
    # its threads properly.  Let's get some information on them.
    print("Detected hung test run.  Active threads are:")
    for t in threading.enumerate():
        if t.getName() in ["MainThread", "hung thread watcher"]:
            # Exclude itself and main thread
            continue

        print("Active thread %s daemon=%s" % (t.getName(), six.text_type(t.isDaemon())))
        pprint(t.__dict__)
    print("Done")
    # NOTE: We exit with non-zero here to fail early in Circle CI instead of waiting on build
    # timeout (10 minutes)
    sys.exit(1)


def _start_thread_watcher_if_necessary():
    """Starts the thread watcher if it hasn't already been started.
    """
    global __thread_watcher_started

    if not __thread_watcher_started:
        thread = threading.Thread(name="hung thread watcher", target=_thread_watcher)
        thread.setDaemon(True)
        thread.start()
        __thread_watcher_started = True


class BaseScalyrTestCase(unittest.TestCase):
    """Used to define ScalyrTestCase below.

    This augments the standard TestCase by capturing all logged lines to stdout and
    adds protection to help detect hung test threads.
    """

    # noinspection PyPep8Naming
    def __init__(self, methodName="runTest", verify_setup_invoked=False):
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

        # Enable keys sort for json.dumps to make it easier to assert on the serialized output
        scalyr_util.SORT_KEYS = True

        # NOTE: orjson doesn't support sort_keys so we fallback to implementation which supports it
        scalyr_util.set_json_lib("json")

    def tearDown(self):
        scalyr_util.SORT_KEYS = False

        # It's important we close all the open FDs used by loggers otherwise tests will fail on
        # Windows because the file will still be opened
        scalyr_logging.close_handlers()

    def run(self, result=None):
        _start_thread_watcher_if_necessary()
        StoppableThread.set_name_prefix("TestCase %s: " % six.text_type(self))
        return unittest.TestCase.run(self, result=result)

    def verify_setup_invoked(self):
        self.assertTrue(
            self.__setup_invoked,
            msg="Inherited setUp method was not invoked by class derived from ScalyrTestCase",
        )


if sys.version_info[:2] < (2, 7):

    class ScalyrTestCase(BaseScalyrTestCase):
        """The base class for Scalyr tests.

        This is used mainly to hide differences between the test fixtures available in the various Python
        versions.

        WARNING:  Derived classes that override setUp, must be sure to invoke the inherited setUp method.
        """

        # noinspection PyPep8Naming
        def __init__(self, methodName="runTest"):
            # Do not verify the setup was invoked since it relies on addCleanup which is only available in 2.7
            BaseScalyrTestCase.__init__(
                self, methodName=methodName, verify_setup_invoked=False
            )

        def assertIs(self, obj1, obj2, msg=None):
            """Just like self.assertTrue(a is b), but with a nicer default message."""
            if obj1 is not obj2:
                if msg is None:
                    msg = "%s is not %s" % (obj1, obj2)
                self.fail(msg)

        def assertIsNone(self, obj, msg=None):
            """Same as self.assertTrue(obj is None), with a nicer default message."""
            if msg is not None:
                self.assertTrue(obj is None, msg)
            else:
                self.assertTrue(obj is None, "%s is not None" % (six.text_type(obj)))

        def assertIsNotNone(self, obj, msg=None):
            """Included for symmetry with assertIsNone."""
            if msg is not None:
                self.assertTrue(obj is not None, msg)
            else:
                self.assertTrue(obj is not None, "%s is None" % (six.text_type(obj)))

        def assertGreater(self, a, b, msg=None):
            if msg is not None:
                self.assertTrue(a > b, msg)
            else:
                self.assertTrue(
                    a > b,
                    "%s is greater than %s" % (six.text_type(a), six.text_type(b)),
                )

        def assertLess(self, a, b, msg=None):
            if msg is not None:
                self.assertTrue(a < b, msg)
            else:
                self.assertTrue(
                    a < b,
                    "%s is greater than %s" % (six.text_type(a), six.text_type(b)),
                )

        def assertRaisesRegexp(self, exc_cls, expected_msg, func, **kwargs):
            """
            Compatibility layer for assertRaisesRegexp which also works under Python 2.6.
            """
            try:
                func(**kwargs)
            except Exception as e:
                if not isinstance(e, exc_cls):
                    raise AssertionError(
                        'Expected class "%s", got "%s"'
                        % (exc_cls.__name__, e.__class__.__name__)
                    )

                if not re.match(expected_msg, str(e)):
                    raise AssertionError(
                        'Expected "%s" message, got "%s"' % (expected_msg, str(e))
                    )


else:

    class ScalyrTestCase(BaseScalyrTestCase):
        """The base class for Scalyr tests.

        This is used mainly to hide differences between the test fixtures available in the various Python
        versions.

        WARNING:  Derived classes that override setUp, must be sure to invoke the inherited setUp method.
        """

        # noinspection PyPep8Naming
        def __init__(self, methodName="runTest"):
            BaseScalyrTestCase.__init__(
                self, methodName=methodName, verify_setup_invoked=True
            )

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


class BaseScalyrLogCaptureTestCase(ScalyrTestCase):
    """
    Base test class which captures log data produced by code called inside the tests into the log
    files created in "directory_path" directory as defined by that class variable.

    Directory available via "directory_path" variable is automatically created in a secure random
    fashion for each test invocation inside setUp() method.

    In addition to creating this directory, this method also sets up agent logging so it logs to
    files in that directory.

    On tearDown() the log directory is removed if tests pass and assertion hasn't failed, but if the
    assertion fails, directory is left in place so developer can inspect the log content which might
    aid with test troubleshooting.
    """

    # Path to the directory with the agent logs
    logs_directory = None  # type: Optional[str]

    # Path to the main agent log file
    agent_log_path = None  # type: Optional[str]

    # Path to the agent debug log file (populated inside setUp()
    agent_debug_log_path = None  # type: Optional[str]

    # Variable which indicates if assertLogFileContainsLine assertion was used and it fails
    # NOTE: Due to us needing to support multiple Python versions and test runners, there is no easy
    # and simple test runner agnostic way of detecting if tests have failed
    __assertion_failed = False  # type: bool

    def setUp(self):
        super(BaseScalyrLogCaptureTestCase, self).setUp()

        self.logs_directory = tempfile.mkdtemp(suffix="agent-tests-log")

        scalyr_logging.set_log_destination(
            use_disk=True,
            logs_directory=self.logs_directory,
            agent_log_file_path="agent.log",
            agent_debug_log_file_suffix="_debug",
        )
        scalyr_logging.__log_manager__.set_log_level(scalyr_logging.DEBUG_LEVEL_5)

        self.agent_log_path = os.path.join(self.logs_directory, "agent.log")
        self.agent_debug_log_path = os.path.join(self.logs_directory, "agent_debug.log")

    def tearDown(self):
        super(BaseScalyrLogCaptureTestCase, self).tearDown()

        # It's important we close all the open FDs used by loggers otherwise tests will fail on
        # Windows because the file will still be opened
        scalyr_logging.close_handlers()

        if self.__assertion_failed:
            # Print the paths to which we store the output to so they can be introspected by the
            # developer
            test_name = self._testMethodName
            print(
                'Stored agent log file for test "%s" to: %s'
                % (test_name, self.agent_log_path)
            )
            print(
                'Stored agent debug log file for test "%s" to: %s'
                % (test_name, self.agent_debug_log_path)
            )

        if not self.__assertion_failed:
            shutil.rmtree(self.logs_directory)

    def assertLogFileContainsLineRegex(self, expression, file_path=None):
        """
        Custom assertion function which asserts that the provided log file path contains a line
        which matches the provided line regular expression.

        Keep in mind that this function is line oriented. If you want to perform assertion across
        multiple lines, you should use "assertLogFileContainsRegex".

        :param expression: Regular expression to match against each line in the file.
        :param file_path: Path to the file to use. If not specified, it defaults to agent log file.
        """
        file_path = file_path or self.agent_log_path

        if not self._file_contains_line_regex(
            file_path=file_path, expression=expression
        ):
            with open(file_path, "r") as fp:
                content = fp.read()

            self.__assertion_failed = True
            self.fail(
                'File "%s" doesn\'t contain "%s" line expression.\n\nActual file content: %s'
                % (file_path, expression, content)
            )

    def assertLogFileDoesntContainsLineRegex(self, expression, file_path=None):
        """
        Custom assertion function which asserts that the provided log file path doesn\'t contains a
        line which matches the provided line regular expression.

        Keep in mind that this function is line oriented. If you want to perform assertion across
        multiple lines, you should use "assertLogFileDoesntContainsRegex".

        :param expression: Regular expression to match against each line in the file.
        :param file_path: Path to the file to use. If not specified, it defaults to agent log file.
        """
        file_path = file_path or self.agent_log_path

        if self._file_contains_line_regex(file_path=file_path, expression=expression):
            with open(file_path, "r") as fp:
                content = fp.read()

            self.__assertion_failed = True
            self.fail(
                'File "%s" contain "%s" line expression, but it shouldn\'t.\n\nActual file content: %s'
                % (file_path, expression, content)
            )

    def assertLogFileContainsRegex(self, expression, file_path=None):
        """
        Custom assertion function which asserts that the provided log file path contains a string
        which matches the provided regular expression.

        This function performs checks against the whole file content which means it comes handy in
        scenarios where you need to perform cross line checks.

        :param expression: Regular expression to match against the whole file content.
        :param file_path: Path to the file to use. If not specified, it defaults to agent log file.
        """
        file_path = file_path or self.agent_log_path

        if not self._file_contains_regex(file_path=file_path, expression=expression):
            with open(file_path, "r") as fp:
                content = fp.read()

            self.__assertion_failed = True
            self.fail(
                'File "%s" doesn\'t contain "%s" expression.\n\nActual file content: %s'
                % (file_path, expression, content)
            )

    def assertLogFileDoesntContainsRegex(self, expression, file_path=None):
        """
        Custom assertion function which asserts that the provided log file path doesn\'t contain a
        string which matches the provided regular expression.

        This function performs checks against the whole file content which means it comes handy in
        scenarios where you need to perform cross line checks.

        :param file_path: Path to the file to use.
        :param file_path: Path to the file to use. If not specified, it defaults to agent log file.
        """
        file_path = file_path or self.agent_log_path

        if self._file_contains_regex(file_path=file_path, expression=expression):
            with open(file_path, "r") as fp:
                content = fp.read()

            self.__assertion_failed = True
            self.fail(
                'File "%s" contain "%s" expression, but it shouldn\'t.\n\nActual file content: %s'
                % (file_path, expression, content)
            )

    def _file_contains_line_regex(self, file_path, expression):
        matcher = re.compile(expression)

        with open(file_path, "r") as fp:
            for line in fp:
                if matcher.search(line):
                    return True

        return False

    def _file_contains_regex(self, file_path, expression):
        matcher = re.compile(expression)

        with open(file_path, "r") as fp:
            content = fp.read()

        return bool(matcher.search(content))


class ScalyrMockHttpServerTestCase(ScalyrTestCase):
    """
    Base Scalyr test case class which starts mock http server on startUpClass() and stops it on
    tearDownClass()
    """

    mock_http_server_thread = None

    @classmethod
    def setUpClass(cls):
        cls.mock_http_server_thread = MockHTTPServer()
        cls.mock_http_server_thread.start()

        # Give server some time to start up
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        if cls.mock_http_server_thread:
            cls.mock_http_server_thread.stop()


def shutdown_flask_server():
    from flask import request

    func = request.environ["werkzeug.server.shutdown"]
    func()
    return ""


class MockHTTPServer(StoppableThread):
    """
    Mock HTTP server which can be used for tests.

    It works by starting a mock HTTP server which serves a flask app on localhost and random port.
    """

    def __init__(self, host="127.0.0.1", port=None):
        # type: (str, Optional[int]) -> None
        if not port:
            port = random.randint(5000, 20000)

        super(MockHTTPServer, self).__init__(name="MockHttpServer_%s_%s" % (host, port))

        from flask import Flask

        self.host = host
        self.port = port

        # Make sure we run in the background
        self.setDaemon(True)

        self.app = Flask("mock_app")
        self.app.add_url_rule("/shutdown", view_func=shutdown_flask_server)

    def run(self):
        LOG.info(
            "Starting mock http server and listening on: %s:%s" % (self.host, self.port)
        )

        self.app.run(host=self.host, port=self.port)
        super(MockHTTPServer, self).run()

    def stop(self, wait_on_join=True, join_timeout=2):
        import requests

        LOG.info("Stopping mock http server...")

        # Sadly there is no better way to kill werkzeug server...
        url = "http://%s:%s/shutdown" % (self.host, self.port)
        requests.get(url)

        self.app.do_teardown_appcontext()
        super(MockHTTPServer, self).stop(wait_on_join=True, join_timeout=0.1)
