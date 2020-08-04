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
pylint checker plugin used to enforce invariants necessary for `PyInstaller` to work
correctly (`PyInstaller` is the tool used to generate the Windows binaries).  These
invariants are difficult to enforce in other, more traditional ways.  See below for
more specifics about the checker and the invariants it enforces.
"""

from __future__ import absolute_import
from __future__ import print_function


if False:  # NOSONAR
    from typing import Any

from astroid import node_classes, scoped_nodes
from pylint.checkers import BaseChecker
from pylint.interfaces import IAstroidChecker


from win32.dynamic_modules import WINDOWS_MONITOR_MODULES_TO_INCLUDE


class PyInstallerChecker(BaseChecker):
    """Enforces invariants for PyInstaller to work:

    1. Any monitor that should be included in the Windows binary is listed in the `WINDOWS_MONITOR_MODULES_TO_INCLUDE`
      set.  This is important because monitors are loaded dynamically at runtime and are, therefore, not included
      by default by `PyInstaller` through its static dependency analysis.  This would result in the monitors not being
      available in the Windows binary.
      Instead, we use this list to give `PyInstaller` a manual list of modules to include.
    """

    __implements__ = IAstroidChecker

    name = "scalyr-windows-monitors-import-checker"

    MONITOR_NOT_INCLUDED_FOR_WIN32 = "monitor-not-included-for-win32"

    msgs = {
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
        super(PyInstallerChecker, self).__init__(linter)
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
        pass

    def visit_importfrom(self, node):
        # type: (node_classes.ImportFrom) -> None
        # Invoked when visiting a line like `from module import x,y,z`.  The module name is in
        # node.modname and the actual imports are in a list in node.names.
        pass

    def visit_classdef(self, node):
        # type: (node_classes.ClassDef) -> None
        class_name = node.name
        if (
            "ScalyrMonitor" in node.basenames
            and self.__current_module not in WINDOWS_MONITOR_MODULES_TO_INCLUDE
        ):
            args = (class_name, self.__current_module)
            self.add_message(self.MONITOR_NOT_INCLUDED_FOR_WIN32, node=node, args=args)


def register(linter):
    # type: (Any) -> None
    linter.register_checker(PyInstallerChecker(linter))
