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
from scalyr_agent.monitor_utils.k8s import _K8sCache, _K8sProcessor, KubernetesApi, K8sApiNotFoundException, K8sApiTemporaryError, K8sApiPermanentError, ApiQueryOptions
from scalyr_agent.monitor_utils.blocking_rate_limiter import BlockingRateLimiter
import scalyr_agent.third_party.requests as requests
from scalyr_agent.util import FakeClock, md5_hexdigest
import scalyr_agent.scalyr_logging as scalyr_logging
import time
import mock

from mock import Mock, patch, call


class Test_K8sCache( ScalyrTestCase ):
    """ Tests the _K8sCache
    """

    NAMESPACE_1 = 'namespace_1'
    POD_1 = 'pod_1'

    class DummyObject(object):
        def __init__( self, access_time ):
            self.access_time = access_time

    def setUp(self):
        super(Test_K8sCache, self).setUp()
        self.k8s = FakeK8s()
        self.clock = FakeClock()
        self.processor = FakeProcessor()
        self.cache = _K8sCache( self.processor, 'foo' )

    def tearDown(self):
        self.k8s.stop()

    def test_purge_expired( self ):

        processor = Mock()
        cache = _K8sCache( processor, 'foo' )

        current_time = time.time()
        obj1 = self.DummyObject( current_time - 10 )
        obj2 = self.DummyObject( current_time + 15 )
        obj3 = self.DummyObject( current_time - 20 )

        objects = {
            'default': {
                'obj1': obj1,
                'obj2': obj2,
                'obj3': obj3
            }
        }

        # we should probably look at using actual values returned from k8s here
        # and loading them via 'cache.update'
        cache._objects = objects

        cache.purge_unused(current_time)

        objects = cache._objects.get('default', {})
        self.assertEquals( 1, len( objects ) )
        self.assertTrue( 'obj2' in objects )
        self.assertTrue( objects['obj2'] is obj2 )

    def test_lookup_not_in_cache( self ):

        self.k8s.set_response( self.NAMESPACE_1, self.POD_1, success=True )

        self.assertFalse( self.cache.is_cached( self.NAMESPACE_1, self.POD_1, allow_expired=True ) )

        obj = self.cache.lookup( self.k8s, self.clock.time(), self.NAMESPACE_1, self.POD_1 )

        self.assertTrue( self.cache.is_cached( self.NAMESPACE_1, self.POD_1, allow_expired=True ) )
        self.assertEqual( obj.name, self.POD_1 )
        self.assertEqual( obj.namespace, self.NAMESPACE_1 )

    def test_lookup_already_in_cache( self ):
        query_options = ApiQueryOptions()

        self.k8s.set_response( self.NAMESPACE_1, self.POD_1, success=True )
        obj = self.cache.lookup( self.k8s, self.clock.time(), self.NAMESPACE_1, self.POD_1, query_options=query_options )
        self.assertTrue( self.cache.is_cached( self.NAMESPACE_1, self.POD_1, allow_expired=True ) )

        self.k8s.set_response( self.NAMESPACE_1, self.POD_1, permanent_error=True )
        obj = self.cache.lookup( self.k8s, self.clock.time(), self.NAMESPACE_1, self.POD_1, query_options=query_options )

        self.assertTrue( self.cache.is_cached( self.NAMESPACE_1, self.POD_1, allow_expired=True ) )
        self.assertEqual( obj.name, self.POD_1 )
        self.assertEqual( obj.namespace, self.NAMESPACE_1 )

    def test_raise_exception_on_query_error( self ):
        query_options = ApiQueryOptions()

        self.k8s.set_response( self.NAMESPACE_1, self.POD_1, permanent_error=True )
        self.assertRaises( K8sApiPermanentError, lambda: self.cache.lookup( self.k8s, self.clock.time(), self.NAMESPACE_1, self.POD_1, query_options=query_options ) )

    def test_return_none_on_query_error_without_options( self ):

        self.k8s.set_response( self.NAMESPACE_1, self.POD_1, permanent_error=True )
        obj = self.cache.lookup( self.k8s, self.clock.time(), self.NAMESPACE_1, self.POD_1, ignore_k8s_api_exception=True )
        self.assertIsNone( obj )


class TestKubernetesApi(ScalyrTestCase):
    """
    Tests the Kubernetes API
    """
    def setUp(self):
        super(TestKubernetesApi, self).setUp()
        self._path = '/foo'

    def _get_expected_log_mesg(self, path, stack_trace_lines, response_content):
        """This helper method also serves as a assertion on the format for the log messages"""
        lines = ''
        for l in stack_trace_lines:
            lines += l.replace('\n', '\\n')
        return 'k8s.query_api (rate limited): %s\\n\\n\\n%s\\n\\n%s' % (path, lines, response_content)

    def _get_debug_call(self, expected_log_msg):
        """Return a mock call object that captures the param values of the log() call"""
        debug_log_call = call.log(
            scalyr_logging.DEBUG_LEVEL_1,
            expected_log_msg,
            limit_once_per_x_secs=300,
            limit_key='query-api-log-resp-%s' % md5_hexdigest(self._path))
        return debug_log_call

    def _assert_logged(self, mock_logger, expected_log_msg):
        """Assert that the log() method was called on the mock_logger with expected params"""
        mock_logger.log.assert_called_with(
            scalyr_logging.DEBUG_LEVEL_1,
            expected_log_msg,
            limit_once_per_x_secs=300,
            limit_key='query-api-log-resp-%s' % md5_hexdigest(self._path))

    def _assert_not_logged(self, mock_logger, expected_log_msg):
        """Assert that the log() method was not called on the mock_logger (with expected params)"""
        expected_call = self._get_debug_call(expected_log_msg)
        for mock_call in mock_logger.mock_calls:
            self.assertNotEquals(mock_call, expected_call)

    @patch('scalyr_agent.monitor_utils.k8s.global_log')
    @patch('traceback.format_stack')
    @patch.object(requests.Session, 'get')
    def _simulate_response(self, kapi, response_code_or_exception, mock_get, mock_stack_list, mock_logger):
        """Simulate a query to self._path and return expected log message that would have been logged if all criteria
        for logging were met.  (The caller is responsible for knowing if criteria were met.)

        This method fakes the stack trace and API query, thus making it possible to deterministically calculate the
        log message that would have been logged.
        """
        if isinstance(response_code_or_exception, Exception):
            mock_get.side_effect = response_code_or_exception
        else:
            resp = requests.Response()
            resp.status_code = response_code_or_exception
            resp._content = '{}'
            mock_get.return_value = resp

        stack_trace_lines = ['stack_trace_line_1\n', 'stack_trace_line_2\n']
        mock_stack_list.return_value = stack_trace_lines

        kapi.query_api(self._path, rate_limited=True)
        # Return the log message that should have been logged if all criteria are met
        return mock_logger, self._get_expected_log_mesg(self._path, stack_trace_lines, resp._content)

    def test_query_api_log_format(self):
        """Logging is turned on.  Asserts proper debug-logging (url + stacktrace + response content)"""
        kapi = KubernetesApi(log_api_responses=True)
        mock_logger, expected_log_msg = self._simulate_response(kapi, 200)
        self._assert_logged(mock_logger, expected_log_msg)

    def test_query_api_no_log(self):
        """Logging is turned off"""
        kapi = KubernetesApi(log_api_responses=False)
        mock_logger, expected_log_msg = self._simulate_response(kapi, 200)
        self._assert_not_logged(mock_logger, expected_log_msg)

    def test_query_api_min_response_len(self):
        """Fails to satisfy minimum response len.  Not logged"""
        kapi = KubernetesApi(log_api_responses=True, log_api_min_response_len=3)
        mock_logger, expected_log_msg = self._simulate_response(kapi, 200)
        self._assert_not_logged(mock_logger, expected_log_msg)

    def test_query_api_min_latency(self):
        """Fails to satisfy minimum latency.  Not logged"""
        kapi = KubernetesApi(log_api_responses=True, log_api_min_latency=10)
        mock_logger, expected_log_msg = self._simulate_response(kapi, 200)
        self._assert_not_logged(mock_logger, expected_log_msg)

    def test_query_api_ratelimit(self):
        """Fails to satisfy minimum latency.  Not logged"""
        kapi = KubernetesApi(log_api_responses=True, log_api_ratelimit_interval=77)
        mock_logger, expected_log_msg = self._simulate_response(kapi, 200)
        mock_logger.log.assert_called_with(
            scalyr_logging.DEBUG_LEVEL_1,
            expected_log_msg,
            limit_once_per_x_secs=77,
            limit_key='query-api-log-resp-%s' % md5_hexdigest(self._path))

    def test_query_api_200s_not_logged(self):
        """200 response not logged when 200s are excluded"""
        kapi = KubernetesApi(log_api_responses=True, log_api_exclude_200s=True)
        mock_logger, expected_log_msg = self._simulate_response(kapi, 200)
        self._assert_not_logged(mock_logger, expected_log_msg)

    def test_query_api_non_200_always_logged(self):
        """Non-200 response logged when 200s are excluded"""
        kapi = KubernetesApi(log_api_responses=True, log_api_exclude_200s=True)

        def func():
            mock_logger, expected_log_msg = self._simulate_response(kapi, 404)
            self._assert_logged(mock_logger, expected_log_msg)

        self.assertRaises(K8sApiNotFoundException, lambda: func())

    def test_query_api_exception_logged(self):
        """Exception response are logged in general"""
        kapi = KubernetesApi(log_api_responses=True)

        def func():
            mock_logger, expected_log_msg = self._simulate_response(kapi, requests.ReadTimeout())
            self._assert_logged(mock_logger, expected_log_msg)

        self.assertRaises(requests.ReadTimeout, lambda: func())

    def test_query_api_exception_obey_criteria(self):
        """Exception response obeys criteria (such as latency)"""
        kapi = KubernetesApi(log_api_responses=True, log_api_min_latency=100)

        def func():
            mock_logger, expected_log_msg = self._simulate_response(kapi, requests.ReadTimeout())
            self._assert_not_logged(mock_logger, expected_log_msg)

        self.assertRaises(requests.ReadTimeout, lambda: func())


class TestKubernetesApiRateLimited( ScalyrTestCase ):
    """
    Tests the Rate Limited Kubernetes API calls
    """
    def test_query_api_with_retries_success_not_rate_limited( self ):
        with mock.patch.object( KubernetesApi, "query_api" ) as mock_query:
            mock_query.return_value = { "success": "success" }

            k8s = KubernetesApi()
            rate_limiter = BlockingRateLimiter(
                num_agents=1, initial_cluster_rate=100, max_cluster_rate=1000, min_cluster_rate=1,
                consecutive_success_threshold=1,
                strategy='multiply',
            )
            options = ApiQueryOptions( rate_limiter=rate_limiter )
            result = k8s.query_api_with_retries( "/foo/bar", options )
            self.assertEqual( result, { "success": "success" } )
            self.assertEqual( rate_limiter.current_cluster_rate, 200.0 )

    def test_query_api_with_retries_not_found_not_rate_limited( self ):
        with mock.patch.object( KubernetesApi, "query_api" ) as mock_query:
            mock_query.side_effect = K8sApiNotFoundException( "/foo/bar" )

            k8s = KubernetesApi()
            rate_limiter = BlockingRateLimiter(
                num_agents=1, initial_cluster_rate=100, max_cluster_rate=1000, min_cluster_rate=1,
                consecutive_success_threshold=1,
                strategy='multiply',
            )
            options = ApiQueryOptions( rate_limiter=rate_limiter )
            self.assertRaises( K8sApiNotFoundException, lambda: k8s.query_api_with_retries( "/foo/bar", options ) )
            self.assertEqual( rate_limiter.current_cluster_rate, 200.0 )

    def test_query_api_with_retries_temp_error_rate_limited( self ):
        with mock.patch.object( KubernetesApi, "query_api" ) as mock_query:
            mock_query.side_effect = K8sApiTemporaryError( "Temporary Error" )

            k8s = KubernetesApi()
            rate_limiter = BlockingRateLimiter(
                num_agents=1, initial_cluster_rate=100, max_cluster_rate=1000, min_cluster_rate=1,
                consecutive_success_threshold=1,
                strategy='multiply',
            )
            options = ApiQueryOptions( rate_limiter=rate_limiter, max_retries=0 )
            self.assertRaises( K8sApiTemporaryError, lambda: k8s.query_api_with_retries( "/foo/bar", options ) )
            self.assertEqual( rate_limiter.current_cluster_rate, 50.0 )

    def test_query_api_with_retries_other_error_rate_limited( self ):
        with mock.patch.object( KubernetesApi, "query_api" ) as mock_query:
            mock_query.side_effect = K8sApiPermanentError( "Permanent Error" )

            k8s = KubernetesApi()
            rate_limiter = BlockingRateLimiter(
                num_agents=1, initial_cluster_rate=100, max_cluster_rate=1000, min_cluster_rate=1,
                consecutive_success_threshold=1,
                strategy='multiply',
            )
            options = ApiQueryOptions( rate_limiter=rate_limiter, max_retries=0 )
            self.assertRaises( K8sApiPermanentError, lambda: k8s.query_api_with_retries( "/foo/bar", options ) )
            self.assertEqual( rate_limiter.current_cluster_rate, 50.0 )

            mock_query.side_effect = Exception( "Some other exception" )
            self.assertRaises( Exception, lambda: k8s.query_api_with_retries( "/foo/bar", options ) )
            self.assertEqual( rate_limiter.current_cluster_rate, 25.0 )


class TestDockerMetricFetcher(ScalyrTestCase):
    """Tests the DockerMetricFetch abstraction.
    """
    def setUp(self):
        super(TestDockerMetricFetcher, self).setUp()
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

def create_object_from_dict( d ):
    """
    Takes a dict of key-value pairs and converts it to an object with attributes
    equal to the names of the keys and values equal to the values
    """
    result = type('', (), {})()
    for key, value in d.iteritems():
        setattr( result, key, value )
    return result

class FakeK8s( object ):
    """Used in the test to fake out the KubernetesApi.

    It allows for requests to the `query_object` method to block until some other caller supplies what response
    should be returned for it.
    """

    def __init__(self, wait_timeout=5 ):
        # Protects all state in this instance
        self.__lock = threading.Lock()
        # Signals changes to __pending_responses
        self.__condition_var = threading.Condition(self.__lock)
        # Maps from pod key (which is pod_namespace and pod_name) to the response that should be returned
        # for it.  The response is represented by a function pointer that when invoked will do the right thing.
        self.__pending_responses = dict()
        # The current pod key that is blocked waiting on a response.
        self.__pending_request = None

        # How long to block on waits - a normal test should be configured to complete almost instantly
        # set this value to raise an exception if it takes too long, to prevent the tests from hanging
        # indefinitely.
        self.wait_timeout = wait_timeout

    @staticmethod
    def __obj_key(namespace, name):
        return namespace + ':' + name

    @staticmethod
    def __split_obj_key(obj_key):
        parts = obj_key.split(':')
        return parts[0], parts[1]

    def _return_success(self, namespace, name):
        return {
            'namespace': namespace,
            'name': name
        }

    @staticmethod
    def _raise_temp_error(pod_namespace, pod_name):
        raise K8sApiTemporaryError('Temporary error')

    @staticmethod
    def _raise_perm_error(pod_namespace, pod_name):
        raise K8sApiPermanentError('Permanent error')

    def _raise_exception_if_timeout( self, start_time, message=None ):
        if message is None:
            message = "Timeout - waiting too long"

        if time.time() - start_time > self.wait_timeout:
            raise Exception( message )

    def query_object( self, kind, namespace, name, query_options=None ):
        """Faked KubernetesApi method that simulates blocking for querying the specified object.

        @param kind: The kind of object
        @param namespace: The namespace for the object
        @param name:  The name for the object

        @type kind: str
        @type namespace: str
        @type name: str
        """
        self.__lock.acquire()

        key = self.__obj_key(namespace, name)
        self.__pending_request = key
        try:
            # Block there is a response for this object.
            while key not in self.__pending_responses:
                # Notify any thread waiting to see if __pending_request is set.
                self.__condition_var.notify_all()
                # This should be awoken up by `set_response`
                self.__condition_var.wait( self.wait_timeout )

            return self.__pending_responses.pop(key)(namespace, name)
        finally:
            self.__pending_request = None
            self.__lock.release()

    def set_response(self, namespace, name, success=None, temporary_error=None, permanent_error=None):
        """Sets what response should be returned for the next call `query_object` for the specified object.

        @param namespace: The namespace for the object
        @param name:  The name for the object
        @param success:  True if success should be returned
        @param temporary_error: True if a temporary error should be raised
        @param permanent_error: True if a permanent error should be raised.

        @type namespace: str
        @type name: str
        @type success: bool
        @type temporary_error: bool
        @type permanent_error: bool
        """
        if success:
            response = self._return_success
        elif temporary_error:
            response = self._raise_temp_error
        elif permanent_error:
            response = self._raise_perm_error
        else:
            raise ValueError('Must specify one of the arguments')

        self.__lock.acquire()
        try:
            self.__pending_responses[self.__obj_key(namespace, name)] = response
            # Wake up anything blocked in `query_object`
            self.__condition_var.notify_all()
        finally:
            self.__lock.release()

    def stop(self):
        """Wakes up anything waiting on a pending requests.  Called when the test is finished.
        """
        self.__lock.acquire()
        try:
            if self.__pending_request is not None:
                # If there is still a blocked request at the end of the test, drain it out with an arbitrary
                # response so the testing thread is not blocked.
                self.__pending_responses[self.__pending_request] = self._raise_temp_error
                self.__condition_var.notify_all()
        finally:
            self.__lock.release()

    def wait_until_request_pending(self, namespace=None, name=None):
        """Blocks the caller until there is a pending call to the cache's `query_object` method that is blocked,
        waiting for a response to be added via `set_response`.  If no object is specified, will wait until
        any object invocation is blocked.

        @param namespace: If not None, this method won't block until there is a call with specified
            namespace blocked.
        @param name:  If not None, this method won't block until there is a call with specified
            name blocked.

        @type namespace: str
        @type name: str
        """
        if namespace is not None and name is not None:
            target_key = self.__obj_key(namespace, name)
        else:
            target_key = None

        start_time = time.time()
        self.__lock.acquire()
        try:
            if target_key is not None:
                while target_key != self.__pending_request:
                    self._raise_exception_if_timeout( start_time, "waiting too long for pending request" )
                    self.__condition_var.wait( self.wait_timeout )
            else:
                while self.__pending_request is None:
                    self._raise_exception_if_timeout( start_time, "waiting too long for pending request" )
                    self.__condition_var.wait( self.wait_timeout )
            return self.__split_obj_key(self.__pending_request)
        finally:
            self.__lock.release()

    def wait_until_request_finished(self, namespace, name):
        """Blocks the caller until the response registered for the specified object has been consumed.

        @param namespace: The namespace for the object
        @param name:  The name for the object

        @type namespace: str
        @type name: str
        """
        start_time = time.time()
        target_key = self.__obj_key(namespace, name)
        self.__lock.acquire()
        try:
            while target_key in self.__pending_responses:
                self._raise_exception_if_timeout( start_time, "waiting too long for request to finish" )
                self.__condition_var.wait( self.wait_timeout )
        finally:
            self.__lock.release()

class FakeProcessor( _K8sProcessor ):

    def process_object( self, k8s, obj, query_options=None ):
        """
        Return an object with attributes mapped to the keys and values of the `obj` parameter
        Only `obj` is used.  All other parameters are there to provide compatibility with the real
        process_object

        @param obj: a dict of key values that will be mapped to attributes of the result
        """
        return create_object_from_dict( obj )

class FakeCache(object):
    """Used in the test to fake out the KubernetesCache.

    It allows for requests to the `pod` method to block until some other caller supplies what response
    should be returned for it.
    """
    def __init__(self):

        self.__processor = FakeProcessor()
        self.__pod_cache = _K8sCache( self.__processor, 'Pod' )
        self.wait_timeout = 5
        self.k8s = FakeK8s( wait_timeout=self.wait_timeout )
        self.__clock = FakeClock()

    def is_pod_cached(self, pod_namespace, pod_name, allow_expired):
        """Faked KubernetesCache method that returns if the pod has been warmed from the cache's perspective.
        @param pod_namespace: The namespace for the pod
        @param pod_name:  The name for the pod
        @param allow_expired: If True, an object is considered present in cache even if it is expired.

        @type pod_namespace: str
        @type pod_name: str
        @type allow_expired: bool

        @return True if the pod has been warmed.
        @rtype: bool
        """
        return self.__pod_cache.is_cached( pod_namespace, pod_name, allow_expired )

    def pod(self, pod_namespace, pod_name, allow_expired=False, current_time=None, query_options=None ):
        """Faked KubernetesCache method that simulates blocking for the specified pod's cached entry.

        @param pod_namespace: The namespace for the pod
        @param pod_name:  The name for the pod

        @type pod_namespace: str
        @type pod_name: str
        """
        return self.__pod_cache.lookup(self.k8s, current_time, pod_namespace, pod_name, kind='Pod',
                                       allow_expired=allow_expired, query_options=query_options)

    def stop(self):
        """Stops the cache.  Called when the test is finished.
        """
        self.k8s.stop()

    def set_response(self, namespace, name, **kwargs ):
        self.k8s.set_response( namespace, name, **kwargs )

    def wait_until_request_pending(self, namespace=None, name=None ):
        return self.k8s.wait_until_request_pending( namespace=namespace, name=name )

    def wait_until_request_finished(self, namespace, name):
        return self.k8s.wait_until_request_finished( namespace, name )

    def simulate_add_pod_to_cache( self, pod_namespace, pod_name ):
        """
        Simulates adding a pod to the cache so that we can populate the
        cache for testing purposes without going through the regular interface
        """
        obj = create_object_from_dict( { 'namespace': pod_namespace, 'name': pod_name } )
        self.__pod_cache._add_to_cache( obj )
