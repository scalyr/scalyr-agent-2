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
    "scalyr_agent.tests.url_monitor_test",
]

# A list of Python module FQDNs or file paths relative to this directory (repo
# root to be ignored under Python < 2.7
PRE_PYTHON27_WHITELIST = [
    "scalyr_agent.tests.configuration_docker_test",
    "scalyr_agent.tests.configuration_k8s_test",
    "scalyr_agent.builtin_monitors.tests.docker_monitor_test",
    "scalyr_agent.builtin_monitors.tests.kubernetes_monitor_test",
    "scalyr_agent.monitor_utils.tests.k8s_test",
    "scalyr_agent.tests.syslog_request_parser_test",
    "scalyr_agent.tests.syslog_monitor_test",
    "scalyr_agent.tests.redis_monitor_test",
]

collect_ignore_glob = []
collect_ignore_glob.extend(GLOBAL_WHITELIST)

collect_ignore = ["setup.py"]


def get_module_path_for_fqdn(module_fqdn):
    # type: (str) -> str
    """
    Return path to the module based on the module fqdn.
    """
    module_path = module_fqdn.replace(".", os.path.sep) + ".py"
    module_path = os.path.abspath(module_path)
    return module_path


# Skip unloadable modules under different versions
for module_fqdn in PRE_PYTHON27_WHITELIST:
    try:
        mod = importlib.import_module(module_fqdn)
    except (ImportError, AttributeError) as e:
        if sys.version_info[:2] < (2, 7) or True:
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
    except (ImportError, AttributeError) as e:
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
