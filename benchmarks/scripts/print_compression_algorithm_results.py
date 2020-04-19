#!/usr/bin/env python
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

"""
Script which pretty prints benchmark results for compression algorithms benchmarks.
"""


from __future__ import absolute_import
from __future__ import print_function

import sys
import copy
import json

from io import open

from collections import defaultdict

from prettytable import PrettyTable  # pylint: disable=import-error


def main():
    with open(sys.argv[1], "r") as fp:
        data = fp.read()

    data = json.loads(data)

    result = defaultdict(list)

    print(("=" * 100))
    print("Compression")
    print(("=" * 100))

    for benchmark in data["benchmarks"]:
        if benchmark["group"] != "compress":
            continue

        name = benchmark["name"]
        key = "=".join([str(x) for x in benchmark["params"]["log_tuple"]])
        mean = benchmark["stats"]["mean"] * 1000
        compression_ratio = round(benchmark["stats"]["compression_ratio"], 3)
        result[key].append((benchmark["name"], mean, compression_ratio))

    for key in result.keys():
        values = result[key]
        split = key.split("=")

        print("")
        print(("-" * 100))
        print("")

        print(("%s %s bytes (-1 means whole file)" % (split[0], split[1])))
        print("")

        print("Best by timing (less is better)")
        print("")

        table = PrettyTable()
        table.field_names = [
            "name",
            "mean time in ms (less is better)",
            "compression ratio (more is better)",
        ]

        values1 = sorted(copy.copy(values), key=lambda x: x[1])

        for name, mean, compression_ratio in values1:
            table.add_row((name, mean, compression_ratio))

        print(table)

        print("")
        print("Best by compression ratio (more is better)")
        print("")

        table = PrettyTable()
        table.field_names = [
            "name",
            "mean time in ms (less is better)",
            "compression ratio (more is better)",
        ]

        values2 = sorted(copy.copy(values), key=lambda x: x[2], reverse=True)

        for name, mean, compression_ratio in values2:
            table.add_row((name, mean, compression_ratio))

        print(table)

        print("")
        print(("=" * 100))
        print("")

    result = defaultdict(list)

    print(("=" * 100))
    print("Decompression")
    print(("=" * 100))

    for benchmark in data["benchmarks"]:
        if benchmark["group"] != "decompress":
            continue

        name = benchmark["name"]
        key = "=".join([str(x) for x in benchmark["params"]["log_tuple"]])
        mean = benchmark["stats"]["mean"] * 1000
        result[key].append((benchmark["name"], mean))

    for key in result.keys():
        values = result[key]
        split = key.split("=")

        print("")
        print(("-" * 100))
        print("")

        print(("%s %s bytes (-1 means whole file)" % (split[0], split[1])))
        print("")

        print("Best by timing (less is better)")
        print("")

        table = PrettyTable()
        table.field_names = ["name", "mean time in ms (less is better)"]

        values1 = sorted(copy.copy(values), key=lambda x: x[1])

        for name, mean in values1:
            table.add_row((name, mean))

        print(table)

        print("")
        print(("=" * 100))
        print("")


if __name__ == "__main__":
    main()
