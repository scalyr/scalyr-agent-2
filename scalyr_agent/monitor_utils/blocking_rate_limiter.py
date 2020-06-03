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

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "echee@scalyr.com"

if False:  # NOSONAR
    from typing import Dict

import random
import threading
import time
from collections import deque

from six.moves import range

import scalyr_agent.scalyr_logging as scalyr_logging


MULTIPLY = "multiply"
RESET_THE_MULTIPLY = "reset_then_multiply"


class RateLimiterToken(object):
    def __init__(self, token_id):
        self._token_id = token_id

    @property
    def token_id(self):
        """Integer ID"""
        return self._token_id

    def __repr__(self):
        return "Token #%s" % self._token_id


class BlockingRateLimiter(object):
    """A Rate Limiter that blocks for a random time interval such that over time, the average rate of acquire() calls
    is R where R varies between a max upper and min lower bound. R is a "cluster" rate where the semantics are
    each of num_agents Scalyr Agents instantiates one of these rate limiters such that the aggregate access rate over
    all agents is R.  (Therefore, the per-agent rate is R / num_agents).

    Whenever a certain number of consecutive successes are seen, the rate is increased up until max_cluster_rate.
    Likewise, whenever a failure is reported (on token release()), the rate is lowered up until a min_cluster_rate.
    Cluster rate is reduced by dividing current rate by backoff_factor.  Cluster rate is increased either by
    multiplying by increase_factor or resetting to initial rate, depending on the strategy.
    (Note: if cluster rate is already greater or equal to initial rate, it will be multiplied by the increase factor)
    """

    STRATEGY_MULTIPLY = MULTIPLY
    STRATEGY_RESET_THEN_MULTIPLY = RESET_THE_MULTIPLY

    # Hard limit to protect against user error.
    # With 5K agents, each agent will start off at 4rps.
    # With 1 agent, the agent will start off at 20K rps.
    # Note: we do not specify an upper bound to allow the rate limiter to push the boundaries.
    HARD_LIMIT_INITIAL_CLUSTER_RATE = 20000

    HARD_LIMIT_MIN_CLUSTER_RATE = 1

    registry = {}  # type: Dict[str, BlockingRateLimiter]
    registry_lock = threading.Lock()

    def __repr__(self):
        return "%s/%s" % (self.__class__.__name__, self._name)

    @classmethod
    def get_instance(cls, key, global_config, logger=None):
        """Returned a named instance of a rate limiter so that it can be shared by multiple threads/code areas

        If a named instance does not exist, create one, based on the global configuration settings.
        """
        cls.registry_lock.acquire()
        try:
            if key not in cls.registry:
                cls.registry[key] = BlockingRateLimiter(
                    global_config.k8s_ratelimit_cluster_num_agents,
                    global_config.k8s_ratelimit_cluster_rps_init,
                    global_config.k8s_ratelimit_cluster_rps_max,
                    global_config.k8s_ratelimit_cluster_rps_min,
                    global_config.k8s_ratelimit_consecutive_increase_threshold,
                    global_config.k8s_ratelimit_strategy,
                    global_config.k8s_ratelimit_increase_factor,
                    global_config.k8s_ratelimit_backoff_factor,
                    global_config.k8s_ratelimit_max_concurrency,
                    logger=logger,
                    name=key,
                )
            return cls.registry[key]
        finally:
            cls.registry_lock.release()

    def __init__(
        self,
        num_agents,
        initial_cluster_rate,
        max_cluster_rate,
        min_cluster_rate,
        consecutive_success_threshold,
        strategy=MULTIPLY,
        increase_factor=2.0,
        backoff_factor=0.5,
        max_concurrency=1,
        logger=None,
        fake_clock=None,
        name=None,
    ):
        """
        @param num_agents: Number of agents in the cluster
        @param initial_cluster_rate: initial cluster rate (requests/sec)
        @param max_cluster_rate: upper bound on cluster rate (requests/sec)
        @param min_cluster_rate: lower bound on cluster rate (requests/sec)
        @param consecutive_success_threshold: number of consecutive successes to trigger a rate increase
        @param strategy: strategy for changing rate (multiply or reset-then-multiply)
        @param increase_factor: multiplicative factor for increasing rate
        @param backoff_factor: multiplicative factor for decreasing rate
        @param max_concurrency: max number of tokens (for limiting concurrent requests) that can be acquired
        @param logger: If supplied, will log messages for debugging
        @parm name: Name string for identification purposes (optional)

        @type num_agents: int
        @type initial_cluster_rate: float
        @type max_cluster_rate: float
        @type min_cluster_rate: float
        @type consecutive_success_threshold: int
        @type strategy: six.text_type
        @type increase_factor: float
        @type backoff_factor: float
        @type max_concurrency: int
        @type logger: Logger
        @type name: six.text_type
        """
        # Validate input (Note: will raise exception and thus kill the agent process if invalid)
        strategies = [self.STRATEGY_MULTIPLY, self.STRATEGY_RESET_THEN_MULTIPLY]
        if strategy not in strategies:
            raise ValueError("Increase strategy must be one of %s" % strategies)

        if max_concurrency < 1:
            raise ValueError("max_concurrency must be greater than 0")

        if consecutive_success_threshold < 1:
            raise ValueError(
                "consecutive_success_threshold must be a positive int. Value=%s"
                % consecutive_success_threshold
            )

        if int(consecutive_success_threshold) != consecutive_success_threshold:
            raise ValueError(
                "consecutive_success_threshold must be a positive int. Value=%s"
                % consecutive_success_threshold
            )

        if (
            initial_cluster_rate < min_cluster_rate
            or initial_cluster_rate > max_cluster_rate
        ):
            raise ValueError(
                "Initial cluster rate must be between lower and upper rates. Initial=%s, Lower=%s, Upper=%s."
                % (initial_cluster_rate, min_cluster_rate, max_cluster_rate)
            )

        self._logger = logger
        self._num_agents = num_agents
        self._initial_cluster_rate = initial_cluster_rate

        self._max_cluster_rate = max_cluster_rate
        self._min_cluster_rate = min_cluster_rate
        # A flag that when set to True signifies that a one-time adjustment has been made to min/max
        # cluster rates.  This is needed to avoid repeat warning messages being logged every time
        # __init__ is called on a redundant instance of this class (e.g. when created by k8s_monitor_initialize()
        self._lazy_adjusted = False

        self._consecutive_success_threshold = consecutive_success_threshold
        self._strategy = strategy
        self._increase_factor = increase_factor
        self._backoff_factor = backoff_factor

        # target cluster rate
        self._current_cluster_rate = self._initial_cluster_rate
        self._consecutive_successes = 0
        # state for tracking actual rate
        self._first_action_time = None
        self._last_action_time = None
        self._num_actions = 0
        # lock for protecting all the above state for cluster & actual rates
        self._cluster_rate_lock = threading.RLock()

        self._max_concurrency = max_concurrency

        self._name = name

        # A queue of tokens
        # 2->TODO python3 does not allow None in sort. There is sort in 'self._initialize_token_queue()'
        self._ripe_time = 0.0
        self._token_queue = deque()
        # Condition variable to synchronize access to token queue
        self._token_queue_cv = threading.Condition()

        # fake clock for testing
        self._fake_clock = fake_clock
        self._test_mode_lock = threading.Lock()

        self._initialize_token_queue()

    def _lazy_adjust_min_max_rates(self):
        """Adjust min/max cluster rates to hard limits"""

        self._cluster_rate_lock.acquire()
        try:
            if self._lazy_adjusted:
                return

            if self._initial_cluster_rate > self.HARD_LIMIT_INITIAL_CLUSTER_RATE:
                old_initial_cluster_rate = self._initial_cluster_rate
                self._initial_cluster_rate = self.HARD_LIMIT_INITIAL_CLUSTER_RATE
                if self._logger:
                    self._logger.warn(
                        "RateLimiter: initial cluster rate of %.2f is too high.  Limiting to %.2f."
                        % (old_initial_cluster_rate, self._initial_cluster_rate)
                    )
            if self._min_cluster_rate < self.HARD_LIMIT_MIN_CLUSTER_RATE:
                old_min_cluster_rate = self._min_cluster_rate
                self._min_cluster_rate = self.HARD_LIMIT_MIN_CLUSTER_RATE
                if self._logger:
                    self._logger.warn(
                        "RateLimiter: min cluster rate of %.2f is too low.  Increasing to %.2f."
                        % (old_min_cluster_rate, self._min_cluster_rate)
                    )
            if self._initial_cluster_rate < self._min_cluster_rate:
                old_initial_cluster_rate = self._initial_cluster_rate
                self._initial_cluster_rate = self._min_cluster_rate
                self._current_cluster_rate = self._initial_cluster_rate
                if self._logger:
                    self._logger.warn(
                        "RateLimiter: initial cluster rate of %.2f is too low.  Increasing to %.2f."
                        % (old_initial_cluster_rate, self._initial_cluster_rate)
                    )
            self._lazy_adjusted = True
        finally:
            self._cluster_rate_lock.release()

    def _get_actual_cluster_rate(self):
        """Calculate actual rate based on recorded actions.  If fewer than 2 actions, returns None
        """
        self._cluster_rate_lock.acquire()
        try:
            if self._num_actions < 2:
                return None
            rate = (
                float(self._num_actions - 1)
                * self._num_agents
                / (self._last_action_time - self._first_action_time)
            )
            return rate
        finally:
            self._cluster_rate_lock.release()

    def _record_actual_rate(self):
        """Record a completed action in order to keep track of actual rate
        """
        self._cluster_rate_lock.acquire()
        try:
            t = self._time()
            self._num_actions += 1
            if self._num_actions == 1:
                self._first_action_time = t
            self._last_action_time = t
        finally:
            self._cluster_rate_lock.release()

    def _reset_actual_rate(self):
        """Reset actual rate state"""
        self._cluster_rate_lock.acquire()
        try:
            self._num_actions = 0
            self._first_action_time = None
            self._last_action_time = None
        finally:
            self._cluster_rate_lock.release()

    @property
    def name(self):
        return self._name

    @property
    def current_cluster_rate(self):
        return self._current_cluster_rate

    @property
    def current_agent_rate(self):
        return float(self._current_cluster_rate) / self._num_agents

    def _initialize_token_queue(self):
        """Initialize a queue with max_concurrency tokens."""
        self._token_queue_cv.acquire()
        for num in range(self._max_concurrency):
            token = RateLimiterToken(num)
            self._token_queue.append(token)
        self._ripe_time = self._get_next_ripe_time()
        self._token_queue_cv.release()

    def _increase_cluster_rate(self):
        """Increase cluster rate but no higher than configured max and no lower than current cluster rate.

        If actual rate was calculated, then the new rate is calculated off the lower of actual & current target rate.
        Otherwise, new rate is calculated off the existing target rate.

        Note: this method is not thread-safe. Callers should pre-acquire cluster_rate_lock.
        """
        current_target_rate = self._current_cluster_rate

        actual_rate = self._get_actual_cluster_rate()
        if actual_rate is not None:
            # new rate should be based off the lower of actual & target rates
            new_rate = min(actual_rate, current_target_rate) * self._increase_factor
        else:
            new_rate = current_target_rate * self._increase_factor

        # new rate cannot be higher than configured higher bound
        new_rate = min(new_rate, self._max_cluster_rate)

        # new rate cannot be lower than existing rate (which may happen if actual rate was really low)
        new_rate = max(new_rate, current_target_rate)

        self._current_cluster_rate = new_rate

        if self._logger:
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_3,
                "RateLimiter: increase cluster rate %s (%s) x %s -> %s"
                % (current_target_rate, actual_rate, self._increase_factor, new_rate),
            )

        self._reset_actual_rate()

    def _decrease_cluster_rate(self):
        """Decrease cluster rate but no lower than configured min and no higher than current cluster rate.

        If actual rate was calculated, then the new rate is calculated off the higher of actual & current target rate.
        Otherwise, new rate is calculated off the existing target rate.

        Note: this method is not thread-safe. Callers should pre-acquire cluster_rate_lock.
        """
        current_target_rate = self._current_cluster_rate

        actual_rate = self._get_actual_cluster_rate()
        if actual_rate is not None:
            # new rate should be based off the higher of actual & target rates
            new_rate = max(actual_rate, current_target_rate) * self._backoff_factor
        else:
            new_rate = current_target_rate * self._backoff_factor

        # new rate cannot be lower than configured lower bound
        new_rate = max(new_rate, self._min_cluster_rate)

        # new rate cannot be higher than existing rate (which may happen if actual rate was really high)
        new_rate = min(new_rate, current_target_rate)

        self._current_cluster_rate = new_rate

        if self._logger:
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_3,
                "RateLimiter: decrease cluster rate %s (%s) x %s -> %s"
                % (current_target_rate, actual_rate, self._backoff_factor, new_rate),
            )
        self._reset_actual_rate()

    def _adjust_cluster_rate(self, success):
        """Adjust cluster rate, backing off on failure or increasing on enough consecutive successes.

        Any failure will cause backoff.
        A success will accumulate until self._consecutive_success_threshold is reached, at which point the rate will be
            increased according to self._increase_strategy.  When this happens, the success accumulator resets to 0

        @param success: Whether an operation was successful
        @type success: bool
        """
        self._cluster_rate_lock.acquire()
        try:
            if success:
                # Success case: If current rate can be increased, do so based on strategy
                self._consecutive_successes += 1

                # not enough consecutive successes
                if self._consecutive_successes < self._consecutive_success_threshold:
                    return

                self._consecutive_successes = 0
                if self._current_cluster_rate < self._max_cluster_rate:
                    if self._strategy == self.STRATEGY_RESET_THEN_MULTIPLY:
                        if self._current_cluster_rate < self._initial_cluster_rate:
                            self._current_cluster_rate = self._initial_cluster_rate
                        else:
                            self._increase_cluster_rate()
                    else:
                        self._increase_cluster_rate()
            else:
                # Failure case: backoff
                self._consecutive_successes = 0

                # currently, a single failure will cause backoff
                if self._current_cluster_rate > self._min_cluster_rate:
                    if self._strategy == self.STRATEGY_RESET_THEN_MULTIPLY:
                        if self._current_cluster_rate > self._initial_cluster_rate:
                            self._current_cluster_rate = self._initial_cluster_rate
                        else:
                            self._decrease_cluster_rate()
                    else:
                        self._decrease_cluster_rate()
        finally:
            self._cluster_rate_lock.release()

    def _get_next_ripe_time(self):
        """Get the absolute time for when this token becomes next available

        A token contains state representing the last time it was acquired.
        In order to achieve a uniform cluster-wide average rate of R, the next time is calculated as:

        current_time + delta

        where delta = random number between (0, 2 * T)
        where T is the per-agent interval or num_agents / cluster rate
        """
        agent_interval = float(self._num_agents) / self._current_cluster_rate
        delta = random.uniform(0, 2 * agent_interval)
        next_ripe = max(self._ripe_time, self._time()) + delta
        return next_ripe

    def _time(self):
        """Returns absolute time in UTC epoch seconds"""
        if self._fake_clock:
            return self._fake_clock.time()
        else:
            return time.time()

    def _simulate_acquire_token(self):
        self._test_mode_lock.acquire()
        try:
            while len(self._token_queue) == 0 or self._time() < self._ripe_time:
                self._test_mode_lock.release()
                self._fake_clock.simulate_waiting()
                self._test_mode_lock.acquire()

            # Head token is ripe
            token = self._token_queue.popleft()
            self._ripe_time = self._get_next_ripe_time()
            return token
        finally:
            self._test_mode_lock.release()

    def _simulate_release_token(self, token, success):
        self._adjust_cluster_rate(success)
        self._test_mode_lock.acquire()
        try:
            self._token_queue.append(token)
        finally:
            self._test_mode_lock.release()
        self._fake_clock.advance_time(
            increment_by=self._ripe_time - self._fake_clock.time()
        )

    def acquire_token(self):
        """Acquires a token, blocking until a token becomes available.

        The primary state used to determine token availability is self._ripe_time. Until that time is reached,
        all client threads are blocked.

        @return: a token object
        @rtype: RateLimiterToken
        """
        self._lazy_adjust_min_max_rates()

        if self._fake_clock:
            return self._simulate_acquire_token()

        # block until a token is available from the token heap
        if self._logger:
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_5,
                "[%s] RateLimiter.acquire_token : acquire()    "
                % threading.current_thread().name,
            )
        self._token_queue_cv.acquire()

        try:
            while len(self._token_queue) == 0 or self._time() < self._ripe_time:
                # no tokens available so sleep for a while
                if len(self._token_queue) == 0:
                    # queue contained no tokens so wait indefinitely
                    if self._logger:
                        self._logger.log(
                            scalyr_logging.DEBUG_LEVEL_5,
                            "[%s] RateLimiter.acquire_token : wait()"
                            % threading.current_thread().name,
                        )
                    self._token_queue_cv.wait()
                else:
                    # queue contained at least one token so sleep until the head token becomes ripe
                    sleep_time = max(0, self._ripe_time - self._time())
                    if sleep_time > 0:
                        if self._logger:
                            self._logger.log(
                                scalyr_logging.DEBUG_LEVEL_5,
                                "[%s] RateLimiter.acquire_token : wait(%s)"
                                % (threading.current_thread().name, sleep_time),
                            )
                        self._token_queue_cv.wait(sleep_time)

            # Head token is ripe.
            token = self._token_queue.popleft()
            if self._logger:
                self._logger.log(
                    scalyr_logging.DEBUG_LEVEL_5,
                    "[%s] RateLimiter grant token %s at %.2f"
                    % (threading.current_thread().name, token, self._time()),
                )
            self._ripe_time = self._get_next_ripe_time()

            if self._logger:
                self._logger.log(
                    scalyr_logging.DEBUG_LEVEL_5,
                    "[%s] RateLimiter.acquire_token : returning token %s"
                    % (threading.current_thread().name, token),
                )
            return token

        finally:
            self._token_queue_cv.release()

    def release_token(self, token, success):
        """Release a token back to the rate limiter.  Adjusts the rate based on success/failure and then re-inserts
        token back into the queue

        @param token: Token to release
        @param success: Whether or not the client operation was successful

        @type token: RateLimiterToken
        @type success: bool
        """
        if not isinstance(token, RateLimiterToken):
            raise TypeError(
                "Rate limiting token must be of type %s" % type(RateLimiterToken)
            )

        self._record_actual_rate()

        if self._fake_clock:
            return self._simulate_release_token(token, success)

        if self._logger:
            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_5,
                "[%s] RateLimiter.release_token : before acquire"
                % threading.current_thread().name,
            )
        self._token_queue_cv.acquire()

        try:
            # potentially adjust rate depending on reported outcome
            self._adjust_cluster_rate(success)

            # re-insert token
            self._token_queue.append(token)

            # awaken threads waiting for tokens
            if self._logger:
                self._logger.log(
                    scalyr_logging.DEBUG_LEVEL_5,
                    "[%s] RateLimiter.release_token : notifyAll()"
                    % threading.current_thread().name,
                )
            self._token_queue_cv.notifyAll()

        finally:
            self._token_queue_cv.release()
