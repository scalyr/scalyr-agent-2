# Copyright 2019 Scalyr Inc.
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
# author: Steven Czerwinski <czerwin@scalyr.com>
import threading

__author__ = 'czerwin@scalyr.com'

from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.monitor_utils.k8s import DockerMetricFetcher

import logging


class TestDockerMetricFetcher(ScalyrTestCase):
    """Tests the DockerMetricFetch abstraction.
    """
    def setUp(self):
        self._faker = DockerClientFaker()
        self._fetcher = DockerMetricFetcher(self._faker, 5)

    def test_basic_prefetch(self):
        """Tests the typical prefetch and then get_metrics path.. just for one container.
        """
        self._fetcher.prefetch_metrics('foo')
        self.assertTrue(self._faker.wait_for_requests(1))
        self.assertEquals(0, self._fetcher.idle_workers())
        self._faker.resolve_metric('foo', 10)
        value = self._fetcher.get_metrics('foo')
        self.assertEqual(1, self._fetcher.idle_workers())
        self.assertEqual(10, value)

    def test_multiple_prefetch(self):
        """Tests the typical prefetch and then get_metrics path for multiple concurrent requests.
        """
        self._fetcher.prefetch_metrics('foo')
        self._fetcher.prefetch_metrics('bar')
        self.assertTrue(self._faker.wait_for_requests(2))
        self.assertEquals(0, self._fetcher.idle_workers())

        self._faker.resolve_metric('foo', 10)
        value = self._fetcher.get_metrics('foo')
        self.assertEquals(1, self._fetcher.idle_workers())
        self.assertEqual(10, value)

        self._faker.resolve_metric('bar', 5)
        value = self._fetcher.get_metrics('bar')
        self.assertEquals(2, self._fetcher.idle_workers())
        self.assertEqual(5, value)

    def test_limit_by_concurrency(self):
        """Tests that we only have at most `concurrency` threads for fetching metrics."""
        container_names = []

        for i in range(0, 10):
            container_names.append('foo-%d' % i)
            self._fetcher.prefetch_metrics(container_names[i])

        # Since we have concurrency as 5, we should only have at most 5 requests in flight.
        self.assertTrue(self._faker.wait_for_requests(5))
        self.assertEquals(0, self._fetcher.idle_workers())

        for i in range(0, 5):
            self._faker.resolve_metric(container_names[i], i)

        self.assertTrue(self._faker.wait_for_requests(5))
        self.assertEquals(0, self._fetcher.idle_workers())

        for i in range(0, 5):
            value = self._fetcher.get_metrics(container_names[i])
            self.assertEquals(i, value)

        self.assertTrue(self._faker.wait_for_requests(5))
        self.assertEquals(0, self._fetcher.idle_workers())

        # Once the first batch have been resolved, we should see the other 5 fetches get issued.
        for i in range(5, 10):
            self._faker.resolve_metric(container_names[i], i)

        for i in range(5, 10):
            value = self._fetcher.get_metrics(container_names[i])
            self.assertEquals(i, value)

        self.assertEquals(5, self._fetcher.idle_workers())

    def test_stopped(self):
        """Tests that stopping the abstraction terminates any calls blocked on `get_metrics`.
        """
        self._fetcher.prefetch_metrics('foo')
        self.assertTrue(self._faker.wait_for_requests(1))

        self._fetcher.stop()

        value = self._fetcher.get_metrics('foo')
        self.assertIsNone(value)

    def test_no_prefetch(self):
        """Tests that if you invoke `get_metrics` without a `prefetch_metrics` first, we still will fetch the
        metrics.
        """
        self._faker.resolve_metric('foo', 10)
        value = self._fetcher.get_metrics('foo')
        self.assertEqual(1, self._fetcher.idle_workers())
        self.assertEqual(10, value)


class DockerClientFaker(object):
    """A fake DockerClient that only supports the `stats` call.  Used for tests to control when a `stats` call
    should finish and what it should return.
    """
    def __init__(self):
        # Lock that must be held to modify any state
        self.__lock = threading.Lock()
        # The results to return.  Maps from container to the result.
        self.__results_to_return = dict()
        # The conditional var used to notify changes on this object.
        self.__cv = threading.Condition(self.__lock)
        # The total number of requests blocking on a `stats` call.
        self.__pending_requests = 0

    def stats(self, container=None, stream=False):
        if stream:
            return 'Unexpected stream=True in fake metric fetcher'

        self.__lock.acquire()
        try:
            self.__pending_requests += 1
            # Notify any threads blocking in `wait_for_requests` that a new pending request has been received.
            self.__cv.notifyAll()

            # Wait until the result shows up in `__results_to_return`.
            while True:
                if container in self.__results_to_return:
                    result = self.__results_to_return[container]
                    del self.__results_to_return[container]
                    self.__pending_requests -= 1
                    return result
                self.__cv.wait()
        finally:
            self.__lock.release()

    def resolve_metric(self, container_id, metric_value):
        """Update this instance so that any pending or future call to `stats` for the specified metric should finish
        and return the specified value.

        @param container_id: The container we are reporting
        @param metric_value:  The value to return

        @type container_id: str
        @type metric_value: int
        """
        self.__lock.acquire()
        try:
            self.__results_to_return[container_id] = metric_value
            # Notify any threads waiting on `stats` that result they be interested in has been added.
            self.__cv.notifyAll()
        finally:
            self.__lock.release()

    def wait_for_requests(self, target_pending):
        """Block until there are the specified number of threads blocked on `stats`

        This is used for testing.

        @param target_pending: The number of threads that should be blocking before this call returns.
        @type target_pending: int

        @return If there are exactly `target_pending` blocking.  False otherwise.
        @rtype bool
        """
        self.__lock.acquire()
        try:
            while True:
                if self.__pending_requests == target_pending:
                    return True
                elif self.__pending_requests > target_pending:
                    return False
                self.__cv.wait()
        finally:
            self.__lock.release()
