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

"""
Scalyr monitor which can scrape metrics from HTTP interface exposed by the jmx_exporter Java agent
plugin (https://github.com/prometheus/jmx_exporter).

Monitor support specifying a whitelist of metric names to scrape, but users are strongly encouraged
to filter metrics at the source aka configure jmx_exporter to only expose metrics you want to
scrape (this way you avoid additional filtering overhead in this monitor).

By default if no filters are specified, all the metric are included.

NOTE: Technically this monitor can scrape metrics from any /metrics HTTP endpoint which returns
data in Prometheus compatible format, but it hasn't been tested with other endpoints so it's
classified as JMX exporter monitor for now.

Some applications also return pre-aggregated values (e.g. percentiles, etc.) and those are not
supported at this point.
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

define_log_field(__monitor__, "monitor", "Always ``jmx_exporter_monitor``.")


define_config_option(
    __monitor__,
    "url",
    "URL to the JMX exporter HTTP interface (e.g. https://my.host:8080/metrics).",
)

define_config_option(
    __monitor__,
    "metric_name_whitelist",
    "List of globs for metric names to scrape (defaults to all)",
    convert_to=ArrayOfStrings,
    default=["*"],
)

TYPE_KEY_RE = re.compile('.*type="(.*?)".*')
POOL_KEY_RE = re.compile('.*pool="(.*?)".*')
KEY_KEY_RE = re.compile('.*key="(.*?)".*')


class JMXExporterMonitor(ScalyrMonitor):
    def _initialize(self):
        # type: () -> None
        self.__url = self._config.get(
            "url", convert_to=six.text_type, required_field=True,
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
        Scrape metrics from JMX exporter interface and return dictionary with parsed metrics.
        """
        resp = requests.get(url)

        if resp.status_code != 200:
            self._logger.warn(
                "Failed to fetch metrics from %s: %s" % (self.__url, resp.text)
            )
            return []

        lines = resp.text.splitlines()

        result = []

        for line in lines:
            if line.startswith("# "):
                # Comment
                continue

            split = line.rsplit(" ", 1)
            metric_name, extra_fields = self._sanitize_metric_name(split[0])
            metric_value = split[1]

            if not metric_name:
                continue

            if "." in metric_value:
                metric_value = float(metric_value)  # type: ignore
            else:
                metric_value = int(metric_value)  # type: ignore

            if not self._should_include_metric_name(metric_name):
                continue

            item = (metric_name, extra_fields, metric_value)
            result.append(item)

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

        # Find any extra componenets
        type_match = TYPE_KEY_RE.match(split[1])
        pool_match = POOL_KEY_RE.match(split[1])
        key_match = KEY_KEY_RE.match(split[1])

        if type_match:
            extra_fields["type"] = self._sanitize_simple_metric_name(
                type_match.groups()[0]
            )

        if pool_match:
            extra_fields["pool"] = self._sanitize_simple_metric_name(
                pool_match.groups()[0]
            )

        if key_match:
            extra_fields["key"] = self._sanitize_simple_metric_name(
                key_match.groups()[0]
            )

        return metric_name, extra_fields
