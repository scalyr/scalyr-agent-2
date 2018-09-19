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
# Runs all tests in modules in this directory and all of its children that end in '_test.py'
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import unittest
import os
import sys
import traceback


def find_all_tests(directory=None, base_path=None):
    """Returns a list of of test module names from the directory where this script is located.

    @param directory: The directory to search (defaults to the directory containing this script.)
    @param base_path: The root directory for the module names (defaults to the directory containing script).

    @return: List of module names with periods between package names and without the trailing '.py' suffix,
        such as 'scalyr_agent.tests.exceptions_test'.
    """
    if directory is None:
        directory = os.path.dirname(os.path.abspath(__file__))
        base_path = directory
    result = []

    for path in os.listdir(directory):
        full_path = os.path.join(directory, path)
        if os.path.isdir(full_path):
            result.extend(find_all_tests(directory=full_path, base_path=base_path))
        elif full_path.endswith('_test.py'):
            # We need to strip off the leading directory and replace the
            # directory separators with periods.
            x = full_path[len(base_path)+1:len(full_path) - 3]
            result.append('scalyr_agent.' + x.replace(os.sep, '.'))

    return result


def run_all_tests():
    """Runs all the tests containing this this directory and its children (where tests are
    contained in files ending in '_test.py'.
    """
    test_loader = unittest.defaultTestLoader
    suites = []
    error = False
    for test_case in find_all_tests():
        try:
            suites.append(test_loader.loadTestsFromName(test_case))
        except Exception, e:
            error = True
            print( "Error loading test_case '%s'.  %s, %s" % (test_case, str(e), traceback.format_exc()) )

    test_suite = unittest.TestSuite(suites)
    text_runner = unittest.TextTestRunner().run(test_suite)
    if not text_runner.wasSuccessful():
        error = True
    sys.exit(error)

if __name__ == '__main__':
    run_all_tests()
