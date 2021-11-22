# Copyright 2021 Scalyr Inc.
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
Monitor which scrapes metrics from OpenMetrics / Prometheus metrics API endpoint.

Monitor support specifying a whitelist of metric names to scrape, but users are strongly encouraged
to filter metrics at the source aka configure various Prometheus exporters (where applicable and
possible) to only expose metrics you want to ingest (this way we can avoid additional filtering
overhead in this monitor).

By default no filters are specified which means all the metric are included.

----

Metrics are in the following format:

1. Metric name
2. Any number of labels (can be 0), represented as a key-value array
3. Current metric value
4. Optional metric timestamp

For example:

http_requests_total{method="post",code="400"}  3   1395066363000
http_requests 2
# HELP metric_name Description of the metric
# TYPE metric_name type
# Comment that's not parsed by prometheus
http_requests_total{method="post",code="400"}  3   1395066363000

See https://github.com/OpenObservability/OpenMetrics/blob/main/specification/OpenMetrics.md for
details.

# TODO:

- Add support for Protobuf format
- If metric contains a description / help string, should we include this with every metric as part
  of the extra_fields? This could provide large increase in storage and little value so it may not
  be a good idea.
"""

from __future__ import absolute_import

if False:
    from typing import Tuple
    from typing import Any
    from typing import List

import re
import fnmatch

import six
import requests

from scalyr_agent import ScalyrMonitor
from scalyr_agent import define_config_option
from scalyr_agent import define_log_field
from scalyr_agent.json_lib.objects import ArrayOfStrings

__monitor__ = __name__

define_log_field(__monitor__, "monitor", "Always ``openmetrics_monitor``.")
define_log_field(
    __monitor__, "instance", "The ``id`` value from the monitor configuration."
)
define_log_field(__monitor__, "metric", "The name of a metric being measured.")
define_log_field(__monitor__, "value", "The metric value.")

define_config_option(
    __monitor__,
    "url",
    "URL to the OpenMetrics / Prometheus API endpoint (e.g. https://my.host:8080/metrics).",
    convert_to=six.text_type,
)

define_config_option(
    __monitor__,
    "metric_name_whitelist",
    "List of globs for metric names to scrape (defaults to all)",
    convert_to=ArrayOfStrings,
    default=[u"*"],
)

# A list of metric types we currently support. Keep in mind that Scalyr doesn't currently
# support some metric types such as histograms and summaries.
SUPPORTED_METRIC_TYPES = [
    "counter",
    "gauge",
    "untyped",
]

# If more than this number of metrics are returned at once we log a warning since this could mean
# misconfiguration on the user side (not filtering metrics at the source / on the monitor level).
MAX_METRICS_PER_GATHER_WARN = 2000


class OpenMetricsMonitor(ScalyrMonitor):
    def _initialize(self):
        # type: () -> None
        self.__url = self._config.get(
            "url",
            convert_to=six.text_type,
            required_field=True,
        )

        if self._config.get("metric_name_whitelist"):
            if isinstance(self._config.get("metric_name_white"), ArrayOfStrings):
                self.__metric_name_whitelist = self._config.get(
                    "metric_name_whitelist"
                )._items
            else:
                self.__metric_name_whitelist = self._config.get("metric_name_whitelist")
        else:
            self.__metric_name_whitelist = ["*"]

        self.__include_all_metrics = "*" in self.__metric_name_whitelist

    def gather_sample(self):
        # type: () -> None
        metrics = self._scrape_metrics(self.__url)

        for metric_name, extra_fields, metric_value in metrics:
            self._logger.emit_value(
                metric_name, metric_value, extra_fields=extra_fields
            )

    def _scrape_metrics(self, url):
        # type: (str) -> List[Tuple[str, dict, Any]]
        """
        Scrape metrics from Prometheus interface and return dictionary with parsed metrics.
        """
        resp = requests.get(url)

        if resp.status_code != 200:
            self._logger.warn(
                "Failed to fetch metrics from %s: status_code=%s,body=%s"
                % (self.__url, resp.status_code, resp.text)
            )
            return []

        # NOTE: To be more compatible we assume Content-Type is text in case header is not provided
        # and we only explicitly skip Protobuf format
        content_type = resp.headers.get("Content-Type", "application/openmetrics-text")
        if "application/openmetrics-protobuf" in content_type:
            self._logger.warn(
                "Received non-supported protobuf format. Content-type: %s"
                % (content_type)
            )
            return []

        lines = resp.text.splitlines()

        result = []

        metric_name_to_type_map = {}

        metrics_count = 0

        for line in lines:
            comment_metric_name = None
            comment_metric_type = None

            # Skip comments
            if line.startswith("# "):
                if "TYPE" in line:
                    comment_split = re.split(r"\s+", line)

                    if len(comment_split) < 4:
                        self._logger.warn(
                            "Received malformed comment line: %s" % (line)
                        )
                        continue

                    comment_metric_name = comment_split[2]
                    comment_metric_type = comment_split[3]
                    metric_name_to_type_map[comment_metric_name] = comment_metric_type

                # Comment
                continue

            # Skip empty lines
            if not line.strip(""):
                continue

            if "}" in line:
                # Metric name contains extra components
                char_index = line.find("}")
                metric_name = line[0 : char_index + 1]
                rest_of_the_line = line[char_index + 1 :].lstrip()
                split_partial = re.split(r"\s+", rest_of_the_line)
                split = [metric_name] + split_partial
            else:
                split = re.split(r"\s+", line)

            if len(split) < 2:
                self._logger.warn(
                    "Received invalid / unsupported metric line: %s" % (line)
                )
                continue

            metric_name = split[0]
            metric_name, extra_fields = self._sanitize_metric_name(metric_name)

            if not metric_name:
                self._logger.warn(
                    "Received invalid / unsupported metric line: %s" % (line)
                )
                continue

            metric_value = split[1]

            # TODO: Refactor emit_value so we support emitting custom timestamps. For now, we
            # include timestamp as an extra field
            if len(split) >= 3:
                try:
                    extra_fields["timestamp"] = int(split[2])
                except Exception:
                    self._logger.warn(
                        "Metric line contains invalid timestamp. Line: %s" % (line)
                    )

            if "." in metric_value:
                metric_value = float(metric_value)  # type: ignore
            else:
                # In some cases value may be NaN which we simply ignore
                try:
                    metric_value = int(metric_value)  # type: ignore
                except ValueError as e:
                    self._logger.warn(
                        'Failed to cast metric "%s" value "%s" to int: %s'
                        % (metric_name, metric_value, str(e))
                    )
                    continue

            if not self._should_include_metric_name(metric_name):
                continue

            metric_type = metric_name_to_type_map.get(metric_name, None)
            if metric_type and metric_type not in SUPPORTED_METRIC_TYPES:
                self._logger.debug(
                    "Ignoring non-supported metric type (%s). Line: %s"
                    % (metric_type, line)
                )
                continue

            metrics_count += 1

            item = (metric_name, extra_fields, metric_value)
            result.append(item)

        if metrics_count > MAX_METRICS_PER_GATHER_WARN:
            limit_key = self.__url
            self._logger.warn(
                "Parsed more than 2000 metrics (%s) for URL %s. You are strongly "
                "encouraged to filter metrics at the source or set "
                '"metric_name_blacklist" monitor configuration option to avoid '
                "excessive number of metrics being ingested."
                % (metrics_count, self.__url),
                limit_once_per_x_secs=86400,
                limit_key=limit_key,
            )

        return result

    def _should_include_metric_name(self, metric_name):
        # type: (str) -> bool

        # Short circuit if glob indicates include all
        if self.__include_all_metrics:
            return True

        for glob_pattern in self.__metric_name_whitelist:
            if fnmatch.fnmatch(metric_name, glob_pattern):
                return True

        return False

    def _sanitize_simple_metric_name(self, metric_name):
        # type: (str) -> str
        return (
            metric_name.lower()
            .replace("'", "")
            .replace('"', "")
            .replace(" ", "_")
            .replace("-", "_")
        )

    def _sanitize_metric_name(self, metric_name):
        # type: (str) -> Tuple[str, dict]
        """
        Parse and sanitize the metric name and return the sanitized metric name and dict with extra
        fields (if any).
        """
        split = metric_name.split("{")

        if len(split) == 1:
            # metric contains no extra components
            return self._sanitize_simple_metric_name(metric_name), {}

        metric_name = self._sanitize_simple_metric_name(split[0])
        extra_fields = {}

        metric_components = split[1].replace("}", "")
        metric_components_split = metric_components.split('",')

        for component in metric_components_split:
            if not component:
                continue

            component_split = component.split("=")
            component_name = component_split[0]
            component_value = component_split[1].replace('"', "")
            extra_fields[component_name] = component_value

        return metric_name, extra_fields
