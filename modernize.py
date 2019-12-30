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

from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import re
import os
import io
import difflib
import functools
import argparse
from concurrent.futures import ProcessPoolExecutor

import six
from six.moves import zip
import glob2
from libmodernize.main import refactor
from libmodernize.fixes import six_fix_names

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
}


def modernize_string(source, disabled_fixers=None):
    """
    Apply "modernize" to string with python source code.
    :param source: source code.
    :param disabled_fixers: fixers which are not going to be used in this file processing.
    :return: "Modernized" source code
    :type source six.text_type
    :type disabled_fixers set
    :rtype six.text_type
    """
    if disabled_fixers is None:
        disabled_fixers = set()

    fixers = FIXERS - set(disabled_fixers)
    tool = refactor.RefactoringTool(sorted(fixers))
    tree = tool.refactor_string(source, "<stdin>")
    new_source = six.text_type(tree)

    return new_source


def get_diff(new_source, original_source, file_path):
    """
    Get diff from two strings.
    :param new_source:
    :param original_source:
    :param file_path:
    :return: string with diff
    :rtype six.text_type
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


def parse_todos(source):
    """
    :param source: string with python source code
    :type source six.text_type
    :return:
    """
    # pattern to find start of the area [start of 2->TOD0]
    start_pattern = r"(?!\n)[\s]*#\s*\[\s*start of 2->TODO\s*[a-zA-Z._ ]*\s*\]"
    # pattern to find end of the area [start of 2->TOD0]
    end_pattern = r"#\s*\[\s*end of 2->TOD[O0]\s*\]"
    todo_area_pattern = re.compile(
        r"{start}((?:(?!{end}).)*){end}".format(start=start_pattern, end=end_pattern),
        re.DOTALL,
    )
    found = todo_area_pattern.findall(source)

    return found


def process_file(file_path, write=False, **kwargs):
    """
    Apply modernize on source code from file and check it is up to date.
    :param file_path:
    :param write: Writes all found modification.
    :param kwargs: all additional arguments to "process_source_string"
    :type write bool
    :return:
    """

    with io.open(file_path, "r") as file:
        original_source_string = file.read()
    new_source_string = process_source_string(original_source_string, **kwargs)

    # create diff from original source code and after modernize.
    diff = get_diff(new_source_string, original_source_string, file_path)

    # if there are changes and write option is set, than we write new string to file.
    if diff and write:
        with io.open(file_path, "w") as file:
            file.write(new_source_string)

    # return diff for console report.
    return diff


def process_source_string(original_source_string, disabled_fixers=None):
    """
    Apply modernize on string, but leave [ start of 2->TOD0] untouched.
    :param original_source_string:
    :param disabled_fixers: fixers which are not going to be used in this file processing.
    :type original_source_string: six.text_type
    :type disabled_fixers set
    :return:
    """

    # parse and save [2->TOD0] areas.
    original_todos = parse_todos(original_source_string)

    # modernize source code.
    modernized_source_string = modernize_string(
        original_source_string, disabled_fixers=disabled_fixers
    )

    # parse [2->TOD0] areas which are now modernized too.
    new_todos = parse_todos(modernized_source_string)

    result_source_string = modernized_source_string

    # something went wrong with parsing
    if len(original_todos) != len(new_todos):
        raise RuntimeError("some of [2->TODO] areas was corrupted.")

    # replace modernized [2->TOD0] areas with original.
    for o, n in zip(original_todos, new_todos):
        result_source_string = result_source_string.replace(n, o, 1)

    return result_source_string


def _process(file_infos, write=False):
    for file_path, info in six.iteritems(file_infos):
        diff = process_file(file_path, write=write, **info)
        if not diff:
            continue
        yield diff


def _process_parallel(file_infos, max_workers=1, write=False):
    executor = ProcessPoolExecutor(max_workers=max_workers)
    futures = dict()
    for file_path, info in six.iteritems(file_infos):
        future = executor.submit(process_file, file_path, write=write, **info)
        futures[file_path] = future

    for file_path, future in six.iteritems(futures):
        diff = future.result()
        if not diff:
            continue

        yield diff


def process_all(file_infos, max_workers=1, write=False):
    """
    :param file_infos:
    :param max_workers: jobs count. If more than 1, multiprocessing is used.
    :param write: write changes.
    :type max_workers: int
    :type file_infos: dict
    :type write: bool
    :return: dict with diffs for each file_path
    :rtype: dict
    """

    if max_workers > 1:
        do_process = functools.partial(
            _process_parallel, max_workers=max_workers, write=write
        )
    else:
        do_process = _process
    diffs = list(do_process(file_infos))

    return diffs


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

    new_source = process_source_string(orig_source)
    assert new_source == expected_source, "Test failed."


# simple test before main activity.
_run_tests()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        default=False,
        help="Write modified files.",
    )
    parser.add_argument(
        "-j", "--processes", default=1, type=int, help="Run modernize concurrently."
    )
    parser.add_argument("--test", action="store_true", default=False, help="Run tests")
    args = parser.parse_args()
    root = os.path.dirname(__file__)
    source_root = os.path.join(root, "scalyr_agent")

    # do not modernize third_party libraries.
    third_party_files = set(glob2.glob("{0}/third_party*/**/*.py".format(source_root)))

    input_file_infos = {
        file_path: dict()
        for file_path in set(glob2.glob("{}/**/*.py".format(root), recursive=True))
        - third_party_files
    }

    # __scalyr__.py can not have "six" as dependency, because third_party libraries are not imported yet.
    input_file_infos[os.path.join(source_root, "__scalyr__.py")][
        "disabled_fixers"
    ] = six_fix_names

    all_diffs = process_all(
        input_file_infos, max_workers=args.processes, write=args.write
    )

    if all_diffs:
        print("Python-modernize found code to update in files:")
        print("\n".join(sorted(all_diffs)))
        exit(1)
    print("All files are up to date.")
    # Nothing to update. Exit without error.
