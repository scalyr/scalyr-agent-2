# Copyright 2019 Scalyr Inc.
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
pylint checker plugin which verifies that any import for a 3rd party bundled module (modules in
scalyr_agent/third_party* directory) comes after "scalyr_init()" function call.

This is important, because if module is imported before "scalyr_init()" function call, it means it
may use system version of that module instead of the bundled version.

NOTE: Currently this plugin is limited to only checking main entry point files since it doesn't
implement cross module / file tracking (e.g. file A calls scalyr_init() and imports file B which
then imports some bundled module).
"""

from __future__ import absolute_import
from __future__ import print_function

if False:  # NOSONAR
    from typing import List
    from typing import Tuple
    from typing import Dict
    from typing import Set
    from typing import Any
    from typing import Optional

import os

from collections import defaultdict

from astroid import node_classes
from astroid import scoped_nodes
from pylint.checkers import BaseChecker
from pylint.interfaces import IAstroidChecker

BASE_DIR = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.abspath(os.path.join(BASE_DIR, "../"))

THIRD_PARTY_DIRECTORIES = [
    os.path.join(BASE_DIR, "scalyr_agent/third_party"),
    os.path.join(BASE_DIR, "scalyr_agent/third_party_tls"),
    os.path.join(BASE_DIR, "scalyr_agent/third_party_python2"),
]


class ThirdPartyBundledImportOrderChecker(BaseChecker):
    __implements__ = IAstroidChecker

    name = "scalyr-bundled-imports-checker"

    SCALYR_INIT_CALL_NOT_FOUND = "scalyr-init-call-not-found"
    INVALID_BUNDLED_IMPORT_ORDER = "bundled-import-after-scalyr-init"

    msgs = {
        "E8001": (
            'Found import "%s" on line %d, but no scalyr_init() line found.',
            SCALYR_INIT_CALL_NOT_FOUND,
            "",
        ),
        "E8002": (
            'Import "%s" is on line %s, but it should come after scalyr_init() function call which is on line %s.',
            INVALID_BUNDLED_IMPORT_ORDER,
            "",
        ),
    }

    options = ()
    priority = -1

    def __init__(self, linter):
        # type: (Any) -> None
        super(ThirdPartyBundledImportOrderChecker, self).__init__(linter)

        self._third_party_module_names = get_third_party_package_module_names()

        # Stores reference to the node where scalyr_init() function is called
        # Maps file_path -> node
        self._scalyr_init_nodes = {}  # type: Dict[str, node_classes.Call]

        # Stores references to imoort nodes which refer to 3rd party modules
        # Maps file_path -> nodes
        self._third_party_import_nodes = defaultdict(
            set
        )  # type: Dict[str, Set[node_classes.Import]]

    def visit_call(self, node):
        # type: (node_classes.Call) -> None
        if getattr(node.func, "name", None) == "scalyr_init":
            # TODO: Handle case where there are multiple scalyr_init calls - just store reference
            # to the earliest one (aka one with lowest line number)
            node_file_path = self._get_file_path_for_node(node=node)
            node.file_path = node_file_path
            self._scalyr_init_nodes[node_file_path] = node

    def visit_import(self, node):
        # type: (node_classes.Import) -> None
        module_name = node.names[0][0]
        if module_name in self._third_party_module_names:
            node.name = module_name
            node_file_path = self._get_file_path_for_node(node=node)
            self._third_party_import_nodes[node_file_path].add(node)

    def visit_importfrom(self, node):
        # type: (node_classes.Import) -> None
        module_name = node.modname
        if module_name in self._third_party_module_names:
            node.name = module_name
            node_file_path = self._get_file_path_for_node(node=node)
            self._third_party_import_nodes[node_file_path].add(node)

    def leave_module(self, node):
        # type: (scoped_nodes.Module) -> None
        """
        We perform the actual check just before we leave the module since that's when the file has
        been fully processed.
        """
        node_file_path = self._get_file_path_for_node(node=node)

        third_party_nodes = list(
            self._third_party_import_nodes.get(node_file_path, [])
        )  # type: List[node_classes.Import]
        scalyr_init_node = self._scalyr_init_nodes.get(node_file_path, None)

        for import_node in third_party_nodes:
            self._verify_import_node_comes_after_scalyr_init(
                scalyr_init_node=scalyr_init_node, import_node=import_node
            )

    def _verify_import_node_comes_after_scalyr_init(
        self, scalyr_init_node, import_node
    ):
        """
        Verify any import which references a bundled third party module comes after scalyr_init()
        call.
        """
        if not scalyr_init_node:
            # TODO: Implement support for indirect imports. Currently we only check files which
            # contain "scalyr_init()" call aka main entry points.
            return
            args = (import_node.name, import_node.lineno)
            self.add_message(
                self.SCALYR_INIT_CALL_NOT_FOUND, node=import_node, args=args
            )

        if import_node.lineno < scalyr_init_node.lineno:
            args = (import_node.name, import_node.lineno, scalyr_init_node.lineno)
            self.add_message(
                self.INVALID_BUNDLED_IMPORT_ORDER, node=import_node, args=args
            )
            return

    def _get_file_path_for_node(self, node):
        # Recursievly walk up to the top most parent to find the file original node comes from
        if getattr(node, "file", None):
            return node.file
        elif node.parent:
            return self._get_file_path_for_node(node=node.parent)

        return None


def get_third_party_package_module_names():
    # type: () -> List[str]
    """
    Return a list of bundled 3rd party package and module names.
    """
    result = []  # type: List[str]

    def is_python_package(directory_path, file_path):
        # type: (str, str) -> Tuple[bool, Optional[str]]
        """
        Return package name if the provided file path is a Python package, None otherwise.
        """
        file_name = os.path.basename(file_path)
        init_file_path = os.path.join(file_path, "__init__.py")

        if os.path.isdir(file_path) and os.path.isfile(init_file_path):
            # Package
            return (True, file_name)

        return (False, None)

    def is_python_module(directory_path, file_path):
        # type: (str, str) -> Tuple[bool, Optional[str]]
        """
        Return module name if the provided file path is a Python module, None otherwise.
        """
        if (
            os.path.isfile(file_path)
            and file_path.endswith(".py")
            and file_name != "__init__.py"
        ):
            # Single file module (e.g. six.py)
            module_name = file_name.replace(".py", "")
            return (True, module_name)

        return (False, None)

    for directory_path in THIRD_PARTY_DIRECTORIES:
        file_names = os.listdir(directory_path)

        for file_name in file_names:
            file_path = os.path.join(directory_path, file_name)

            python_package, package_name = is_python_package(directory_path, file_path)
            python_module, module_name = is_python_module(directory_path, file_path)

            if python_package and package_name:
                result.append(package_name)
            elif python_module and module_name:
                result.append(module_name)

    return result


def register(linter):
    # type: (Any) -> None
    linter.register_checker(ThirdPartyBundledImportOrderChecker(linter))
