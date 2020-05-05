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

from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import print_function

__author__ = "czerwin@scalyr.com"

import unittest
import os
import sys
import traceback

# NOTE: We ensure repo root is in PYTHONPATH so we can import conftest module
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT_PATH = os.path.abspath(os.path.join(BASE_DIR, "../"))
sys.path.insert(0, REPO_ROOT_PATH)
from conftest import collect_ignore
from conftest import get_module_fqdn_for_path


UNIT_TESTS_DIRECTORY = os.path.abspath(os.path.join(BASE_DIR, "../tests/unit"))


def find_all_tests(directory=None, base_path=None):
    """Returns a list of of test module names from the directory where this script is located.

    @param directory: The directory to search (defaults to the directory containing this script.)
    @param base_path: The root directory for the module names (defaults to the directory containing script).

    @return: List of module names with periods between package names and without the trailing '.py' suffix,
        such as 'tests.unit.exceptions_test'.
    """
    if directory is None:
        directory = os.path.dirname(os.path.abspath(__file__))
        base_path = directory
    result = []

    for path in os.listdir(directory):
        full_path = os.path.join(directory, path)
        if os.path.isdir(full_path):
            result.extend(find_all_tests(directory=full_path, base_path=base_path))
        elif full_path.endswith("_test.py"):
            # We need to strip off the leading directory and replace the
            # directory separators with periods.
            x = full_path[len(base_path) + 1 : len(full_path) - 3]
            result.append("tests.unit." + x.replace(os.sep, "."))

    return result


def run_all_tests():
    """Runs all the tests containing this this directory and its children (where tests are
    contained in files ending in '_test.py'.
    """
    print("Current python version: %s" % sys.version)

    test_loader = unittest.defaultTestLoader
    suites = []
    error = False

    test_modules = find_all_tests(UNIT_TESTS_DIRECTORY, UNIT_TESTS_DIRECTORY)
    # Remove all modules which are to be ignored
    ignored_test_modules = [
        get_module_fqdn_for_path(module_path) for module_path in collect_ignore
    ]
    test_modules = list(set(test_modules) - set(ignored_test_modules))

    for test_case in test_modules:
        try:
            suites.append(test_loader.loadTestsFromName(test_case))
        except Exception as e:
            error = True
            print(
                "Error loading test_case '%s'.  %s, %s"
                % (test_case, str(e), traceback.format_exc())
            )

    test_suite = unittest.TestSuite(suites)
    if sys.version_info[:2] < (2, 7):
        # 2.6 and below to do not support capturing test output
        text_runner = unittest.TextTestRunner().run(test_suite)
    else:
        text_runner = unittest.TextTestRunner(buffer=True).run(test_suite)
    if not text_runner.wasSuccessful():
        error = True
    sys.exit(error)


if __name__ == "__main__":
    run_all_tests()
