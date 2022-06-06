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

Monitor support specifying a include_list of metric names to scrape using metric name and metric
component value filters using the configuration options described below:

- ``metric_name_include_list`` - A list of metric names to include. If not specified, we include all
  the scraped metrics.

  For example:

      ``["my.metric1", "my.metric2"].

- ``metric_component_value_include_list`` - Dictionary where the key is a metric name and the value is
  an object where a key is component name and the value is a list of globs for the component values.

  For examples:

      {
        "kafka_log_log_numlogsegments": {"topic": ["connect-status"]},
        "kafka_log_log_logstartoffset": {"topic": ["connect-status", "connect-failures"]},
      }

  In this example, only metric with name ``kafka_log_log_numlogsegments`` and
  ``kafka_log_log_logstartoffset`` where the ``topic`` component name is ``connect-status`` will
  be included.

  Another option is something like this:

      {
        "*": {"topic": "account-foo-*"},
      }

  In this example any metric which has a component (extra attribute) named ``topic`` with a value of
  ``account-foo-*`` will be included.

  Keep in mind that globs are only supported for metric component value items and special "*" glob
  for the metric name which matches all the metrics.

``metric_name_include_list`` has priority over ``metric_component_value_include_list`` config option.

- ``metric_name_exclude_list`` - A list of metrics names to exclude. This has higher priority over
  include list which means that a metric won't be included if it's specified in this list even if
  it's also specified in an include list.

Where possible you are strongly encouraged to filter metrics at the source aka configure various
Prometheus exporters (where applicable and possible) to only expose metrics you want to ingest
(this way we can avoid additional filtering overhead in this monitor).

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

- If metric contains a description / help string, should we include this with every metric as part
  of the extra_fields? This could provide large increase in storage and little value so it may not
  be a good idea.
"""

from __future__ import absolute_import

if False:
    from typing import Tuple
    from typing import Any
    from typing import List
    from typing import Dict
    from typing import Optional

import re
import fnmatch
import time

import six
import requests

from scalyr_agent import ScalyrMonitor
from scalyr_agent import define_config_option
from scalyr_agent import define_log_field
from scalyr_agent.scalyr_monitor import BadMonitorConfiguration
from scalyr_agent.json_lib.objects import ArrayOfStrings
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonArray

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
    "headers",
    "Optional HTTP headers which are sent with the outgoing request.",
    convert_to=JsonObject,
    default=JsonObject({}),
)

define_config_option(
    __monitor__,
    "timeout",
    "Timeout for outgoing requests.",
    convert_to=int,
    default=10,
)

define_config_option(
    __monitor__,
    "ca_file",
    "Optional file with CA certificate used to validate the server certificate. Only applies to https "
    "requests.",
    convert_to=str,
    default=None,
)

define_config_option(
    __monitor__,
    "verify_https",
    "Set to False to disable verification of the server certificate and hostname for https requests.",
    convert_to=bool,
    default=True,
)

define_config_option(
    __monitor__,
    "metric_name_include_list",
    "List of globs for metric names to scrape (defaults to all).",
    convert_to=ArrayOfStrings,
    default=["*"],
)

define_config_option(
    __monitor__,
    "metric_name_exclude_list",
    "List of globs for metric names to exclude (all the metrics are included by default). NOTE: "
    "Exclude list has priority over a white list. This means that if the same metric name is specified "
    "in exclude and include list, it will be excluded.",
    convert_to=ArrayOfStrings,
    default=[],
)

# Maps metric_name to a dictionary where the key is extra_field key name and a value is a list of
# globs for the value include_list.
#
# For example:
# {
#    'kafka_log_log_logstartoffset': {'topic': ['connect-status', 'connect-test']},
#    'kafka_server_fetcherlagmetrics_consumerlag': {'topic': ['connect-status', 'connect-test']}
# }
define_config_option(
    __monitor__,
    "metric_component_value_include_list",
    "List of globs for metric component values to include_list. Metrics which extra_fields don't "
    "match this include_list will be ignored (defaults to all). If this value is set you also need "
    'set "metric_name_include_list" value to an empty list ([]) otherwise all metrics will be included.',
    convert_to=JsonObject,
    default=JsonObject({}),
)

define_config_option(
    __monitor__,
    "extra_fields",
    "Optional dictionary with extra fields which are included with each emitted metric line.",
    convert_to=JsonObject,
    default=JsonObject({}),
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
        self.__timeout = self._config.get("timeout", 10)
        self.__verify_https = self._config.get("verify_https", True)
        self.__headers = self._config.get(
            "headers",
            {},
        )
        self.__ca_file = self._config.get(
            "ca_file",
            None,
        )

        if self._config.get("metric_name_include_list") is not None:
            if isinstance(self._config.get("metric_name_include_list"), ArrayOfStrings):
                self.__metric_name_include_list = self._config.get(
                    "metric_name_include_list"
                )._items
            else:
                self.__metric_name_include_list = self._config.get(
                    "metric_name_include_list"
                )
        else:
            self.__metric_name_include_list = ["*"]

        if self._config.get("metric_name_exclude_list") is not None:
            if isinstance(self._config.get("metric_name_exclude_list"), ArrayOfStrings):
                self.__metric_name_exclude_list = self._config.get(
                    "metric_name_exclude_list"
                )._items
            else:
                self.__metric_name_exclude_list = self._config.get(
                    "metric_name_exclude_list"
                )
        else:
            self.__metric_name_exclude_list = []

        self.__metric_component_value_include_list = (
            self._validate_metric_component_value_include_list(
                self._config.get("metric_component_value_include_list", {})
            )
        )

        self.__include_all_metrics = (
            "*" in self.__metric_name_include_list
            and not self.__metric_component_value_include_list
            and not self.__metric_name_exclude_list
        )

        self.__base_extra_fields = dict(self._config.get("extra_fields", {}) or {})

        # Override the default value for the rate limit for writing the metric logs. We override the
        # default value since each scrape could result in a lot of metrics.
        self._log_write_rate = self._config.get(
            "monitor_log_write_rate", convert_to=int, default=-1
        )
        self._log_max_write_burst = self._config.get(
            "monitor_log_max_write_burst", convert_to=int, default=-1
        )

        base_request_headers = {"User-Agent": "scalyr-agent-2/OpenMetricsMonitor"}
        base_request_headers.update(self.__headers)

        self.__session = requests.Session()
        self.__session.headers.update(base_request_headers)

    def gather_sample(self):
        # type: () -> None
        # We want to use the same timestamp for all the metrics in a batch (aka all the metrics
        # which are scraped at the same time( to make joins and other server side operations easier.
        # Keep in mind that in case the parsed metric (aka record) contains a custom timestamp,
        # that value has precedence over this one aka that record / metric specific value will be
        # used for that metric
        timestamp_ms = round(time.time() * 1000)

        start_ts = time.time()
        metrics = self._scrape_metrics(self.__url)
        end_ts = time.time()

        self._logger.debug(
            f"Scraping and parsing metrics for url {self.__url} took {(end_ts - start_ts):.3f} seconds."
        )

        for metric_name, extra_fields, metric_value in metrics:
            extra_fields.update(self.__base_extra_fields or {})
            self._logger.emit_value(
                metric_name,
                metric_value,
                extra_fields=extra_fields,
                timestamp=timestamp_ms,
            )

    def check_connectivity(self) -> requests.Response:
        """
        Send the request to the configured URL and return a response.

        This is used for checking connectivity and other similar purposes.
        """
        request_kwargs = self._get_request_kwargs(url=self.__url)
        resp = self.__session.get(self.__url, **request_kwargs, timeout=self.__timeout)
        return resp

    def _get_request_kwargs(self, url: str) -> dict:
        """
        Return optional keyword arguments which are passed to the requests.get() method for the
        provided url.
        """
        request_kwargs = {}
        if url.startswith("https://"):
            verify = self.__verify_https

            if self.__ca_file:
                verify = self.__ca_file

            request_kwargs["verify"] = verify

        # TODO: Use rate limited warn if verify is false
        return request_kwargs

    def _scrape_metrics(self, url):
        # type: (str) -> List[Tuple[str, dict, Any]]
        """
        Scrape metrics from Prometheus interface and return dictionary with parsed metrics.
        """
        request_kwargs = self._get_request_kwargs(url=url)

        try:
            resp = self.__session.get(url, **request_kwargs, timeout=self.__timeout)
        except Exception as e:
            self._logger.warn(
                "Outgoing request failed to %s failed: %s" % (url, str(e))
            )
            return []

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

        total_metrics_count = (
            0  # total number of returned metrics, including ignored ones
        )
        included_metrics_count = 0  # number of metrics which are included
        ignored_metrics_count = 0  # number of ignored / skipped metrics

        for line in lines:
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
            elif "e+" in metric_value or "e-" in metric_value:
                # Special case for values in scientific notation which we first need to cast to
                # float
                metric_value = float(metric_value)  # type: ignore
                metric_value = int(metric_value)  # type: ignore
            elif metric_value == "+Inf":
                pass
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

            total_metrics_count += 1

            if not self._should_include_metric(
                metric_name=metric_name, extra_fields=extra_fields
            ):
                ignored_metrics_count += 1
                continue

            metric_type = metric_name_to_type_map.get(metric_name, None)
            if metric_type and metric_type not in SUPPORTED_METRIC_TYPES:
                self._logger.debug(
                    "Ignoring non-supported metric type (%s). Line: %s"
                    % (metric_type, line)
                )
                continue

            included_metrics_count += 1

            item = (metric_name, extra_fields, metric_value)
            result.append(item)

        if included_metrics_count > MAX_METRICS_PER_GATHER_WARN:
            limit_key = "max-metrics-" + self.__url
            self._logger.warn(
                "Parsed more than 2000 metrics (%s) for URL %s. You are strongly "
                "encouraged to filter metrics at the source or set "
                '"metric_name_exclude_list" monitor configuration option to avoid '
                "excessive number of metrics being ingested."
                % (included_metrics_count, self.__url),
                limit_once_per_x_secs=86400,
                limit_key=limit_key,
            )

        if total_metrics_count >= 1 and included_metrics_count == 0:
            limit_key = "no-metrics-" + self.__url
            self._logger.warn(
                "Server returned %s metrics, but none were included. This likely means "
                "that filters specified as part of the plugin configuration are too restrictive and "
                "need to be relaxed." % (total_metrics_count),
                limit_once_per_x_secs=86400,
                limit_key=limit_key,
            )

        return result

    def _should_include_metric(self, metric_name, extra_fields=None):
        # type: (str, Optional[Dict[Any,Any]]) -> bool
        """
        Return True if the provided metirc should be included based on the configuration specified
        filters.
        """
        extra_fields = extra_fields or {}

        # Short circuit if globs indicates include all
        if self.__include_all_metrics:
            return True

        # 1. Perform metric_name exclude_list checks
        for glob_pattern in self.__metric_name_exclude_list:
            if fnmatch.fnmatch(metric_name, glob_pattern):
                return False

        # 2. Perform extra_field include_list checks
        # NOTE: User can specify "*" for metric name which means we will check this filter against
        # all the metric names
        metric_component_value_include_list = (
            self.__metric_component_value_include_list.get(
                metric_name, self.__metric_component_value_include_list.get("*", {})
            )
        )

        for (
            extra_field_name,
            extra_field_value_filters,
        ) in metric_component_value_include_list.items():
            for glob_pattern in extra_field_value_filters:
                extra_field_value = extra_fields.get(extra_field_name, "")

                if fnmatch.fnmatch(extra_field_value, glob_pattern):
                    return True

        # 3. Perform metric_name include_list checks
        for glob_pattern in self.__metric_name_include_list:
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

    def _validate_metric_component_value_include_list(self, value):
        """
        Validate that the "metric_component_value_include_list" configuration options is in a correct
        format (if specified).
        """
        value = value or {}

        for metric_name, component_filters in value.items():
            if not isinstance(component_filters, (dict, JsonObject)):
                raise BadMonitorConfiguration(
                    "Value must be a dictionary (got %s)" % (type(component_filters)),
                    field="metric_component_value_include_list",
                )

            for component_name, component_filter_globs in component_filters.items():
                if not isinstance(component_filter_globs, (list, tuple, JsonArray)):
                    raise BadMonitorConfiguration(
                        "Value must be a list of strings (got %s)"
                        % (type(component_filter_globs)),
                        field="metric_component_value_include_list",
                    )

                for filter_glob in component_filter_globs:
                    if not isinstance(filter_glob, six.text_type):
                        raise BadMonitorConfiguration(
                            "Value must be a list of strings (got list of %s)"
                            % (type(filter_glob)),
                            field="metric_component_value_include_list",
                        )

        return value
