#!/usr/bin/env python
#
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
# Script used to print documentation for a single Scalyr Monitor Plugin.
#
# NOTE, this script is still experimental and will probably change over time.
#
#
# Usage: python print_monitor_doc.py [options] monitor_module
#
# author: Steven Czerwinski <czerwin@scalyr.com>

from __future__ import absolute_import
from __future__ import print_function

__author__ = "czerwin@scalyr.com"

import sys

from optparse import OptionParser

from scalyr_agent.__scalyr__ import scalyr_init

scalyr_init()

# [start of 2->TODO]
# Check for suitability.
# Important. Import six as any other dependency from "third_party" libraries after "__scalyr__.scalyr_init"
import six
from six.moves import range

# [end of 2->TOD0]

from scalyr_agent.monitors_manager import load_monitor_class


def print_monitor_documentation(
    monitor_module, column_size, additional_module_paths, include_sections
):
    """Prints out the documentation for the specified monitor.

    @param monitor_module: The module the monitor is defined in.
    @param column_size: The maximum line size to use.
    @param additional_module_paths: Any additional paths that should be examined to load the monitor module.  This
        can contain multiple paths separated by os.pathsep
    @param include_sections: List of sections to include in the output.

    @type monitor_module: str
    @type column_size: int
    @type additional_module_paths: str
    @type include_sections: list
    """
    include_sections = include_sections or [
        "description",
        "configuration_reference",
        "log_reference",
        "metrics",
    ]
    info = load_monitor_class(monitor_module, additional_module_paths)[1]

    if "description" in include_sections:
        # NOTE: We only include monitor name header if the section doesn't already contain one
        if "# " not in info.description:
            # This turns scalyr_agent.builtin_monitors.redis_monitor -> Redis
            monitor_module = info.monitor_module.split(".")[-1]
            monitor_name = monitor_module.replace("_", " ").title().split()
            print("# %s" % (monitor_name[0]))
            print("")

        print(info.description)
        print("")

    if "configuration_reference" in include_sections and len(info.config_options) > 0:
        print('<a name="options"></a>')
        print("## Configuration Options")
        print("")
        print_options(info.config_options, column_size)
        print("")

    if "log_reference" in include_sections and len(info.log_fields) > 0:
        print('<a name="events"></a>')
        print("## Event Reference")
        print("")
        print("In the UI, each event has the fields:")
        print("")
        print_log_fields(info.log_fields, column_size)
        print("")

    if "metrics" not in include_sections or len(info.metrics) == 0:
        return

    print('<a name="metrics"></a>')
    print("## Metrics Reference")
    print("")
    print("Metrics recorded by this plugin:")
    print("")

    # Have to break the metrics up into their categories if they have them.
    all_metrics = info.metrics

    # Determine the unique categories.
    categories = []
    for metric in all_metrics:
        if metric.category is None:
            continue
        # This is a bit inefficient, but that's ok here.
        if categories.count(metric.category) == 0:
            categories.append(metric.category)

    # Print each grouping.
    metrics_with_no_categories = filter_metric_by_category(all_metrics, None)
    if len(metrics_with_no_categories) > 0:
        print_metrics(metrics_with_no_categories, column_size)
    print("")

    for category in categories:
        print("### %s Metrics" % category)
        print("")
        print_metrics(filter_metric_by_category(all_metrics, category), column_size)
        print("")


def print_options(option_list, column_size):
    """Prints the options table for the options.

    @param option_list: The list of options.
    @param column_size: The maximum line size to use.

    @type option_list: list of scalyr_agent.scalyr_monitor.ConfigOption
    @type column_size: int
    """
    # First, prepare a list of lists representing the table contents.  Each row has two elements.
    # Append ["---", "---"] to generate the markdown delimiter row.
    rows = [["Property", "Description"]]
    rows.append(["---", "---"])
    for x in option_list:
        rows.append(["`%s`" % x.option_name, x.description])
    # We let the second column take up as much room as it needs, so find out how large the first column is
    # by finding the longest string in it.
    longest_first_column = ""
    for x in rows:
        if len(x[0]) > len(longest_first_column):
            longest_first_column = x[0]

    # The length has to include the '|' characters we prefix the line with.
    first_column_length = 1 + len(longest_first_column)

    sys.stdout.flush()
    for row in rows:
        sys.stdout.write(
            "| %s%s |" % (row[0], space_filler(first_column_length - len(row[0]) - 1))
        )
        sys.stdout.write(" %s | \n" % (row[1]))
    sys.stdout.flush()


def print_log_fields(log_fields_list, column_size):
    """Prints the log reference table for the log fields.

    @param log_fields_list: The list of log fields.
    @param column_size: The maximum line size to use.

    @type log_fields_list: list of scalyr_agent.scalyr_monitor.LogFieldDescription
    @type column_size: int
    """
    # First, prepare a list of lists representing the table contents.  Each row has two elements.
    # Append ["---", "---"] to generate the markdown delimiter row.
    rows = [["Field", "Description"]]
    rows.append(["---", "---"])
    for x in log_fields_list:
        rows.append(["`%s`" % x.field, x.description])

    # We let the second column take up as much room as it needs, so find out how large the first column is
    # by finding the longest string in it.
    longest_first_column = ""
    for x in rows:
        if len(x[0]) > len(longest_first_column):
            longest_first_column = x[0]

    # The length has to include the '|' characters we prefix the line with.
    first_column_length = 1 + len(longest_first_column)

    sys.stdout.flush()
    for row in rows:
        sys.stdout.write(
            "| %s%s | %s | \n"
            % (row[0], space_filler(first_column_length - len(row[0]) - 1), row[1])
        )
    sys.stdout.flush()


def print_metrics(metric_list, column_size):
    """Prints the metrics table for the metrics.

    @param metric_list: The list of metrics.
    @param column_size: The maximum line size to use.

    @type metric_list: list of scalyr_agent.scalyr_monitor.MetricDescription
    @type column_size: int
    """

    # Create the contents of the table, split up by the different columns.  We populate each column with
    # its header row.
    # The metric name column will be the first be displayed.
    # Append "---" to all 3 columns to generate the markdown delimiter row.
    metric_name_column = ["Metric"]
    metric_name_column.append("---")
    # The extra fields column is optional, only used if any of the metrics has extra fields.  The content
    # for each cell will be a list of strings, one for each extra field.
    extra_fields_column = [["Fields"]]
    extra_fields_column.append(["---"])
    # The description is the last column.
    description_column = ["Description"]
    description_column.append("---")

    total_extra_fields = 0

    for metric in metric_list:
        # Create the metric name cell for this row.
        metric_name_column.append("`%s`" % metric.metric_name)

        # Create the description
        description_column.append(metric.description.strip())

        # Create the extra fields cell for this row.
        cell = []
        extra_fields_column.append(cell)
        if metric.extra_fields is not None and len(metric.extra_fields) > 0:
            # Create an entry for each extra field.  We create a string representation that is
            # field_name=value if value is not an empty string, otherwise just field_name.
            for key, value in six.iteritems(metric.extra_fields):
                if value == "":
                    str_rep = "`%s`" % key
                else:
                    str_rep = "`%s=%s`" % (key, value)
                cell.append(str_rep)
                total_extra_fields += 1

    # Calculate the width of the extra field column.
    extra_field_column_width = 0
    for cell in extra_fields_column:
        for field in cell:
            extra_field_column_width = max(extra_field_column_width, len(field) + 5)

    if total_extra_fields == 0:
        extra_field_column_width = 0

    # Calculate the width of the metric name column.
    metric_name_column_width = 0
    for cell in metric_name_column:
        metric_name_column_width = max(metric_name_column_width, len(cell) + 6)

    # Actually print out the rows.
    for row in range(len(metric_name_column)):
        # Print the metric name with enough padding to get to the end of the column.
        metric_cell = "| %s " % metric_name_column[row]
        sys.stdout.write(
            "%s%s"
            % (metric_cell, space_filler(metric_name_column_width - len(metric_cell)))
        )

        # If we have an extra field column, print it out.
        if extra_field_column_width > 0:
            sys.stdout.write("| ")
            extra_cell = extra_fields_column[row]
            # If there are multiple fields, then we want to stick a newline and padding in the next line to
            # get the next field lined up with the previous one.  We can do this trick with str.join
            line_join = ", \\\n%s" % space_filler(metric_name_column_width + 4)
            sys.stdout.write(line_join.join(extra_cell))
            # Have to print enough spaces to fill out the rest of the space to the description column.
            if len(extra_cell) > 0:
                sys.stdout.write(
                    space_filler(extra_field_column_width - len(extra_cell[-1]) - 4)
                )
            else:
                sys.stdout.write(space_filler(extra_field_column_width - 4))

        # The description gets line wrapped in the final column.
        sys.stdout.write("| %s | \n" % description_column[row])

    sys.stdout.flush()


def space_filler(num_spaces):
    """Returns a string with the specified number of spaces.

    @param num_spaces: The number of spaces
    @type num_spaces: int
    @return: The string
    @rtype: str
    """
    return " " * num_spaces


def filter_metric_by_category(metrics, category):
    """Returns the metric list filtered by metrics that have the specified category.

    @param metrics: The list of the metrics.
    @param category: The category name, or None if should match for all metrics that have None as category.
    @type metrics: list of MetricDescription
    @type category: str or None
    @return: The filtered list.
    @rtype: list of MetricDescription
    """
    result = []
    for metric in metrics:
        if metric.category is None:
            if category is None:
                result.append(metric)
        elif metric.category == category:
            result.append(metric)
    return result


if __name__ == "__main__":
    parser = OptionParser(
        usage="Usage: python print_monitor_doc.py [options] monitor_module"
    )
    parser.add_option(
        "",
        "--no-warning",
        action="store_true",
        dest="no_warning",
        default=False,
        help="Suppresses warning that you should not rely format of the output on this tool yet since it "
        "may change.",
    )
    parser.add_option(
        "-c",
        "--column-size",
        dest="column_size",
        default=120,
        help="Sets the number of columns to constrain the output to.",
    )
    parser.add_option(
        "-p",
        "--additional-module-paths",
        dest="module_paths",
        help="Additional paths to examine to search for the monitor module, beyond the standard ones.",
    )
    parser.add_option(
        "" "--include-sections",
        dest="include_sections",
        default="description,configuration_reference,log_reference,metrics",
        help="Comma delimited list of sections to include (e.g. configuration_reference,metrics)",
    )
    (options, args) = parser.parse_args()

    if len(args) != 1:
        print(
            "You must specify the module for the monitor whose documentation you wish to print.",
            file=sys.stderr,
        )
        parser.print_help(sys.stderr)
        sys.exit(1)

    if not options.no_warning:
        print(
            "Warning, this tool is still experimental.  The format of the output may change in the"
            "future.  Use with caution.",
            file=sys.stderr,
        )

    include_sections = options.include_sections.split(",")

    print_monitor_documentation(
        args[0], int(options.column_size), options.module_paths, include_sections
    )
    sys.exit(0)
