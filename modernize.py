from __future__ import print_function

from __future__ import absolute_import
import re
import os
import glob2
import sys
import subprocess
from collections import defaultdict

from scalyr_agent.__scalyr__ import get_package_root

source_root = get_package_root()

root = os.path.dirname(source_root)


def modernize(files, params_str=""):
    """
    :param files: list of file paths.
    :param params_str:  additional parameters to python-modernize
    :return:
    """
    process = subprocess.Popen(
        "python-modernize {} {}".format(params_str, " ".join(list(files))),
        shell=True,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE
    )

    stdout = process.stdout

    diffs = defaultdict(list)

    while True:
        line = stdout.readline()
        if not line:
            break
        m = re.match(r"--- (.+)\s+\(original\)\n", line)
        if m:
            filename = m.group(1)
            diffs[filename].append(line)
            current_file = list()
            current_filename = filename
        else:
            diffs[current_filename].append(line)

    return diffs


# do not modernize third_party libraries.
third_party_files = set(glob2.glob("{0}/third_party*/**/*.py".format(source_root)))

regular_files = set(glob2.glob("{}/**/*.py".format(root), recursive=True)) - third_party_files

regular_files_diffs = modernize(regular_files)

# files to not modernize.
files_to_exclude = (
    os.path.join(root, os.path.join(*p))
    for p in (
    ('scalyr_agent', '__scalyr__.py'),
    ('scalyr_agent', '__scalyr__.py'),
    ('scalyr_agent', '__scalyr__.py'),
    ('scalyr_agent', '__scalyr__.py'),
    ('scalyr_agent', '__scalyr__.py'),
))

files_to_exclude = {os.path.join(root, os.path.join(*f)) for f in files_to_exclude}




general_files_diffs = modernize(regular_files)

if not file_diffs:
    print("All files are up to date.")
    exit(0)


for filename, lines in list(file_diffs.items()):
    file_diffs[filename] = "".join(lines)


print("Python-modernize found code to update in files:")


for filename, diff in list(file_diffs.items()):
    print(filename)
    print(diff)

exit(1)





a=10
