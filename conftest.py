#
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
#
# ------------------------------------------------------------------------
#
# Module which is used by py.test for customizing test collection and discovery
# Based on code from scalyr_agent/all_tests.py

from __future__ import absolute_import
from __future__ import print_function

import os
import sys
import importlib

__all__ = [
    "get_module_path_for_fqdn",
    "get_module_fqdn_for_path",
    "collect_ignore",
    "collect_ignore_glob",
]

# A list of directory globs which are ignored under all Python versions.
# Those paths represent bundled third party dependencies
GLOBAL_WHITELIST = [
    "scalyr_agent/third_party/*",
    "scalyr_agent/third_party_tls/*",
    "scalyr_agent/third_party_python2/*",
]

# A list of Python module FQDNs or file paths relative to this directory (repo
# root) to be ignored under Python 2.4
PYTHON24_WHITELIST = [
    "tests.unit.url_monitor_test",
]

# A list of Python module FQDNs or file paths relative to this directory (repo
# root to be ignored under Python < 2.7
PRE_PYTHON27_WHITELIST = [
    "tests.unit.configuration_docker_test",
    "tests.unit.configuration_k8s_test",
    "tests.unit.builtin_monitors.docker_monitor_test",
    "tests.unit.builtin_monitors.kubernetes_monitor_test",
    "tests.unit.monitor_utils.k8s_test",
    "tests.unit.syslog_request_parser_test",
    "tests.unit.syslog_monitor_test",
    "tests.unit.redis_monitor_test",
]

collect_ignore_glob = []
collect_ignore_glob.extend(GLOBAL_WHITELIST)

collect_ignore = ["setup.py"]

# NOTE: Older version of pytest (<= 3.2.5 )which is used under Python 2.6 doesn't support
# collect_ignore_glob directive
if sys.version_info[:2] == (2, 6):
    import fnmatch

    for directory in GLOBAL_WHITELIST:
        for root, dirnames, filenames in os.walk(directory.replace("/*", "/")):
            for filename in fnmatch.filter(filenames, "*.py"):
                file_path = os.path.join(root, filename)
                collect_ignore.append(file_path)


def get_module_path_for_fqdn(module_fqdn):
    # type: (str) -> str
    """
    Return path to the module based on the module fqdn.
    """
    module_path = module_fqdn.replace(".", os.path.sep) + ".py"
    module_path = os.path.abspath(module_path)
    return module_path


def get_module_fqdn_for_path(module_path):
    # type: (str) -> str
    """
    Return fully qualified module name for the provided absolute module path starting with
    scalyr_agent. package.
    """
    index = module_path.find("scalyr_agent")
    if index != -1:
        module_path = module_path[module_path.find("scalyr_agent") :]

    index = module_path.find("tests/unit")
    if index != -1:
        module_path = module_path[module_path.find("tests/unit") :]

    module_fqdn = module_path.replace(os.path.sep, ".").replace(".py", "")

    return module_fqdn


# Skip unloadable modules under different versions
for module_fqdn in PRE_PYTHON27_WHITELIST:
    try:
        mod = importlib.import_module(module_fqdn)
    except (ImportError, AttributeError, SyntaxError) as e:
        if sys.version_info[:2] < (2, 7):
            print(
                (
                    "Warning. Skipping unloadable module '%s'.\n"
                    "This module was whitelisted as non-critical for pre-2.7 testing.\n"
                    "Module-load exception message: '%s'\n" % (module_fqdn, e)
                )
            )
            module_path = get_module_path_for_fqdn(module_fqdn)
            collect_ignore.append(module_path)

for module_fqdn in PYTHON24_WHITELIST:
    try:
        mod = importlib.import_module(module_fqdn)
    except (ImportError, AttributeError, SyntaxError) as e:
        if sys.version_info[:2] < (2, 5):
            print(
                (
                    "Warning. Skipping unloadable module '%s'.\n"
                    "This module was whitelisted as non-critical for Python 2.4 testing.\n"
                    "Module-load exception message: '%s'\n" % (module_fqdn, e)
                )
            )
            module_path = get_module_path_for_fqdn(module_fqdn)
            collect_ignore.append(module_path)
