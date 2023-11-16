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

        self._request_reading_executor = ThreadPoolExecutor(max_workers=reading_threads)
        self._request_processing_executor = ThreadPoolExecutor(max_workers=processing_threads)

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

class ThreadPoolExecutorFactory():
    __lock = threading.Lock()
    __instances = {}

    @classmethod
    def get_singleton(cls, name, max_workers=None):
        if name not in cls.__instances:
            with cls.__lock:
                if name not in cls.__instances:
                    cls.__instances[name] = ThreadPoolExecutor(thread_name_prefix=name, max_workers=max_workers)
        return cls.__instances[name]

    @classmethod
    def shutdown(cls, wait=True, cancel_futures=False):
        wait_on_futures_str = " and waiting on futures" if wait else ""
        for name, executor in cls.__instances.items():
            global_log.info("Shutting down ThreadPoolExecutor%s: %s", wait_on_futures_str, name)
            try:
                executor.shutdown(wait=wait, cancel_futures=cancel_futures)
            except Exception as e:
                global_log.error("Failed shutting down the ThreadPoolExecutor %s", executor, exc_info=e)
