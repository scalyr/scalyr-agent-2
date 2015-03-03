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
# An example ScalyrMonitor plugin to demonstrate how they can be written.
#
# Note, this can be run in standalone mode by:
#     python -m scalyr_agent.run_monitor -c "{ gauss_mean: 0.5 }" scalyr_agent.builtin_monitors.test_monitor
#
# author:  Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import random

from scalyr_agent import ScalyrMonitor


class RandomMonitor(ScalyrMonitor):
    """A Scalyr agent monitor that records random numbers.
    """
    def _initialize(self):
        """Performs monitor-specific initialization."""
        # TODO:  Is it better to have this, or just require that classes override __init__ and do their
        # initialization that way.  If we do that, then they must know the argument list for __init__.

        # Useful instance variables:
        #   self._sample_interval_secs:  The number of seconds between calls to gather_sample.
        #   self._config:  The MonitorConfig object containing the configuration for this monitor instance as retrieved
        #                  from configuration file.  It is essentially like a dict but has some methods for validating
        #                  field values.
        #   self._logger:  The logger instance to report errors/warnings/etc.
        #   self.log_config: The dict containing the configuration for how the metric log created by the
        #                    this module should be saved.  It uses the same fields as the entries in agent.json's
        #                    "logs" section.  You can set the path for the log file, as well as the attributes
        #                    such as the parser, etc.
        #  self._log_write_rate:  The allowed average number of bytes per second that can be written to the metric
        #                         log for this monitor.  If this monitor tries to emit more than these number of
        #                         bytes, then log lines are dropped (and a warning message is emitted to the log
        #                         indicating how many lines were dropped).  The actual rate limit is calculated using
        #                         a leaky bucket algorithm, where this is the fill rate (per second) of the bucket.
        #  self._log_max_write_burst:  The maximum allowed log write burst rate.  This is used in conjunction with
        #                              self._log_write_rate to rate limit how many bytes this monitor can write to
        #                              the metric log.  The actual rate limit is calculated using a leaky bucket
        #                              algorithm, where this is the bucket size.
        self.__counter = 0
        # A required configuration field.
        self.__gauss_mean = self._config.get('gauss_mean',  convert_to=float, min_value=0, max_value=10,
                                             required_field=True)
        # An optional configuration field.
        self.__gauss_stddev = self._config.get('gauss_stddev', default=0.25, convert_to=float,
                                               min_value=0, max_value=5)

    def gather_sample(self):
        """Invoked once per sample interval to gather a statistic."""
        self.__counter += 1
        # Be sure to use emit_values to record the statistics the monitor wishes to send to Scalyr.
        self._logger.emit_value('uniform', random.random(), extra_fields={'count': self.__counter})
        self._logger.emit_value('gauss', random.gauss(self.__gauss_mean, self.__gauss_stddev),
                                extra_fields={'count': self.__counter})

        # You may also emit full log lines to the metric log by using the special emit_to_metric_log=True parameter.
        # Otherwise, the log lines will be assumed to be errors and will go to the agent.log
        # self._logger.info('This will go to the metric log', emit_to_metric_log=True)