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
# ------------------------------------------------------------------------
#
# author: Edward Chee <echee@scalyr.com>

from __future__ import unicode_literals
from __future__ import absolute_import


from scalyr_agent.builtin_monitors.url_monitor import UrlMonitor
from scalyr_agent.test_base import ScalyrMockHttpServerTestCase

import mock

__all__ = ["UrLMonitorTest"]


def mock_view_func_200():
    return "yay, success!"


def mock_view_func_200_multiline():
    return "line 1\nline 2\nline 3"


def mock_view_func_200_long_response():
    return "a" * 1000


def mock_view_func_non200():
    return "error", 500


class UrLMonitorTest(ScalyrMockHttpServerTestCase):
    @classmethod
    def setUpClass(cls):
        super(UrLMonitorTest, cls).setUpClass()

        # Register mock route
        cls.mock_http_server_thread.app.add_url_rule(
            "/200", view_func=mock_view_func_200
        )
        cls.mock_http_server_thread.app.add_url_rule(
            "/200_long", view_func=mock_view_func_200_long_response
        )
        cls.mock_http_server_thread.app.add_url_rule(
            "/200_multiline", view_func=mock_view_func_200_multiline
        )
        cls.mock_http_server_thread.app.add_url_rule(
            "/500", view_func=mock_view_func_non200
        )

    def test_gather_sample_200_success(self):
        url = "http://%s:%s/200" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )

        monitor_config = {
            "module": "shell_monitor",
            "url": url,
            "request_method": "GET",
            "max_characters": 100,
        }
        mock_logger = mock.Mock()
        monitor = UrlMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(call_args[0], "response")
        self.assertEqual(call_args[1], "yay, success!")
        self.assertEqual(call_kwargs["extra_fields"]["url"], url)
        self.assertEqual(call_kwargs["extra_fields"]["status"], 200)
        self.assertEqual(call_kwargs["extra_fields"]["request_method"], "GET")

    def test_gather_sample_200_success_long_body_is_truncated(self):
        url = "http://%s:%s/200_long" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )

        monitor_config = {
            "module": "shell_monitor",
            "url": url,
            "request_method": "GET",
            "max_characters": 10,
        }
        mock_logger = mock.Mock()
        monitor = UrlMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(call_args[0], "response")
        self.assertEqual(call_args[1], "a" * 10 + "...")
        self.assertEqual(call_kwargs["extra_fields"]["url"], url)
        self.assertEqual(call_kwargs["extra_fields"]["status"], 200)
        self.assertEqual(call_kwargs["extra_fields"]["request_method"], "GET")

    def test_gather_sample_200_success_multiline(self):
        url = "http://%s:%s/200_multiline" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )

        # log_all_lines=False (only first line should be logged)
        monitor_config = {
            "module": "shell_monitor",
            "url": url,
            "request_method": "GET",
            "max_characters": 100,
        }
        mock_logger = mock.Mock()
        monitor = UrlMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(call_args[0], "response")
        self.assertEqual(call_args[1], "line 1")
        self.assertEqual(call_kwargs["extra_fields"]["url"], url)
        self.assertEqual(call_kwargs["extra_fields"]["status"], 200)
        self.assertEqual(call_kwargs["extra_fields"]["request_method"], "GET")

        # log_all_lines=True (all lines should be logged)
        monitor_config = {
            "module": "shell_monitor",
            "url": url,
            "request_method": "GET",
            "max_characters": 100,
            "log_all_lines": True,
        }
        mock_logger = mock.Mock()
        monitor = UrlMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(call_args[0], "response")
        self.assertEqual(call_args[1], "line 1\nline 2\nline 3")
        self.assertEqual(call_kwargs["extra_fields"]["url"], url)
        self.assertEqual(call_kwargs["extra_fields"]["status"], 200)
        self.assertEqual(call_kwargs["extra_fields"]["request_method"], "GET")

    def test_gather_sample_non_200_error(self):
        url = "http://%s:%s/500" % (
            self.mock_http_server_thread.host,
            self.mock_http_server_thread.port,
        )

        monitor_config = {
            "module": "shell_monitor",
            "url": url,
            "request_method": "GET",
            "max_characters": 100,
        }
        mock_logger = mock.Mock()
        monitor = UrlMonitor(monitor_config, mock_logger)

        monitor.gather_sample()
        call_args_list = mock_logger.emit_value.call_args_list[0]
        call_args = call_args_list[0]
        call_kwargs = call_args_list[1]

        self.assertEqual(mock_logger.error.call_count, 0)
        self.assertEqual(call_args[0], "response")
        self.assertEqual(call_args[1], "error")
        self.assertEqual(call_kwargs["extra_fields"]["url"], url)
        self.assertEqual(call_kwargs["extra_fields"]["status"], 500)
        self.assertEqual(call_kwargs["extra_fields"]["request_method"], "GET")
