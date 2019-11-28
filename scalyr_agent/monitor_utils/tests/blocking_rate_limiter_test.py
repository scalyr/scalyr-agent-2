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
# author: Edward Chee <echee@scalyr.com>

__author__ = 'echee@scalyr.com'


import threading
from mock import patch
from scalyr_agent.util import FakeClock, StoppableThread
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent.monitor_utils.blocking_rate_limiter import BlockingRateLimiter


def always_true():
    while True:
        yield True

def always_false():
    while True:
        yield False


def rate_maintainer(consecutive_success_threshold, backoff_rate, increase_rate):
    """Returns a generator that maintains the rate at a constant level by balancing failures with successes
    """
    last = True
    consecutive_true = 0
    backoff_increase_ratio = float(backoff_rate) * increase_rate
    required_consecutive_successes = int(consecutive_success_threshold * backoff_increase_ratio)

    while True:
        if last:
            if consecutive_true == required_consecutive_successes:
                last = False
                consecutive_true = 0
            else:
                # stay True
                consecutive_true += 1
        else:
            last = True
            consecutive_true += 1
        yield last


class BlockingRateLimiterTest(ScalyrTestCase):

    def setUp(self):
        super(BlockingRateLimiterTest, self).setUp()
        self._fake_clock = FakeClock()
        self._test_state = {
            'count': 0,
            'times': [],
        }
        self._test_state_lock = threading.Lock()
        self._outcome_generator_lock = threading.Lock()


    def test_init_exceptions(self):
        BRL = BlockingRateLimiter

        # strategy must be restricted to proper values
        self.assertRaises(ValueError, lambda: BRL(
            num_agents=1, initial_cluster_rate=100, max_cluster_rate=1000, min_cluster_rate=1,
            consecutive_success_threshold=5,
            strategy='bad strategy',
        ))

        # max_concurrency must be 1 or more
        self.assertRaises(ValueError, lambda: BRL(
            num_agents=1, initial_cluster_rate=100, max_cluster_rate=1000, min_cluster_rate=1,
            consecutive_success_threshold=5,
            max_concurrency=0,
        ))

        # consecutive_success_threshold must be a positive int
        self.assertRaises(ValueError, lambda: BRL(
            num_agents=1, initial_cluster_rate=100, max_cluster_rate=1000, min_cluster_rate=1,
            consecutive_success_threshold=-5.0,
        ))
        self.assertRaises(ValueError, lambda: BRL(
            num_agents=1, initial_cluster_rate=100, max_cluster_rate=1000, min_cluster_rate=1,
            consecutive_success_threshold=99.99,
        ))

        # user-supplied init must be between user-supplied min/max
        self.assertRaises(ValueError, lambda: BRL(
            num_agents=1, initial_cluster_rate=0.7, max_cluster_rate=1000, min_cluster_rate=1,
            consecutive_success_threshold=5,
        ))
        self.assertRaises(ValueError, lambda: BRL(
            num_agents=1, initial_cluster_rate=7777, max_cluster_rate=1000, min_cluster_rate=1,
            consecutive_success_threshold=5,
        ))

    def test_lazy_adjust_min_max_init_rates(self):
        """Tests the one-time lazy adjustments"""

        # Make sure proper adjustments are made if out of bounds
        BRL = BlockingRateLimiter
        rl = BRL(
            num_agents=1,
            initial_cluster_rate=BRL.HARD_LIMIT_INITIAL_CLUSTER_RATE + 1000,
            max_cluster_rate=BRL.HARD_LIMIT_INITIAL_CLUSTER_RATE + 2000000,
            min_cluster_rate=float(BRL.HARD_LIMIT_MIN_CLUSTER_RATE)/10,
            consecutive_success_threshold=5,
        )
        rl._lazy_adjust_min_max_rates()
        self.assertEqual(rl._initial_cluster_rate, BRL.HARD_LIMIT_INITIAL_CLUSTER_RATE)
        self.assertEqual(rl._max_cluster_rate, BRL.HARD_LIMIT_INITIAL_CLUSTER_RATE + 2000000)
        self.assertEqual(rl._min_cluster_rate, BRL.HARD_LIMIT_MIN_CLUSTER_RATE)

        # Make sure adjustments are NOT made if within bounds
        rl = BRL(
            num_agents=1,
            initial_cluster_rate=BRL.HARD_LIMIT_INITIAL_CLUSTER_RATE - 1,
            max_cluster_rate=BRL.HARD_LIMIT_INITIAL_CLUSTER_RATE - 1,
            min_cluster_rate=float(BRL.HARD_LIMIT_MIN_CLUSTER_RATE) + 1,
            consecutive_success_threshold=5,
        )
        rl._lazy_adjust_min_max_rates()
        self.assertEqual(rl._initial_cluster_rate, BRL.HARD_LIMIT_INITIAL_CLUSTER_RATE - 1)
        self.assertEqual(rl._max_cluster_rate, BRL.HARD_LIMIT_INITIAL_CLUSTER_RATE + -1)
        self.assertEqual(rl._min_cluster_rate, BRL.HARD_LIMIT_MIN_CLUSTER_RATE + 1)

        # Init rate cannot be lower than min rate
        rl = BlockingRateLimiter(
            num_agents=1,
            initial_cluster_rate=0.1,
            max_cluster_rate=1000,
            min_cluster_rate=0,
            consecutive_success_threshold=5,
        )
        rl._lazy_adjust_min_max_rates()
        self.assertEqual(rl._initial_cluster_rate, 1)

    def __create_consumer_threads(self, num_threads, rate_limiter, experiment_end_time, reported_outcome_generator):
        """
        Create a list of client thread that will consume from the rate limiter.
        @param num_threads: Number of client threads
        @param rate_limiter: The rate limiter to test
        @param experiment_end_time: consumer threads terminate their loops when the fake clock has exceeded this.
        @param reported_outcome_generator: Generator to get reported outcome boolean value

        @type rate_limiter: BlockingRateLimiter
        @type threads: iterable of Thread objects
        @type experiment_end_time: int (utc seconds)
        @type reported_outcome_generator: generator

        @returns: list of consumer threads
        @rtype: list(Thread)
        """
        def consume_token_blocking():
            """consumer threads will keep acquiring tokens until experiment end time"""
            while self._fake_clock.time() < experiment_end_time:
                # A simple loop that acquires token, updates a counter, then releases token with an outcome
                # provided by reported_outcome_generator()
                t1 = self._fake_clock.time()
                token = rate_limiter.acquire_token()
                # update test state
                self._test_state_lock.acquire()
                try:
                    self._test_state['count'] += 1
                    self._test_state['times'].append(int(t1))
                finally:
                    self._test_state_lock.release()

                self._outcome_generator_lock.acquire()
                try:
                    outcome = reported_outcome_generator.next()
                    rate_limiter.release_token(token, outcome)
                finally:
                    self._outcome_generator_lock.release()

        return [threading.Thread(target=consume_token_blocking) for _ in range(num_threads)]

    def __create_fake_clock_advancer_thread(self, rate_limiter, consumer_threads):
        """
        Run a separate thread that advances time in order to allow rate_limiter to release tokens
        @param rate_limiter: The rate limiter to test
        @param consumer_threads: Other threads that are consumers of the Rate Limiter.  The advancer thread will run
            for as long as the consumer threads continue to run.

        @type rate_limiter: BlockingRateLimiter
        @type consumer_threads: iterable of Thread objects

        @returns: Thread object
        @rtype: Thread
        """
        class FakeClockAdvancerThread(StoppableThread):

            def __init__(self2):
                StoppableThread.__init__(self2, name='FakeClockAdvancerThread', is_daemon=True)

            def run_and_propagate(self2):
                at_least_one_client_thread_incomplete = True
                while at_least_one_client_thread_incomplete:
                    # All client threads are likely blocking on the token queue at this point
                    # The experiment will never start until at least one token is granted (and waiting threads notified)
                    # To jump start this, simply advance fake clock to the ripe_time.
                    delta = rate_limiter._ripe_time - self._fake_clock.time()
                    self._fake_clock.advance_time(increment_by=delta)
                    # Wake up after 1 second just in case and trigger another advance
                    [t.join(1) for t in consumer_threads]
                    at_least_one_client_thread_incomplete = False
                    for t in consumer_threads:
                        if t.isAlive():
                            at_least_one_client_thread_incomplete = True
                            break

        return FakeClockAdvancerThread()

    def test_rate_adjustment_logic(self):
        """Make sure rate adjustments work according to spec

        The cases we test are:
        1. All successes. Actual rate is very high. New target rate is always increase_factor * current target rate.
        2. All successes. Actual rate is very low. New target rate is always increase_factor * actual rate,
            (but no lower than current rate).
        3. All failures. Actual rate is very low. New target rate is always backoff_factor * current target rate.
        4. All failures. Actual rate is very high. New target rate is always backoff_factor * actual rate.
            (but no higher than current rate).
        """
        required_successes = 5
        max_cluster_rate = 10000
        min_cluster_rate = 1
        initial_cluster_rate = 100
        increase_factor = 2.0
        backoff_factor = 0.5

        def _create_rate_limiter():
            return BlockingRateLimiter(
                num_agents=1,
                initial_cluster_rate=initial_cluster_rate,
                max_cluster_rate=max_cluster_rate,
                min_cluster_rate=min_cluster_rate,
                consecutive_success_threshold=required_successes,
                strategy=BlockingRateLimiter.STRATEGY_MULTIPLY,
                increase_factor=increase_factor,
                backoff_factor=backoff_factor,
                max_concurrency=1,
                fake_clock=self._fake_clock
            )

        def _mock_get_next_ripe_time_actual_rate_leads(rate_limiter):
            # Make the rate limiter grant tokens faster than the target rate
            def _func(*args, **kwargs):
                delta = 1.0 / rate_limiter._current_cluster_rate
                return rl._ripe_time + 0.9 * delta
            return _func

        def _mock_get_next_ripe_time_actual_rate_lags(rate_limiter):
            # Make the rate limiter grant tokens slower than the target rate
            def _func(*args, **kwargs):
                delta = 1.0 / rate_limiter._current_cluster_rate
                return rl._ripe_time + 1.1 * delta
            return _func

        rl = _create_rate_limiter()
        @patch.object(rl, '_get_next_ripe_time')
        def _case1_test_successes_actual_rate_leads_target_rate(mock_get_next_ripe_time):
            """Examine rate-increasing behavior in the context of very high actual rates"""
            mock_get_next_ripe_time.side_effect = _mock_get_next_ripe_time_actual_rate_leads(rl)

            advancer = self.__create_fake_clock_advancer_thread(rl, [threading.currentThread()])
            advancer.start()

            while True:
                token = rl.acquire_token()
                for x in range(required_successes-1):
                    rl.release_token(token, True)
                    rl.acquire_token()

                # Actual rate always leads target rate
                old_target_rate = rl._current_cluster_rate
                old_actual_rate = rl._get_actual_cluster_rate()
                self.assertGreater(old_actual_rate, old_target_rate)

                # Token grant causes new rate to be calculated
                rl.release_token(token, True)

                # assert that the new rate is calculated based on the (lower/more conservative) target rate
                if increase_factor * old_target_rate < max_cluster_rate:
                    self.assertEqual(rl._current_cluster_rate, increase_factor * old_target_rate)
                else:
                    # assert that new rate never exceeds max rate
                    self.assertEqual(rl._current_cluster_rate, max_cluster_rate)
                    break
            advancer.stop(wait_on_join=False)

        _case1_test_successes_actual_rate_leads_target_rate()

        rl = _create_rate_limiter()
        @patch.object(rl, '_get_next_ripe_time')
        def _case2_test_successes_actual_rate_lags_target_rate(mock_get_next_ripe_time):
            """Examine rate-increasing behavior in the context of very high actual rates"""
            mock_get_next_ripe_time.side_effect = _mock_get_next_ripe_time_actual_rate_lags(rl)

            advancer = self.__create_fake_clock_advancer_thread(rl, [threading.currentThread()])
            advancer.start()

            while True:
                token = rl.acquire_token()
                for x in range(required_successes - 1):
                    rl.release_token(token, True)
                    rl.acquire_token()

                # Actual rate always lags target rate
                old_target_rate = rl._current_cluster_rate
                old_actual_rate = rl._get_actual_cluster_rate()
                self.assertLess(old_actual_rate, old_target_rate)

                # Token grant causes new rate to be calculated
                rl.release_token(token, True)

                # assert that the new rate is calculated based on the (lower/more conservative) actual rate
                if increase_factor * old_actual_rate < max_cluster_rate:
                    if increase_factor * old_actual_rate < old_target_rate:
                        self.assertEqual(round(rl._current_cluster_rate, 2),
                                         round(old_target_rate, 2))
                    else:
                        self.assertEqual(round(rl._current_cluster_rate, 2),
                                         round(increase_factor * old_actual_rate, 2))
                else:
                    # assert that new rate never exceeds max rate
                    self.assertEqual(rl._current_cluster_rate, max_cluster_rate)
                    break
            advancer.stop(wait_on_join=False)

        _case2_test_successes_actual_rate_lags_target_rate()

        rl = _create_rate_limiter()
        @patch.object(rl, '_get_next_ripe_time')
        def _case3_test_failures_actual_rate_lags_target_rate(mock_get_next_ripe_time):
            """Examine rate-decreasing behavior in the context of very high actual rates"""
            mock_get_next_ripe_time.side_effect = _mock_get_next_ripe_time_actual_rate_lags(rl)

            advancer = self.__create_fake_clock_advancer_thread(rl, [threading.currentThread()])
            advancer.start()

            counter = 0
            while True:
                token = rl.acquire_token()

                # Actual rate always lags target rate
                old_target_rate = rl._current_cluster_rate
                old_actual_rate = rl._get_actual_cluster_rate()
                if old_actual_rate is not None:
                    self.assertLess(old_actual_rate, old_target_rate)

                # Token grant a 100 initial successes followed by all failures
                counter += 1
                if counter <= required_successes:
                    rl.release_token(token, True)
                    continue
                else:
                    rl.release_token(token, False)

                # assert that the new rate is calculated based on the (higher/more conservative) target rate
                if backoff_factor * old_target_rate > min_cluster_rate:
                    self.assertEqual(round(rl._current_cluster_rate, 2),
                                     round(backoff_factor * old_target_rate, 2))
                else:
                    # assert that new rate never goes lower than min rate
                    self.assertEqual(round(rl._current_cluster_rate, 2),
                                     round(min_cluster_rate, 2))
                    break
            advancer.stop(wait_on_join=False)

        _case3_test_failures_actual_rate_lags_target_rate()

        rl = _create_rate_limiter()
        @patch.object(rl, '_get_next_ripe_time')
        def _case4_test_failures_actual_rate_leads_target_rate(mock_get_next_ripe_time):
            """Examine rate-decreasing behavior in the context of very high actual rates"""
            mock_get_next_ripe_time.side_effect = _mock_get_next_ripe_time_actual_rate_leads(rl)

            advancer = self.__create_fake_clock_advancer_thread(rl, [threading.currentThread()])
            advancer.start()

            counter = 0
            while True:
                token = rl.acquire_token()

                # Actual rate is always None because
                old_target_rate = rl._current_cluster_rate
                old_actual_rate = rl._get_actual_cluster_rate()
                if old_actual_rate is not None:
                    self.assertGreater(old_actual_rate, old_target_rate)

                # Token grant a 100 initial successes followed by all failures
                counter += 1
                if counter <= required_successes:
                    rl.release_token(token, True)
                    continue
                else:
                    rl.release_token(token, False)

                # assert that the new rate is calculated based on the (higher/more conservative) actual rate
                if backoff_factor * old_target_rate > min_cluster_rate:
                    self.assertEqual(round(rl._current_cluster_rate, 2),
                                     round(backoff_factor * old_target_rate, 2))
                else:
                    # assert that new rate never goes lower than min rate
                    self.assertEqual(rl._current_cluster_rate, min_cluster_rate)
                    break
            advancer.stop(wait_on_join=False)

        _case4_test_failures_actual_rate_leads_target_rate()

    def test_fixed_rate_single_concurrency(self):
        """Longer experiment"""
        # 1 rps x 1000 simulated seconds => 1000 increments
        self._test_fixed_rate(desired_agent_rate=1.0, experiment_duration=10000, concurrency=1, expected_requests=10000,
                              allowed_variance=(0.95, 1.05))

    def test_fixed_rate_multiple_concurrency(self):
        """Multiple clients should not affect overall rate"""
        # 1 rps x 100 simulated seconds => 100 increments
        # Higher concurrency has more variance
        self._test_fixed_rate(desired_agent_rate=1.0, experiment_duration=10000, concurrency=3, expected_requests=10000,
                              allowed_variance=(0.8, 1.2))

    def _test_fixed_rate(self, desired_agent_rate, experiment_duration, concurrency, expected_requests, allowed_variance):
        """A utility pass-through that fixes the initial, upper and lower rates"""
        num_agents = 1000
        cluster_rate = num_agents * desired_agent_rate
        self._test_rate_limiter(
            num_agents=num_agents,
            initial_cluster_rate=cluster_rate, max_cluster_rate=cluster_rate, min_cluster_rate=cluster_rate,
            consecutive_success_threshold=5, experiment_duration=experiment_duration, max_concurrency=concurrency,
            expected_requests=expected_requests, allowed_variance=allowed_variance
        )

    def test_variable_rate_single_concurrency_all_successes(self):
        """Rate should quickly max out at max_cluster_rate"""

        # Test variables
        initial_agent_rate = 1
        experiment_duration = 1000
        concurrency = 1
        max_rate_multiplier = 10

        # Expected behavior (saturates at upper rate given all successes)
        expected_requests = max_rate_multiplier * experiment_duration
        allowed_variance = (0.8, 1.2)

        # Derived values
        num_agents = 10
        initial_cluster_rate = num_agents * initial_agent_rate
        max_cluster_rate = max_rate_multiplier * initial_cluster_rate

        self._test_rate_limiter(
            num_agents=10,
            initial_cluster_rate=initial_cluster_rate, max_cluster_rate=max_cluster_rate, min_cluster_rate=0,
            experiment_duration=experiment_duration, max_concurrency=concurrency,
            consecutive_success_threshold=5, increase_strategy=BlockingRateLimiter.STRATEGY_RESET_THEN_MULTIPLY,
            expected_requests=expected_requests, allowed_variance=allowed_variance,
        )

    def test_variable_rate_single_concurrency_all_failures(self):
        """Rate should quickly decrease to min_cluster_rate"""

        # temporarily disable hard lower limit as it is irrelevant to this test and we want to let it go down to really
        # low numbers to gather enough data.
        orig_hard_limit = BlockingRateLimiter.HARD_LIMIT_MIN_CLUSTER_RATE
        BlockingRateLimiter.HARD_LIMIT_MIN_CLUSTER_RATE = -float('inf')

        # Test variables
        initial_agent_rate = 1
        experiment_duration = 1000000
        concurrency = 1
        min_rate_multiplier = 0.01  # min rate should be at least an order of magnitude lower than initial rate.

        # Expected behavior
        expected_requests = min_rate_multiplier * experiment_duration
        allowed_variance = (0.8, 1.2)

        # Derived values
        num_agents = 10
        initial_cluster_rate = num_agents * initial_agent_rate
        max_cluster_rate = initial_cluster_rate
        min_cluster_rate = min_rate_multiplier * initial_cluster_rate

        self._test_rate_limiter(
            num_agents=num_agents,
            initial_cluster_rate=initial_cluster_rate,
            max_cluster_rate=max_cluster_rate,
            min_cluster_rate=min_cluster_rate,
            experiment_duration=experiment_duration,
            max_concurrency=concurrency,
            consecutive_success_threshold=5,
            increase_strategy=BlockingRateLimiter.STRATEGY_RESET_THEN_MULTIPLY,
            expected_requests=expected_requests,
            allowed_variance=allowed_variance,
            reported_outcome_generator=always_false(),
        )

        # Restore the min hard limit
        BlockingRateLimiter.HARD_LIMIT_MIN_CLUSTER_RATE = orig_hard_limit

    def test_variable_rate_single_concurrency_push_pull(self):
        """Rate should fluctuate closely around initial rate because of equal successes/failures"""

        # Test variables
        initial_agent_rate = 1
        experiment_duration = 10000
        concurrency = 1
        min_rate_multiplier = 0.1
        max_rate_multiplier = 10
        consecutive_success_threshold = 5
        backoff_factor = 0.5
        increase_factor = 2.0

        # Expected behavior
        # 1 * 1 rps * 100s
        expected_requests = 1 * experiment_duration
        allowed_variance = (0.8, 1.2)  # variance increases as difference between backoffs increase

        # Derived values
        num_agents = 100
        initial_cluster_rate = num_agents * initial_agent_rate

        self._test_rate_limiter(
            num_agents=num_agents,
            initial_cluster_rate=initial_cluster_rate,
            max_cluster_rate=max_rate_multiplier * initial_cluster_rate,
            min_cluster_rate=min_rate_multiplier * initial_cluster_rate,
            experiment_duration=experiment_duration,
            max_concurrency=concurrency,
            consecutive_success_threshold=consecutive_success_threshold,
            increase_strategy=BlockingRateLimiter.STRATEGY_RESET_THEN_MULTIPLY,
            expected_requests=expected_requests,
            allowed_variance=allowed_variance,
            reported_outcome_generator=rate_maintainer(consecutive_success_threshold, backoff_factor, increase_factor),
            backoff_factor=backoff_factor,
            increase_factor=increase_factor,
        )

    def _test_rate_limiter(
            self, num_agents, consecutive_success_threshold, initial_cluster_rate, max_cluster_rate, min_cluster_rate,
            experiment_duration, max_concurrency, expected_requests, allowed_variance,
            reported_outcome_generator=always_true(),
            increase_strategy=BlockingRateLimiter.STRATEGY_MULTIPLY,
            backoff_factor=0.5, increase_factor=2.0,
    ):
        """Main test logic that runs max_concurrency client threads for a defined experiment duration.

        The experiment is driven off a fake_clock (so it can complete in seconds, not minutes or hours).

        Each time a successful acquire() completes, a counter is incremented.  At experiment end, this counter
        should be close enough to a calculated expected value, based on the specified rate.

        Concurrency should not affect the overall rate of allowed acquisitions.

        The reported outcome by acquiring clients is determined by invoking the callable `reported_outcome_callable`.


        @param num_agents: Num agents in cluster (to derive agent rate from cluster rate)
        @param consecutive_success_threshold:
        @param initial_cluster_rate: Initial cluster rate
        @param max_cluster_rate:  Upper bound on cluster rate
        @param min_cluster_rate: Lower bound on cluster rate
        @param increase_strategy: Strategy for increasing rate
        @param experiment_duration: Experiment duration in seconds
        @param max_concurrency: Number of tokens to create
        @param expected_requests: Expected number of requests at the end of experiment
        @param allowed_variance: Allowed variance between expected and actual number of requests. (e.g. 0.1 = 10%)
        @param reported_outcome_generator: Generator to get reported outcome boolean value
        @param fake_clock_increment: Fake clock increment by (seconds)
        """
        rate_limiter = BlockingRateLimiter(
            num_agents=num_agents,
            initial_cluster_rate=initial_cluster_rate,
            max_cluster_rate=max_cluster_rate,
            min_cluster_rate=min_cluster_rate,
            consecutive_success_threshold=consecutive_success_threshold,
            strategy=increase_strategy,
            increase_factor=increase_factor,
            backoff_factor=backoff_factor,
            max_concurrency=max_concurrency,
            fake_clock=self._fake_clock,
        )

        # Create and start a list of consumer threads
        experiment_end_time = self._fake_clock.time() + experiment_duration
        threads = self.__create_consumer_threads(max_concurrency, rate_limiter, experiment_end_time,
                                                 reported_outcome_generator)
        [t.setDaemon(True) for t in threads]
        [t.start() for t in threads]

        # Create and join and advancer thread (which in turn lasts until all client threads die
        advancer = self.__create_fake_clock_advancer_thread(rate_limiter, threads)
        advancer.start()
        advancer.join()

        requests = self._test_state['count']
        # Assert that count is close enough to the expected count
        observed_ratio = float(requests) / expected_requests
        self.assertGreater(observed_ratio, allowed_variance[0])
        self.assertLess(observed_ratio, allowed_variance[1])
