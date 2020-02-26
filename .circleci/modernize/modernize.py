#!/usr/bin/env python
#
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
# ------------------------------------------------------------------------
#
# Script used to check the code for python 2/3 compatibility using "python-modernize" tool
# usage python modernize.py
# IMPORTANT! Working directory must me scalyr agent project root.
# optional arguments:
#   -w --write:  if set, write suggested changes immediately.
#   -j --processes <jobs count> run concurrently.
# Note: This is only python3 script.

if False:
    # NOTE: This is a workaround for old Python versions where typing module is not available
    # We should eventually improve that once we start producing distributions with Python
    # interpreter and dependencies bundled in.
    # Adding conditional "typing" dependency would require too much boiler plate code at this point

    from typing import Dict
    from typing import Any

import re
import os
import io
import difflib
import collections
import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import glob

from libmodernize.main import refactor
from libmodernize.fixes import six_fix_names

MAX_TODO_LINES = 1000

FIXERS = {
    "lib2to3.fixes.fix_apply",
    "lib2to3.fixes.fix_except",
    "lib2to3.fixes.fix_exec",
    "lib2to3.fixes.fix_execfile",
    "lib2to3.fixes.fix_exitfunc",
    "lib2to3.fixes.fix_funcattrs",
    "lib2to3.fixes.fix_has_key",
    "lib2to3.fixes.fix_idioms",
    "lib2to3.fixes.fix_long",
    "lib2to3.fixes.fix_methodattrs",
    "lib2to3.fixes.fix_ne",
    "lib2to3.fixes.fix_numliterals",
    "lib2to3.fixes.fix_operator",
    "lib2to3.fixes.fix_paren",
    "lib2to3.fixes.fix_reduce",
    "lib2to3.fixes.fix_renames",
    "lib2to3.fixes.fix_repr",
    "lib2to3.fixes.fix_set_literal",
    "lib2to3.fixes.fix_standarderror",
    "lib2to3.fixes.fix_sys_exc",
    "lib2to3.fixes.fix_throw",
    "lib2to3.fixes.fix_tuple_params",
    "lib2to3.fixes.fix_types",
    "lib2to3.fixes.fix_ws_comma",
    "lib2to3.fixes.fix_xreadlines",
    "libmodernize.fixes.fix_basestring",
    "libmodernize.fixes.fix_dict_six",
    "libmodernize.fixes.fix_file",
    "libmodernize.fixes.fix_filter",
    "libmodernize.fixes.fix_import",
    "libmodernize.fixes.fix_imports_six",
    "libmodernize.fixes.fix_input_six",
    "libmodernize.fixes.fix_int_long_tuple",
    "libmodernize.fixes.fix_itertools_imports_six",
    "libmodernize.fixes.fix_itertools_six",
    "libmodernize.fixes.fix_map",
    "libmodernize.fixes.fix_metaclass",
    "libmodernize.fixes.fix_next",
    "libmodernize.fixes.fix_print",
    "libmodernize.fixes.fix_raise",
    "libmodernize.fixes.fix_raise_six",
    "libmodernize.fixes.fix_unichr",
    "libmodernize.fixes.fix_unicode_type",
    "libmodernize.fixes.fix_urllib_six",
    "libmodernize.fixes.fix_xrange_six",
    "libmodernize.fixes.fix_zip",
    "libmodernize.fixes.fix_open",
    "custom_fixers.fix_os_environ_unicode",
    "custom_fixers.fix_os_getenv_unicode",
    "custom_fixers.fix_struct_unicode",
}

# pattern to find start of the area [start of 2->TOD0]
TODO_END_PATTERN = re.compile(r"\s*#\s*\[\s*end of 2->TOD[O0]\s*\]")
# pattern to find end of the area [start of 2->TOD0]
TODO_START_PATTERN = re.compile(r"\s*#\s*\[\s*start of 2->TODO\s*[a-zA-Z._ ]*\s*\].*")


def get_diff(new_source, original_source, file_path):
    """
    Get diff from two strings.
    :param new_source:
    :param original_source:
    :param file_path:
    :return: string with diff
    :rtype str
    """
    diff = difflib.unified_diff(
        original_source.splitlines(),
        new_source.splitlines(),
        file_path,
        file_path,
        "(original)",
        "(refactored)",
        lineterm="",
    )

    diff_text = "\n".join(list(diff))

    return diff_text


class TODOParseError(Exception):
    pass


def parse_todo_areas(source):
    """
    Parse and return list of code chunks between [start of 2->TOD0] ... [end of 2->TOD0] areas.
    :param source: string with python source code
    :type source str
    :return:
    :rtype list
    """

    result = list()

    lines = source.splitlines(True)

    if not lines:
        return result

    line_index = 0
    while line_index < len(lines):
        line = lines[line_index]
        # new area
        if TODO_START_PATTERN.match(line):
            start_index = line_index
            todo_area_lines = list()
            line_index += 1
            while True:
                # no end of the erea
                if line_index >= len(lines):
                    raise TODOParseError(
                        "[start of 2->TOD0] without [end of 2->TOD0]. Line: {}".format(
                            start_index
                        )
                    )
                line = lines[line_index]
                # end of the area found
                if TODO_END_PATTERN.match(line):
                    todo_area_string = "".join(todo_area_lines)
                    if len(todo_area_string) > MAX_TODO_LINES:
                        raise TODOParseError(
                            "TODO area is bigger than 500 characters. Line: {}".format(
                                line_index
                            )
                        )

                    result.append(todo_area_string)
                    break
                # another start found, raise error.
                elif TODO_START_PATTERN.match(line):
                    raise TODOParseError(
                        "Another [start of 2->TOD0] inside of [start of 2->TOD0]. Line: {}".format(
                            line_index
                        )
                    )
                else:
                    todo_area_lines.append(line)

                line_index += 1
        # end found without start.
        elif TODO_END_PATTERN.match(line):
            raise TODOParseError(
                "[end of 2->TOD0] without [start of 2->TOD0]. Line: {}".format(
                    line_index
                )
            )
        line_index += 1

    return result


def modernize_source_string(original_source_string, disabled_fixers=None):
    """
    Applies modernize on string and returns string with modified source code. Leaves [ start of 2->TOD0] untouched.
    :param original_source_string:
    :param disabled_fixers: fixers which are not going to be used in this file processing.
    :type original_source_string: str
    :type disabled_fixers set
    :return:
    :rtype str
    """

    # parse and save [2->TOD0] areas.
    original_todos = parse_todo_areas(original_source_string)

    if disabled_fixers is None:
        disabled_fixers = set()

    # create allowed fixers set.
    fixers = FIXERS - set(disabled_fixers)
    # create refactoring tool from libmodernize.
    tool = refactor.RefactoringTool(sorted(fixers))
    # apply refactoring tool on source code.
    tree = tool.refactor_string(original_source_string, "<stdin>")
    # get string with modified source code.
    modernized_source_string = str(tree)

    # parse [2->TOD0] areas which are now modernized too.
    new_todos = parse_todo_areas(modernized_source_string)

    result_source_string = modernized_source_string

    # something went wrong with parsing
    if len(original_todos) != len(new_todos):
        raise RuntimeError("some of [2->TODO] areas was corrupted.")

    # replace modernized [2->TOD0] areas with original.
    for o, n in zip(original_todos, new_todos):
        result_source_string = result_source_string.replace(n, o, 1)

    return result_source_string


def process_file(file_path, write=False, executor=None, **modernize_params):
    """
    Checks source code in file by modernize library. If "write" is True, writes needed modifications.
    :param file_path:
    :param write: Writes all found modification.
    :param executor: ProcessPoolExecutor object to run this function in separate process.
    :param modernize_params: all additional arguments to "modernize_source_string"
    :type file_path str
    :type write bool
    :type executor None|ProcessPoolExecutor
    :return: string with diff of original and modernized source code. If executor specified, future is returned.
    :rtype str | concurrent.futures.Future
    """

    if executor is not None:
        # run same function in executor.
        return executor.submit(process_file, file_path, write=write, **modernize_params)

    with io.open(file_path, "r") as file:
        original_source_string = file.read()

    new_source_string = modernize_source_string(
        original_source_string, **modernize_params
    )

    # create diff from original source code and after modernize.
    diff = get_diff(new_source_string, original_source_string, file_path)

    # if there are changes and write option is set, than we write new string to file.
    if diff and write:
        with io.open(file_path, "w") as file:
            file.write(new_source_string)

    # return diff for console report.
    return diff


def _run_tests():
    orig_source = """
from foo import bar
# [start of 2->TODO]
a = long
b= unicode
d = dict()
for _ in d.items():
    pass
# [end of 2->TOD0]

print "Not to modernize"
"""
    expected_source = """
from __future__ import absolute_import
from __future__ import print_function
from foo import bar
import six
# [start of 2->TODO]
a = long
b= unicode
d = dict()
for _ in d.items():
    pass
# [end of 2->TOD0]

print("Not to modernize")
"""

    new_source = modernize_source_string(orig_source)
    assert new_source == expected_source, "Test failed."

    orig_source = """
from foo import bar
# [start of 2->TODO]
a = long
b= unicode
d = dict()
# [start of 2->TODO]
for _ in d.items():
    pass
# [end of 2->TOD0]

print "Not to modernize"
"""
    try:
        modernize_source_string(orig_source)
        assert False, "Modernize should fail on second [start of 2->TOD0]."
    except TODOParseError as e:
        assert (
            str(e) == "Another [start of 2->TOD0] inside of [start of 2->TOD0]. Line: 6"
        )

    orig_source = """
from foo import bar
# [end of 2->TOD0]
# [start of 2->TODO]
a = long
b= unicode
d = dict()
for _ in d.items():
    pass
# [end of 2->TOD0]

print "Not to modernize"
"""
    try:
        modernize_source_string(orig_source)
        assert (
            False
        ), "Modernize should fail because of [end of 2->TOD0] before [start of 2->TOD0]."
    except TODOParseError as e:
        assert str(e) == "[end of 2->TOD0] without [start of 2->TOD0]. Line: 2"

    orig_source = """
from foo import bar
# [start of 2->TODO]
a = long
b= unicode
d = dict()
for _ in d.items():
    pass

print "Not to modernize"
"""
    try:
        modernize_source_string(orig_source)
        assert (
            False
        ), "Modernize should fail because of the absence of [end of 2->TOD0]."
    except TODOParseError as e:
        assert str(e) == "[start of 2->TOD0] without [end of 2->TOD0]. Line: 2"


# simple test before main activity.
_run_tests()

if __name__ == "__main__":
    if sys.version_info[0] < 3:
        print("This script runs only on python3")
        exit(1)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        default=False,
        help="Write modified files.",
    )
    parser.add_argument(
        "files",
        metavar="FILES",
        type=str,
        nargs="*",
        help="File paths to run the script on. If not specified it runs on all the files.",
    )
    parser.add_argument(
        "-j", "--processes", default=1, type=int, help="Run modernize concurrently."
    )

    args = parser.parse_args()

    root = os.getcwd()
    source_root = os.path.join(root, "scalyr_agent")

    # all python files
    all_files = set(glob.glob("{}/**/*.py".format(root), recursive=True))

    venv_files = set(glob.glob("{}/venv/**/*".format(root), recursive=True))

    # do not modernize third_party libraries.
    third_party_files = set(
        glob.glob("{0}/third_party*/**/*.py".format(source_root), recursive=True),
    )

    # do not process modernize files.
    modernize_files = set(
        glob.glob("{0}/.circleci/modernize/**/*.py".format(root), recursive=True)
    )

    other_files_to_exclude = {
        os.path.join(source_root, "compat.py"),
        os.path.join(root, "build_package.py"),
        os.path.join(root, ".circleci/coverage_report.py"),
    }

    if not args.files:
        # files without third party libraries.
        files_to_process = set(all_files)
    else:
        files_to_process = set([os.path.abspath(file_path) for file_path in args.files])

    # files without third party libraries.
    files_to_process = (
        files_to_process
        - third_party_files
        - venv_files
        - modernize_files
        - other_files_to_exclude
    )

    # Create collection with additional modernize parameters for each file.
    files_modernize_params = collections.defaultdict(dict)  # type: Dict[str, Any]

    # __scalyr__.py can not have "six" as dependency, because third_party libraries are not imported yet,
    # so modernize should not add import of "six" in it.
    scalyr_py_path = os.path.join(source_root, "__scalyr__.py")
    files_modernize_params[scalyr_py_path] = {"disabled_fixers": six_fix_names}

    is_concurrent = args.processes > 1
    # if concurrent mode enabled, create executor.
    executor = (
        ProcessPoolExecutor(max_workers=args.processes) if is_concurrent else None
    )

    diffs = dict()
    if not args.write:
        print("Only compatibility check started. Files will not be changed.")

    current_file_number = 1

    def progress_message(file_path):
        global current_file_number
        print(
            "Processing {} ({}) of {}.".format(
                current_file_number, file_path, total_files_count
            )
        )
        current_file_number += 1

    total_files_count = len(files_to_process)

    for file_path in files_to_process:
        try:
            diff = process_file(
                file_path,
                write=args.write,
                executor=executor,
                **files_modernize_params[file_path]
            )
            if not is_concurrent:
                progress_message(file_path)

            diffs[file_path] = diff

        except TODOParseError:
            print("Can not modernize file: {}".format(file_path))
            raise
    if is_concurrent:
        for file_path, future in list(diffs.items()):
            try:
                diffs[file_path] = future.result()
                progress_message(file_path)
            except TODOParseError:
                print("Can not modernize file: {}".format(file_path))
                raise
    print("\n\n=======================================\n")
    sys.stdout.flush()
    time.sleep(0.1)

    diffs = [diff for diff in list(diffs.values()) if diff]  # type: ignore

    if diffs:
        if args.write:
            print(
                "Python-modernize found and modernized code in files:", file=sys.stderr
            )
        else:
            print(
                "Python-modernize found code that can be modernized in files:",
                file=sys.stderr,
            )
        print("\n".join(sorted(diffs)), file=sys.stderr)
        exit(1)
    print("All files are up to date.")
    # Nothing to update. Exit without error.
