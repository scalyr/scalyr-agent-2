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
from dataclasses import dataclass, field
from enum import Enum
from queue import PriorityQueue
from typing import Any

from scalyr_agent import scalyr_logging

global_log = scalyr_logging.getLogger(__name__)


class PRIORITY(Enum):
    CMD = 0
    DATA = 1


@dataclass(order=True, frozen=True)
class PrioritizedItem:
    priority: int = field(default=PRIORITY.DATA.value, compare=True)
    request: Any = field(default=None, compare=False)
    client_address: Any = field(default=None, compare=False)
    shutdown: bool = field(default=False, compare=False)


class WorkQueue():
    def __init__(self, max_size):
        self.__queue = PriorityQueue(max_size)

    def submit_request(self, request, client_address):
        self.__queue.put(PrioritizedItem(request=request, client_address=client_address))

    def shutdown(self, force=False):
        priority = PRIORITY.CMD.value if force else PRIORITY.DATA.value
        self.__queue.put(PrioritizedItem(shutdown=True, priority=priority))

    def get(self):
        return self.__queue.get()

    def __len__(self):
        return self.__queue.qsize()


# A MixIn class used for adding a thread poll processing to a BaseServer (i.e. SyslogTCPServer, SyslogUDPServer)
class QueueMixin:

    # This is a MixIn class used to provide a SyslogUDPServer with a request queue.
    # Its main purpose is to provide a buffer for UDP requests to handle bursts of requests.

    def __init__(self, global_config):
        self.__is_closed = False
        self.__server_close_lock = threading.Lock()

        if global_config:
            request_queue_size = global_config.syslog_udp_socket_request_queue_size
            self._shutdown_grace_period = global_config.syslog_monitors_shutdown_grace_period
        else:
            request_queue_size = 100_000
            self._shutdown_grace_period = 5

        self.__request_queue = WorkQueue(request_queue_size)

        def read_requests_loop():
            while not self.__is_closed:
                try:
                    # Ignoring the priority here
                    item = self.__request_queue.get()
                    if item.shutdown:
                        break
                    self.process_request_thread(item.request, item.client_address)
                except:
                    global_log.exception("Error reading request from queue")

        self.__processing_thread = threading.Thread(target=read_requests_loop)
        self.__processing_thread.start()

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
            # if random.random() > 0.999:
            #     global_log.info(f"Queue size {threading.current_thread().name}: {len(self.__request_queue)}")

    def process_request(self, request, client_address):
        """Start a new thread to process the request."""
        try:
            self.__request_queue.submit_request(request=request, client_address=client_address)
        except:
            global_log.exception("Error submitting request to executor")

    def server_close(self):
        super().server_close()
        with self.__server_close_lock:
            if self.__is_closed:
                return

            self.__is_closed = True

            self.__gracefully_shutdown_processing_thread()

    def __gracefully_shutdown_processing_thread(self):
        self.__request_queue.shutdown(force=False)
        self.__processing_thread.join(timeout=self._shutdown_grace_period)

        if self.__processing_thread.is_alive():
            self.__request_queue.shutdown(force=True)

        self.__processing_thread.join()
        print("Cus")

