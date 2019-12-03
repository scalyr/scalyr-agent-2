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

__author__ = "czerwin@scalyr.com"

import sys

from optparse import OptionParser

from scalyr_agent.__scalyr__ import scalyr_init

scalyr_init()

from scalyr_agent.monitors_manager import load_monitor_class


def print_monitor_documentation(monitor_module, column_size, additional_module_paths):
    """Prints out the documentation for the specified monitor.

    @param monitor_module: The module the monitor is defined in.
    @param column_size: The maximum line size to use.
    @param additional_module_paths: Any additional paths that should be examined to load the monitor module.  This
        can contain multiple paths separated by os.pathsep

    @type monitor_module: str
    @type column_size: int
    @type additional_module_paths: str
    """
    info = load_monitor_class(monitor_module, additional_module_paths)[1]
    print "Description:"
    print info.description

    print "Options:"
    print_options(info.config_options, column_size)
    print ""

    print "Log reference:"
    print_log_fields(info.log_fields, column_size)
    print ""

    print "Metrics:"
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
    print ""

    for category in categories:
        print "%s metrics" % category
        print_metrics(filter_metric_by_category(all_metrics, category), column_size)
        print ""


def print_options(option_list, column_size):
    """Prints the options table for the options.

    @param option_list: The list of options.
    @param column_size: The maximum line size to use.

    @type option_list: list of scalyr_agent.scalyr_monitor.ConfigOption
    @type column_size: int
    """
    # First, prepare a list of lists representing the table contents.  Each row has two elements.
    rows = [["# Option", "Usage"]]
    for x in option_list:
        rows.append(["# ``%s``" % x.option_name, x.description])

    # We let the second column take up as much room as it needs, so find out how large the first column is
    # by finding the longest string in it.
    longest_first_column = ""
    for x in rows:
        if len(x[0]) > len(longest_first_column):
            longest_first_column = x[0]

    # The length has to include the '|||' characters we prefix the line with.
    first_column_length = 3 + len(longest_first_column)

    sys.stdout.flush()
    for row in rows:
        sys.stdout.write(
            "|||%s%s||| "
            % (row[0], space_filler(first_column_length - len(row[0]) - 3))
        )
        write_wrapped_line(
            row[1],
            column_size - first_column_length - 4,
            " " * (first_column_length + 4),
        )
    sys.stdout.flush()


def print_log_fields(log_fields_list, column_size):
    """Prints the log reference table for the log fields.

    @param log_fields_list: The list of log fields.
    @param column_size: The maximum line size to use.

    @type log_fields_list: list of scalyr_agent.scalyr_monitor.LogFieldDescription
    @type column_size: int
    """
    # First, prepare a list of lists representing the table contents.  Each row has two elements.
    rows = [["# Field", "Meaning"]]
    for x in log_fields_list:
        rows.append(["# ``%s``" % x.field, x.description])

    # We let the second column take up as much room as it needs, so find out how large the first column is
    # by finding the longest string in it.
    longest_first_column = ""
    for x in rows:
        if len(x[0]) > len(longest_first_column):
            longest_first_column = x[0]

    # The length has to include the '|||' characters we prefix the line with.
    first_column_length = 3 + len(longest_first_column)

    sys.stdout.flush()
    for row in rows:
        sys.stdout.write(
            "|||%s%s||| "
            % (row[0], space_filler(first_column_length - len(row[0]) - 3))
        )
        write_wrapped_line(
            row[1],
            column_size - first_column_length - 4,
            " " * (first_column_length + 4),
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
    metric_name_column = ["Metric"]
    # The extra fields column is optional, only used if any of the metrics has extra fields.  The content
    # for each cell will be a list of strings, one for each extra field.
    extra_fields_column = [["Fields"]]
    # The description is the last column.
    description_column = ["Description"]

    total_extra_fields = 0

    for metric in metric_list:
        # Create the metric name cell for this row.
        metric_name_column.append("``%s``" % metric.metric_name)

        # Create the description
        description_column.append(metric.description)

        # Create the extra fields cell for this row.
        cell = []
        extra_fields_column.append(cell)
        if metric.extra_fields is not None and len(metric.extra_fields) > 0:
            # Create an entry for each extra field.  We create a string representation that is
            # field_name=value if value is not an empty string, otherwise just field_name.
            for key, value in metric.extra_fields.iteritems():
                if value == "":
                    str_rep = "``%s``" % key
                else:
                    str_rep = "``%s=%s``" % (key, value)
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

    description_column_width = (
        column_size - metric_name_column_width - extra_field_column_width
    )

    # Actually print out the rows.
    for row in range(len(metric_name_column)):
        # Print the metric name with enough padding to get to the end of the column.
        metric_cell = "|||# %s " % metric_name_column[row]
        sys.stdout.write(
            "%s%s"
            % (metric_cell, space_filler(metric_name_column_width - len(metric_cell)))
        )

        # If we have an extra field column, print it out.
        if extra_field_column_width > 0:
            sys.stdout.write("||| ")
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
        sys.stdout.write("||| ")
        write_wrapped_line(
            description_column[row],
            description_column_width,
            space_filler(column_size - description_column_width + 4),
        )

    sys.stdout.flush()


def write_wrapped_line(content, wrap_length, line_prefix):
    """Writes content to stdout but breaking it after ``wrap_length`` along space boundaries.

    When it begins a new line, ``line_prefix`` is printed first.

    @param content: The line to write
    @param wrap_length: The maximum size of any line emitted.  After this length, the line will be wrapped.
    @param line_prefix: The prefix to write whenenver starting a new line

    @type content: str
    @type wrap_length: int
    @type line_prefix: str
    """
    current_line = ""
    for word in content.split(" "):
        if len(current_line) + len(word) + 3 > wrap_length:
            sys.stdout.write(current_line)
            sys.stdout.write(" \\\n")
            sys.stdout.write(line_prefix)
            current_line = word
        elif len(current_line) == 0:
            current_line = word
        else:
            current_line = "%s %s" % (current_line, word)

    if len(current_line) > 0:
        sys.stdout.write(current_line)
        sys.stdout.write("\n")


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

    (options, args) = parser.parse_args()

    if len(args) != 1:
        print >> sys.stderr, "You must specify the module for the monitor whose documentation you wish to print."
        parser.print_help(sys.stderr)
        sys.exit(1)

    if not options.no_warning:
        print >> sys.stderr, (
            "Warning, this tool is still experimental.  The format of the output may change in the"
            "future.  Use with caution."
        )

    print_monitor_documentation(args[0], int(options.column_size), options.module_paths)
    sys.exit(0)
