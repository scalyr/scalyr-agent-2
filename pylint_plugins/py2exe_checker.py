# Copyright 2020 Scalyr Inc.
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
pylint checker plugin used to enforce invariants necessary for `py2exe` to work
correctly (`py2exe` is the tool used to generate the Windows binaries).  These
invariants are difficult to enforce in other, more traditional ways.  See below for
more specifics about the checker and the invariants it enforces.
"""

from __future__ import absolute_import

if False:  # NOSONAR
    from typing import Any
    from typing import Union

from astroid import node_classes, scoped_nodes
from pylint.checkers import BaseChecker
from pylint.interfaces import IAstroidChecker

from setup import WINDOWS_MONITOR_MODULES_TO_INCLUDE, WINDOWS_PY2_SIX_MOVES_IMPORTS


class Py2ExeChecker(BaseChecker):
    """Enforces two key invariants for py2exe to work:

    1. Any module imported using `six.moves` is listed in the `WINDOWS_PY2_SIX_MOVES_IMPORTS` dict.
      This is important because `py2exe` cannot correctly infer dependencies from modules imported in this
      manner.  This would result in the necessary modules not being included in the Windows binary and thus causing
      it to fail when run.  Instead, we use the `WINDOWS_PY2_SIX_MOVES_IMPORTS` dict to give `py2exe` a manual list
      of modules to include.

    2. Any monitor that should be included in the Windows binary is listed in the `WINDOWS_MONITOR_MODULES_TO_INCLUDE`
      set.  This is important because monitors are loaded dynamically at runtime and are, therefore, not included
      by default by `py2exe` through its static dependency analysis.  This would result in the monitors not being
      available in the Windows binary.  Instead, we use this list to give `py3exe` a manual list of modules to include.
    """

    __implements__ = IAstroidChecker

    name = "scalyr-py2exe-checker"

    SIX_MOVES_IMPORT_NOT_INCLUDED_FOR_WIN32 = "six-moves-import-not-included-for-win32"
    MONITOR_NOT_INCLUDED_FOR_WIN32 = "monitor-not-included-for-win32"

    msgs = {
        "E8101": (
            'Found six.moves import "%s" on line %d, but module is not included for py2exe.  Windows binary '
            "will not properly include all dependencies for the module.  Please edit WINDOWS_PY2_SIX_MOVES_IMPORTS to "
            "add the module and dependencies.",
            SIX_MOVES_IMPORT_NOT_INCLUDED_FOR_WIN32,
            "",
        ),
        "E8102": (
            'Found definition for monitor "%s" in module "%s", but that module is not listed in '
            "WINDOWS_MONITOR_MODULES_TO_INCLUDE.  This monitor will not be included in the Windows binary.  Add the "
            "monitor's module to the list in platform_windows.py to fix.",
            MONITOR_NOT_INCLUDED_FOR_WIN32,
            "",
        ),
    }

    options = ()
    priority = -1

    def __init__(self, linter):
        # type: (Any) -> None
        super(Py2ExeChecker, self).__init__(linter)
        # Keeps track of the current module being visited.
        self.__current_module = None

    def visit_module(self, node):
        # type: (scoped_nodes.Module) -> None
        self.__current_module = node.name

    def leave_module(self, _node):
        # type: (scoped_nodes.Module) -> None
        self.__current_module = None

    def visit_import(self, node):
        # type: (node_classes.Import) -> None
        # Invoked when visiting a line like `import x,y,z`.  The modules are in a list in `node.names`.
        if self.__is_scalyr_agent_module:
            for import_fragment in node.names:
                self.__verify_six_import_in_whitelist(import_fragment[0], node)

    def visit_importfrom(self, node):
        # type: (node_classes.ImportFrom) -> None
        # Invoked when visiting a line like `from module import x,y,z`.  The module name is in
        # node.modname and the actual imports are in a list in node.names.
        if self.__is_scalyr_agent_module:
            module_name = node.modname
            for import_fragment in node.names:
                self.__verify_six_import_in_whitelist(
                    "%s.%s" % (module_name, import_fragment[0]), node
                )

    def visit_classdef(self, node):
        # type: (node_classes.ClassDef) -> None
        class_name = node.name
        if (
            "ScalyrMonitor" in node.basenames
            and self.__current_module not in WINDOWS_MONITOR_MODULES_TO_INCLUDE
        ):
            args = (class_name, self.__current_module)
            self.add_message(self.MONITOR_NOT_INCLUDED_FOR_WIN32, node=node, args=args)

    @property
    def __is_scalyr_agent_module(self):
        # type: () -> bool
        return self.__current_module is not None and self.__current_module.startswith(
            "scalyr_agent"
        )

    def __verify_six_import_in_whitelist(self, import_name, import_node):
        # type: (str, Union[node_classes.Import,node_classes.ImportFrom]) -> None
        """
        Verify any imports from `six.moves` are in the known dict list.
        """
        if (
            import_name.startswith("six.moves")
            and import_name not in WINDOWS_PY2_SIX_MOVES_IMPORTS
        ):
            args = (import_name, import_node.lineno)
            self.add_message(
                self.SIX_MOVES_IMPORT_NOT_INCLUDED_FOR_WIN32,
                node=import_node,
                args=args,
            )


def register(linter):
    # type: (Any) -> None
    linter.register_checker(Py2ExeChecker(linter))
