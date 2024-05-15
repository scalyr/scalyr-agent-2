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
from socketserver import ThreadingMixIn

from scalyr_agent import scalyr_logging

global_log = scalyr_logging.getLogger(__name__)


class BoundedThreadingMixIn(ThreadingMixIn):

    def __init__(self, global_config):
        if global_config:
            processing_threads = global_config.syslog_processing_thread_count
        else:
            processing_threads = 1000

        self.__threads_sempahore = threading.Semaphore(processing_threads)

    def process_request(self, request, client_address):
        self.__threads_sempahore.acquire()
        super().process_request(request, client_address)

    def shutdown_request(self, request):
        self.__threads_sempahore.release()
        super().shutdown_request(request)

