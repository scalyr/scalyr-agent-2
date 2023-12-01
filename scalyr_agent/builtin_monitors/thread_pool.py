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
# @author ales.novak@sentinelone.com

import threading
from concurrent.futures import ThreadPoolExecutor

from scalyr_agent import scalyr_logging

global_log = scalyr_logging.getLogger(__name__)

# A MixIn class used for adding a thread poll processing to a BaseServer (i.e. SyslogTCPServer, SyslogUDPServer)
class ExecutorMixIn:
    def __init__(self, global_config):
        # Using 4 threads for processing requests, because of GIL and CPU bound tasks higher number would not help process the data faster.
        processing_threads = 4
        # Let the ThreadPoolExecutor decide how many threads to use based the numbre of logical CPUs
        reading_threads = None

        if global_config:
            reading_threads = global_config.syslog_socket_thread_count
            processing_threads = global_config.syslog_processing_thread_count

        self._request_reading_executor = ThreadPoolExecutor(max_workers=reading_threads, thread_name_prefix="request_reading_executor")
        self._request_processing_executor = ThreadPoolExecutor(max_workers=processing_threads, thread_name_prefix="request_processing_executor")

        # Since the older versions of python use daemon threads, we need to let the pool create the threads this constructor's thread.
        self.__warmup_thread_pool(self._request_reading_executor)
        self.__warmup_thread_pool(self._request_processing_executor)

    def __warmup_thread_pool(self, thread_pool):
        # Warmup the thread pool
        for _ in range(thread_pool._max_workers):
            thread_pool._adjust_thread_count()

    def process_request_thread(self, request, client_address):
        """Same as in BaseServer but as a thread.

        In addition, exception handling is done here.

        """
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def process_request(self, request, client_address):
        if not self._request_processing_executor:
           raise ValueError(str(self.__class__) + " is not initialized properly")

        """Start a new thread to process the request."""
        self._request_reading_executor.submit(
            self.process_request_thread, request, client_address
        )

    def server_close(self):
        self._request_reading_executor.shutdown(wait=False)
        self._request_processing_executor.shutdown(wait=False)
        super().server_close()
