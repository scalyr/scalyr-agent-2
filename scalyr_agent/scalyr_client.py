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
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import httplib
import platform
import re
import socket
import sys
import time

# noinspection PyBroadException
try:
    import ssl
    __has_ssl__ = True
except Exception:
    __has_ssl__ = False
    ssl = None

try:
    import bz2
except Exception:
    bz2 = None

try:
    import zlib
except Exception:
    zlib = None

import scalyr_agent.json_lib as json_lib
import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util
from scalyr_agent.connection import ConnectionFactory

from cStringIO import StringIO

log = scalyr_logging.getLogger(__name__)

class ScalyrClientSession(object):
    """Encapsulates the connection between the agent and the Scalyr servers.

    It is a session in that we generally only have one connection open to the Scalyr servers at any given time.
    The session aspect is important because we must ensure that the timestamps we include in the AddEventRequests
    are monotonically increasing within a session.
    """
    def __init__(self, server, api_key, agent_version, quiet=False, request_deadline=60.0, ca_file=None, use_requests_lib=False,
                 proxies=None, compression_type=None, compression_level=9, disable_send_requests=False):
        """Initializes the connection.

        This does not actually try to connect to the server.
        @param server: The URL for the server to send requests to, such as https://agent.scalyr.com
        @param api_key: The write logs key to use to authenticate all requests from this agent to scalyr.
            It both authenticates the requests and identifies which account it belongs to.
        @param agent_version: The agent version number, which is included in request headers sent to the server.
        @param quiet: If True, will not log non-error information.
        @param request_deadline: The maximum time to wait for all requests in seconds.
        @param ca_file: The path to the file containing the certificates for the trusted certificate authority roots.
            This is used for the SSL connections to verify the connection is to Scalyr.
        @param proxies:  A dict describing the network proxies to use (such as a mapping for `https`) or None.
        @param compression_type:  A string containing the compression method to use.
            Valid options are bz2, deflate or None.  Defaults to None.
        @param compression_level: An int containing the compression level of compression to use, from 1-9.  Defaults to 9 (max)

        @type server: str
        @type api_key: str
        @type agent_version: str
        @type quiet: bool
        @type request_deadline: float
        @type ca_file: str
        @type proxies: dict
        @type compression_type: str
        @type compression_level: int
        """
        if not quiet:
            log.info('Using "%s" as address for scalyr servers' % server)

        # The full URL address
        self.__full_address = server

        # Verify the server address looks right.
        parsed_server = re.match('^(http://|https://|)([^:]*)(:\d+|)$', server.lower())

        if parsed_server is None:
            raise Exception('Could not parse server address "%s"' % server)


        # The Connection object that has been opened to the servers, if one has been opened.
        self.__connection = None
        self.__use_requests = use_requests_lib
        self.__api_key = api_key
        self.__session_id = scalyr_util.create_unique_id()
        self.__quiet = quiet

        if not quiet:
            log.info('Using session_id=%s %s' % (self.__session_id, scalyr_util.get_pid_tid()))

        # The time of the last success.
        self.__last_success = None
        # The version number of the installed agent
        self.__agent_version = agent_version

        # The last time the connection was closed, if any.
        self.__last_connection_close = None

        # We create a few headers ahead of time so that we don't have to recreate them each time we need them.
        self.__standard_headers = {
            'Connection': 'Keep-Alive',
            'Accept': 'application/json',
            'User-Agent': ScalyrClientSession.__get_user_agent(agent_version)
        }

        # Configure compression type
        self.__compress = None
        encoding = None

        if compression_type:
            if compression_type == 'deflate' and zlib:
                self.__compress = zlib.compress
                encoding = 'deflate'
            elif compression_type == 'bz2' and bz2:
                self.__compress = bz2.compress
                encoding = 'bz2'

            if not self.__compress:
                log.warning("'%s' compression specified, but '%s' compression is not available.  No compression will be used." % (compression_type, compression_type) )

        if encoding:
            self.__standard_headers['Content-Encoding'] = encoding

        # Configure compression level
        if self.__compress:
            if compression_level < 1 or compression_level > 9:
                log.warning("Invalid compression level used - %d.  Range must be 1-9.  Defaulting to 9 - maximum compression." % (compression_level) )
                compression_level = 9

        self.__compression_level = compression_level

        # The number of sconds to wait for a blocking operation on the connection before considering it to have
        # timed out.
        self.__request_deadline = request_deadline

        # The total number of RPC requests sent.
        self.total_requests_sent = 0
        # The total number of RPC requests that failed.
        self.total_requests_failed = 0
        # The total number of bytes sent over the network.
        self.total_request_bytes_sent = 0
        # The total number of compressed bytes sent over the network
        self.total_compressed_request_bytes_sent = 0
        # The total number of bytes received.
        self.total_response_bytes_received = 0
        # The total number of secs spent waiting for a responses (so average latency can be calculated by dividing
        # this number by self.total_requests_sent).  This includes connection establishment time.
        self.total_request_latency_secs = 0
        # The total number of HTTP connections successfully created.
        self.total_connections_created = 0
        # The path the file containing the certs for the root certificate authority to use for verifying the SSL
        # connection to Scalyr.  If this is None, then server certificate verification is disabled, and we are
        # susceptible to man-in-the-middle attacks.
        self.__ca_file = ca_file
        self.__proxies = proxies

        # debug flag to disable send requests
        self.__disable_send_requests = disable_send_requests

    def augment_user_agent(self, fragments):
        """Modifies User-Agent header (applies to all data sent to Scalyr)

        @param fragments String fragments to append (in order) to the standard user agent data
        @type fragments: List of str
        """
        self.__standard_headers['User-Agent'] = ScalyrClientSession.__get_user_agent(self.__agent_version, fragments)

    def ping(self):
        """Ping the Scalyr server by sending a test message to add zero events.

        If the returned message is 'success', then it has been verified that the agent can connect to the
        configured Scalyr server and that the api key is correct.

        @return:  The status message returned by the server.
        @rtype:
        """
        return self.send(self.add_events_request())[0]

    def __send_request(self, request_path, body=None, body_func=None, is_post=True, block_on_response=True):
        """Sends a request either using POST or GET to Scalyr at the specified request path.  It may be either
        a POST or GET.

        Parses, returns response.

        @param request_path: The path of the URL to post to.
        @param [body]: The body string to send.  May be None if body_func is specified.  Ignored if not POST.
        @param [body_func]:  A function that will be invoked to retrieve the body to send in the post.  Ignored if not
            POST.
        @param [is_post]:  True if this request should be sent using a POST, otherwise GET.
        @param [block_on_response]:  True if this request should block, waiting for the response.  If False, it will
            not block, but instead return a function, that will invoked, will block.

        @type request_path: str
        @type body: str|None
        @type body_func: func|None
        @type is_post: bool
        @type block_on_response: bool

        @return: If block_on_response is True, a tuple containing the status message in the response
            (such as 'success'), the number of bytes sent, and the full response.  If block_on_response is False,
            then returns a function, that will invoked, will block and return the tuple.
        @rtype: (str, int, str) or Function
        """
        current_time = time.time()

        # Refuse to try to send the message if the connection has been recently closed and we have not waited
        # long enough to try to re-open it.  We do this to avoid excessive connection opens and SYN floods.
        if self.__last_connection_close is not None and current_time - self.__last_connection_close < 30:
            return self.__wrap_response_if_necessary('client/connectionClosed', 0, '', block_on_response)

        self.total_requests_sent += 1


        was_sent = False

        try:
            try:
                if self.__connection is None:
                    self.__connection = ConnectionFactory.connection( self.__full_address, self.__request_deadline,
                                                                      self.__ca_file, self.__standard_headers,
                                                                      self.__use_requests, quiet=self.__quiet,
                                                                      proxies=self.__proxies)
                    self.total_connections_created += 1
            except Exception, e:
                return self.__wrap_response_if_necessary('client/connectionFailed', 0, '', block_on_response)

            if is_post:
                if body is None:
                    body_str = body_func()
                else:
                    body_str = body
            else:
                body_str = ""

            self.total_request_bytes_sent += len(body_str) + len(request_path)

            if self.__compress:
                body_str = self.__compress( body_str, self.__compression_level )

            self.total_compressed_request_bytes_sent += len(body_str) + len(request_path)

            # noinspection PyBroadException
            try:
                if self.__disable_send_requests:
                    log.log( scalyr_logging.DEBUG_LEVEL_0, "Send requests disabled.  %d bytes dropped" % self.total_request_bytes_sent,
                             limit_once_per_x_secs=60, limit_key='send-requests-disabled')
                else:
                    if is_post:
                        log.log(scalyr_logging.DEBUG_LEVEL_5, 'Sending POST %s with body \"%s\"', request_path, body_str)
                        self.__connection.post( request_path, body=body_str )
                    else:
                        log.log(scalyr_logging.DEBUG_LEVEL_5, 'Sending GET %s', request_path)
                        self.__connection.get( request_path )

            except Exception, error:
                # TODO: Do not just catch Exception.  Do narrower scope.
                if hasattr(error, 'errno') and error.errno is not None:
                    log.error('Failed to connect to "%s" due to errno=%d.  Exception was %s.  Closing connection, '
                              'will re-attempt', self.__full_address, error.errno, str(error),
                              error_code='client/requestFailed')
                else:
                    log.exception('Failed to send request due to exception.  Closing connection, will re-attempt',
                                  error_code='requestFailed')
                return self.__wrap_response_if_necessary('requestFailed', len(body_str), '', block_on_response)

            was_sent = True

            def receive_response():
                return self.__receive_response(body_str, current_time)

            if not block_on_response:
                return receive_response
            else:
                return receive_response()

        finally:
            if not was_sent:
                self.total_request_latency_secs += (time.time() - current_time)
                self.total_requests_failed += 1
                self.close(current_time=current_time)

    def __receive_response(self, body_str, send_time):
        """Receives a response for a request previously sent using __send_request.

        @param body_str: The body of the request that was sent.
        @param send_time: The time of day when the request was sent.

        @type body_str: str
        @type send_time: float
        @return:  The tuple containing the status message in the response  (such as 'success'), the number of bytes
            sent, and the full response.
        @rtype: (str, int, str)
        """
        response = ''
        was_success = False
        bytes_received = 0

        try:
            try:
                if self.__disable_send_requests:
                    response = '{ "status":"success" }'
                    status_code = 200
                else:
                    status_code = self.__connection.status_code()
                    response = self.__connection.response()
                bytes_received = len(response)
            except httplib.HTTPException, httpError:
                log.error('Failed to receive response due to HTTPException \'%s\'. Closing connection, will re-attempt' % ( httpError.__class__.__name__ ),
                                  error_code='requestFailed')
                return 'requestFailed', len(body_str), response

            except Exception, error:
                # TODO: Do not just catch Exception.  Do narrower scope.
                if hasattr(error, 'errno') and error.errno is not None:
                    log.error('Failed to receive response to "%s" due to errno=%d.  Exception was %s.  Closing '
                              'connection, will re-attempt', self.__full_address, error.errno, str(error),
                              error_code='client/requestFailed')
                else:
                    log.exception('Failed to receive response due to exception.  Closing connection, will re-attempt',
                                  error_code='requestFailed')
                return 'requestFailed', len(body_str), response

            log.log(scalyr_logging.DEBUG_LEVEL_5, 'Response was received with body \"%s\"', response)

            if status_code == 429:
                log.error('Received "too busy" response from server.  Will re-attempt',
                          error_code='serverTooBusy')
                return 'serverTooBusy', len(body_str), response

            # If we got back an empty result, that often means the connection has been closed or reset.
            if len(response) == 0:
                log.error('Received empty response, server may have reset connection.  Will re-attempt',
                          error_code='emptyResponse')
                return 'emptyResponse', len(body_str), response

            # Try to parse the response
            # noinspection PyBroadException
            try:
                response_as_json = json_lib.parse(response)
            except Exception:
                # TODO: Do not just catch Exception.  Do narrower scope.  Also, log error here.
                log.error('Failed to parse response of \'%s\' due to exception.  Closing connection, will '
                          're-attempt', scalyr_util.remove_newlines_and_truncate(response, 1000),
                          error_code='parseResponseFailed')
                return 'parseResponseFailed', len(body_str), response

            self.__last_success = send_time

            if 'status' in response_as_json:
                status = response_as_json['status']
                if status == 'success':
                    was_success = True
                elif status == 'error/client/badParam':
                    log.error('Request to \'%s\' failed due to a bad parameter value.  This may be caused by an '
                              'invalid write logs api key in the configuration', self.__full_address,
                              error_code='error/client/badParam')
                else:
                    log.error('Request to \'%s\' failed due to an error.  Returned error code was \'%s\'',
                              self.__full_address, status, error_code='error/client/badParam')
                return status, len(body_str), response
            else:
                log.error('No status message provided in response.  Unknown error.  Response was \'%s\'',
                          scalyr_util.remove_newlines_and_truncate(response, 1000), error_code='unknownError')
                return 'unknownError', len(body_str), response

        finally:
            self.total_request_latency_secs += (time.time() - send_time)
            if not was_success:
                self.total_requests_failed += 1
                self.close(current_time=send_time)
            self.total_response_bytes_received += bytes_received

    def __wrap_response_if_necessary(self, status_message, bytes_sent, response, block_on_response):
        """Wraps the response as appropriate based on whether or not the caller is expecting to block on the
        response or not.

        If the caller requested to not block on the response, then they are expecting a function to be returned
        that, when invoked, will block and return the result.  If the caller did requested to block on the response,
        then the response should be returned directly.

        This is used to cover cases where there was an error and we do not have to block on the response from
        the server.  Instead, we already have the response to return.  However, we still need to return the
        right type of object to the caller.

        @param status_message: The status message for the response.
        @param bytes_sent: The number of bytes that were sent.
        @param response: The response to return.
        @param block_on_response: Whether or not the caller requested to block, waiting for the response.  This controls
            whether or not a function is returned or just the response tuple directly.

        @type status_message: str
        @type bytes_sent: int
        @type response: str
        @type block_on_response: bool

        @return: Either a func or a response tuple (status message, num of bytes sent, response body) depending on
            the value of ``block_on_response``.
        @rtype: func or (str, int, str)
        """
        if block_on_response:
            return status_message, bytes_sent, response

        def wrap():
            return status_message, bytes_sent, response

        return wrap

    def send(self, add_events_request, block_on_response=True):
        """Sends an AddEventsRequest to Scalyr.

        The AddEventsRequest should have been retrieved using the 'add_events_request' method on this object.

        @param add_events_request: The request containing any log lines/events to copy to the server.
        @param block_on_response:  If True, this method will block, waiting for the response from the server.
            Otherwise, it will not block.  Instead, a function will be returned, that when invoked, will block.
        @type add_events_request: AddEventsRequest
        @type block_on_response: bool

        @return: If block_on_response is True, a tuple containing the status message in the response
            (such as 'success'), the number of bytes sent, and the full response.  If block_on_response is False,
            then returns a function, that will invoked, will block and return the tuple.
        @rtype: (str, int, str) or Function
        """
        current_time = time.time()

        def generate_body():
            add_events_request.set_client_time(current_time)

            return add_events_request.get_payload()

        return self.__send_request('/addEvents', body_func=generate_body, block_on_response=block_on_response)

    def close(self, current_time=None):
        """Closes the underlying connection to the Scalyr server.

        @param current_time: If not None, the time to use for the current time.  Used for testing purposes.
        @type current_time: float or None
        """
        if self.__connection is not None:
            if current_time is None:
                current_time = time.time()
            self.__connection.close()
            self.__connection = None
            self.__last_connection_close = current_time

    def add_events_request(self, session_info=None, max_size=1*1024*1024*1024):
        """Creates and returns a new AddEventRequest that can be later sent by this session.

        The caller is expected to add events to this request and then submit it for transmission using
        the 'send' method.

        @param session_info: The session info for this session, which is basically any attributes that should
            be added to all events uploaded by this agent, such as server attributes from the config file.
        @param max_size: The maximum number of bytes to send in this request.

        @type session_info: dict
        @type max_size: int

        @return:  The request that can be populated.
        @rtype: AddEventsRequest
        """
        body = {
            'token': self.__api_key,
            'session': self.__session_id,
            'threads': [],
        }

        if session_info is not None:
            body['sessionInfo'] = session_info

        return AddEventsRequest(body, max_size=max_size)

    @staticmethod
    def __get_user_agent(agent_version, fragments=None):
        """Determine the user agent to report in the request headers.

        We construct an agent that gives Scalyr some information about the platform the customer is running on,
        the Python version, and a few other tidbits.  This is used to make decisions about support issues.

        @param agent_version: The agent version number.
        @param fragments: Additional strings to be appended. Each will be preceded by a semicolon
        @type agent_version: str
        @type fragments: List of str

        @return: The user agent string.
        @rtype: str
        """
        # We will construct our agent string to look something like:
        # Linux-redhat-7.0;python-2.7.2;agent-2.0.1;ssllib

        python_version = sys.version_info
        if len(python_version) >= 5:
            python_version_str = 'python-%s.%s.%s' % (python_version[0], python_version[1], python_version[2])
        else:
            python_version_str = 'python-unknown'

        # Try for a linux distribution first.  This doesn't seem to work for Amazon AMIs, but for most
        # distributions it hopefully will provide something readable.
        platform_value = None
        # noinspection PyBroadException
        try:
            distribution = platform.dist()
            if len(distribution[0]) > 0:
                platform_value = 'Linux-%s-%s' % (distribution[0], distribution[1])
        except Exception:
            platform_value = None

        # Try Mac
        if platform_value is None:
            # noinspection PyBroadException
            try:
                mac_ver = platform.mac_ver()[0]
                if len(mac_ver) > 0:
                    platform_value = 'MacOS-%s' % mac_ver
            except Exception:
                platform_value = None

        # Fall back for all others.  This should print out something reasonable for
        # Windows.
        if platform_value is None:
            platform_value = platform.platform(terse=1)

        # Include a string to indicate if python has a true ssl library available to record
        # whether or not the client is doing server certificate verification.
        if __has_ssl__:
            ssl_str = 'ssllib'
        else:
            ssl_str = 'nossllib'

        parts = [platform_value, python_version_str, 'agent-%s' % agent_version, ssl_str]
        if fragments:
            parts.extend(fragments)
        return ';'.join(map(str, parts))

    def perform_agent_version_check(self, track='stable'):
        """Query the Scalyr API to determine if a newer version is available
        """
        url_path = "/ajax?method=performAgentVersionCheck&installedVersion=%s&track=%s" % (self.__agent_version, track)

        return self.__send_request(url_path, is_post=False)


class EventSequencer( object ):
    """Responsible for keeping track of sequences for an AddEventsRequest

    This abstraction keeps track of previously seen sequence_ids and numbers
    And adds the appropriate fields to an event based on provided sequence ids
    and values.

    This is a standalone class so that various test objects can also use the same
    logic
    """

    def __init__( self ):
        # the previously used sequence_id, used to determine if we need to send the sequence_id
        # with an event
        self.__previous_sequence_id = None

        # the previously seen sequence_number - used to calculate deltas for the sequence_number
        self.__previous_sequence_number = None

    def reset( self ):
        """Resets the sequence tracking"""
        self.__previous_sequence_id = None
        self.__previous_sequence_number = None

    def get_memento( self ):
        """returns internal state of the sequencer as a tuple
        Callers can use this method to set and restore the internal state of the sequencer
        """
        return (self.__previous_sequence_id, self.__previous_sequence_number)


    def restore_from_memento( self, memento ):
        """Restores the state of the EventSequencer with the values from a previous
        call to get_memento
        """
        self.__previous_sequence_id = memento[0]
        self.__previous_sequence_number = memento[1]

    def add_sequence_fields( self, event, sequence_id, sequence_number ):
        """
        If sequence_id and sequence_number are non-None then this method will automatically add the following
        fields:

        'si' set to the value of sequence_id if it is different from the previously seen sequence_id
        'sn' set to the value of sequence_number if we haven't previously seen a sequence number
        'sd' set to the delta of the sequence_number and the previously seen sequence_number

        The 'sn' and 'sd' fields are mutually exclusive.  Only one or the other will be used

        @param event: The event to update
        @param sequence_id: The sequence id
        @param sequence_number: The sequence number

        @type event: Event
        @type sequence_id: long
        @type sequence_number: long
        """

        # only add sequence information if both the sequence fields are valid
        if sequence_id is not None and sequence_number is not None:

            # add the 'si' field if necessary
            if sequence_id != self.__previous_sequence_id:
                event.set_sequence_id(sequence_id)
                self.__previous_sequence_id = sequence_id
                # a new sequence id means we should also send the full sequence number
                # so make sure that __previous_sequence_number is None
                self.__previous_sequence_number = None

            # if we don't have a previous sequence number then send the full number
            # otherwise send the delta
            if self.__previous_sequence_number is None:
                event.set_sequence_number(sequence_number)
            else:
                event.set_sequence_number_delta(sequence_number - self.__previous_sequence_number)

            self.__previous_sequence_number = sequence_number


class AddEventsRequest(object):
    """Used to construct an AddEventsRequest to eventually send.

    This abstraction has three key features.  First, it uses a generally more efficient scheme to build
    up the string to eventually use as the body for an add_events request.  Secondly, it does not require all events
    at construction time.  Instead, you can incrementally add more events before the request is actually sent.  This
    leads to better memory utilization when combined with an abstraction that is incrementally reading events from disk.
    It will also prevent you from exceeding the maximum request size.  Third, you may undo the effect of adding events
    to the request before it is sent.  This is useful to rollback the request state to a previous state if some
    problem occurs.
    """
    def __init__(self, base_body, max_size=1*1024*1024):
        """Initializes the instance.

        @param base_body: A JsonObject or dict containing the information to send as the body of the add_events
            request, with the exception of the events field. The events and client_timestamp fields must not be
            included because they will be added later. Note, base_body must have some fields set, such as 'ts' which is
            required by the server.
        @param max_size: The maximum number of bytes this request can consume when it is serialized to JSON.
        """
        assert len(base_body) > 0, "The base_body object must have some fields defined."
        assert not 'events' in base_body, "The base_body object cannot already have 'events' set."
        assert not 'client_time' in base_body, "The base_body object cannot already have 'client_time' set."

        # As an optimization, we use a StringIO object to serialize the request.  We also
        # do a little bit of the JSON object assembly by hand.  Specifically, we serialize the request
        # to JSON without the 'events' field, but then delete the last '}' so that we can manually
        # add in the 'events: [ ... ]' ourselves.  This way we can watch the size of the buffer as
        # we build up events.
        string_buffer = StringIO()
        json_lib.serialize(base_body, output=string_buffer, use_fast_encoding=True)

        # Now go back and find the last '}' and delete it so that we can open up the JSON again.
        _rewind_past_close_curly(string_buffer)

        # Append the start of our events field.
        string_buffer.write(', events: [')

        # This buffer keeps track of all of the stuff that must be appended after the events JSON array to terminate
        # the request.  That includes both the threads JSON array and the client timestamp.
        self.__post_fix_buffer = PostFixBuffer('], threads: THREADS, client_time: TIMESTAMP }')

        # The time that will be sent as the 'client_time' parameter for the addEvents request.
        # This may be later updated using the set_client_time method in the case where the same AddEventsRequest
        # is being reused to send the events again.
        self.__post_fix_buffer.set_client_timestamp(time.time())

        self.__buffer = string_buffer
        self.__max_size = max_size

        self.__events_added = 0

        # If we have finished serializing the body, it is stored here until the close() method is invoked.
        self.__body = None

        # Used to add sequence fields to an event
        self.__event_sequencer = EventSequencer()

        # Used to record some performance timing data for debugging/analysis
        self.__timing_data = dict()

    @property
    def current_size(self):
        """
        @return: The number of bytes that will be used to send the current request.  This include both the bytes
            from the events and the post fix.
        @rtype: int
        """
        if self.__buffer is not None:
            return self.__buffer.tell() + self.__post_fix_buffer.length
        else:
            return len(self.__body)

    def add_thread(self, thread_id, thread_name):
        """Registers the specified thread for this AddEvents request.

        Any thread id mentioned in any event in this request should first be registered here.

        @param thread_id: An id for the thread.  This can then be used as the value for a ``thread`` field
            in the ``event`` object passed to ``add_event``.  Should be unique for this session.
        @param thread_name: A human-readable name for the thread

        @type thread_id: str
        @type thread_name: str

        @return: True if there was the allowed bytes to send were not exceeded by adding this thread to the
            request.
        @rtype: bool
        """
        # Have to account for the extra space this will use when serialized.  See how much space we can allow for
        # the post fix right now.
        available_size_for_post_fix = self.__max_size - self.__buffer.tell()
        return self.__post_fix_buffer.add_thread_entry(thread_id, thread_name,
                                                       fail_if_buffer_exceeds=available_size_for_post_fix)

    def add_event(self, event, timestamp=None, sequence_id=None, sequence_number=None):
        """Adds the serialized JSON for event if it does not cause the maximum request size to be exceeded.

        It will automatically set the event's timestamp field to a new timestamp based on the current time
        but ensuring it is greater than any previous timestamp that has been used.

        If sequence_id and sequence_number are specified then this method will automatically set the following
        Event fields fields:

        'sequence_id' set to the value of sequence_id if it is different from the previously seen sequence_id
        'sequence_number' set to the value of sequence_number if we haven't previously seen a sequence number
        'sequence_number_delta' set to the delta of the sequence_number and the previously seen sequence_number

        The 'sequence_number' and 'sequence_number_delta' fields are mutually exclusive.  Only one or the other will be
        used.

        It is illegal to invoke this method if 'get_payload' has already been invoked.

        @param event: The event object.
        @param timestamp: The timestamp to use for the event, in nanoseconds since the Epoch. If None, will be the current time.time()
        @param sequence_id: A globally unique id, grouping a set of sequence_numbers
        @param sequence_number: A monotonically increasing sequence_number

        @type event: Event
        @type timestamp: long
        @type sequence_id: long
        @type sequence_number: long

        @return: True if the event's serialized JSON was added to the request, or False if that would have resulted
            in the maximum request size being exceeded so it did not.
        """
        start_pos = self.__buffer.tell()
        # If we already added an event before us, then make sure we add in a comma to separate us from the last event.
        if self.__events_added > 0:
            self.__buffer.write(',')

        timestamp = self.__get_valid_timestamp(timestamp=timestamp)

        # get copy of event sequencer state in case the event wasn't actually added
        # and we need to restore it
        memento = self.__event_sequencer.get_memento()

        self.__event_sequencer.add_sequence_fields(event, sequence_id, sequence_number)
        event.set_timestamp(timestamp)
        event.serialize(self.__buffer)

        # Check if we exceeded the size, if so chop off what we just added.
        # Also reset previously seen sequence numbers and ids
        if self.current_size > self.__max_size:
            self.__buffer.truncate(start_pos)
            self.__event_sequencer.restore_from_memento( memento )
            return False

        self.__events_added += 1
        return True

    @property
    def num_events(self):
        """Returns the number of events added to this request so far.

        @return:  The number of events added to this request.
        @rtype: int
        """
        return self.__events_added

    def set_client_time(self, current_time):
        """Update the 'client_time' field in the request.

        The 'client_time' field should be set to the current time as known by the client when this request is
        sent.  Since a AddEventsRequest can be re-used multiple times to try to resend some events, it is important
        to update the 'client_time' field before each send.

        The 'client_time' field is used by the server to warn when the client clock skew is too great since that
        can lead to log upload problems.

        @param current_time: The current time to include in the request.
        @type current_time: float
        """
        # Get the current size of the postfix buffer since we may need it down below.  We need the length before
        # the new timestamp was added.
        original_postfix_length = self.__post_fix_buffer.length

        self.__post_fix_buffer.set_client_timestamp(current_time)

        if self.__body is not None:
            # We have already cached the serialized JSON, so we need to update it to remain consistent.

            # Create a buffer for the copying.  We write in the entire JSON and then just back up the length of
            # the old postfix and then add in the new one.
            rebuild_buffer = StringIO()
            rebuild_buffer.write(self.__body)
            self.__body = None
            rebuild_buffer.seek(-1 * original_postfix_length, 2)  # os.SEEK_END
            rebuild_buffer.truncate()

            rebuild_buffer.write(self.__post_fix_buffer.content())
            self.__body = rebuild_buffer.getvalue()
            rebuild_buffer.close()

    def get_payload(self):
        """Returns the serialized JSON to use as the body for the add_request.

        After this is invoked, no new events can be added via the 'add_event' method.  However,
        you may call the 'set_client_time' method to update when this request is being sent, according to
        the client clock.
        """
        if self.__body is None:
            self.__buffer.write(self.__post_fix_buffer.content())
            self.__body = self.__buffer.getvalue()
            self.__buffer.close()
            self.__buffer = None
        return self.__body

    def close(self):
        """Must be invoked after this request is no longer needed.  You may not add events or invoke get_payload
        after this call.
        """
        self.__body = None
        self.__buffer = None

    def increment_timing_data(self, **key_values):
        """Increments the timing data kept as part of this data structure to help diagnosis performance issues.

        The arguments should be key/value pairs where the keys name some sort of timing component and the value
        by which to increment the count for that timing component.

        If this is the first time a timing component is being incremented, the initial value is set to zero.
        """
        for key, value in key_values.iteritems():
            if key in self.__timing_data:
                amount = self.__timing_data[key]
            else:
                amount = 0.0
            amount += value
            self.__timing_data[key] = amount

    def get_timing_data(self):
        """Serializes all of the timing data that has been collected via ``increment_timing_data``.

        @return: A string of the key/value pairs for all timing data.
        @rtype: str
        """
        output_buffer = StringIO()
        first_time = True

        for key, value in self.__timing_data.iteritems():
            if not first_time:
                output_buffer.write(' ')
            else:
                first_time = False
            output_buffer.write(key)
            output_buffer.write('=')
            output_buffer.write(str(value))

        return output_buffer.getvalue()

    def __get_valid_timestamp(self, timestamp=None):
        """
        Gets a timestamp in nanoseconds since the Epoch, ensuring that the result is at least 1 nanosecond
        greater than previously returned results.
        @param timestamp: A timestamp to validate.  If it is greater than the result of a previous call the value will
                          be returned with no changes.  If less than the result of a previous call the result will
                          be 1 nanosecond greater than the previous result.
                          If None, time.time() is used for the value of timestamp.
        @return: The next timestamp to use for events.  This is guaranteed to be monotonically increasing.
        @rtype: long
        """
        global __last_time_stamp__

        if timestamp is None:
            timestamp = long(time.time() * 1000000000L)

        if __last_time_stamp__ is not None and timestamp <= __last_time_stamp__:
            timestamp = __last_time_stamp__ + 1L
        __last_time_stamp__ = timestamp

        return timestamp

    @property
    def total_events(self):
        """Returns the total number of events that will be sent in this batch."""
        return self.__events_added

    def position(self):
        """Returns a position such that if it is passed to 'set_position', all events added since this method was
        invoked are removed."""

        return AddEventsRequest.Position(self.__events_added, self.__buffer.tell(), self.__post_fix_buffer.position)

    def set_position(self, position):
        """Reverts this object to only contain the events contained by the object when position was invoked to
        get the passed in position.

        @param position: The position token representing the previous state.
        """
        self.__events_added = position.events_added
        self.__buffer.truncate(position.buffer_size)
        self.__post_fix_buffer.set_position(position.postfix_buffer_position)

        #reset previously seen sequence id and numbers
        self.__event_sequencer.reset()

    class Position(object):
        """Represents a position in the added events.
        """
        def __init__(self, events_added, buffer_size, postfix_buffer_position):
            self.events_added = events_added
            self.buffer_size = buffer_size
            self.postfix_buffer_position = postfix_buffer_position


# This is used down below by PostFixBuffer.
def _calculate_per_thread_extra_bytes():
    """Calculates how many extra bytes are added to the serialized form of the threads JSON array
    when adding a new thread, excluding the bytes for serializing the thread id and name themselves.

    This is used below by the PostFixBuffer abstraction to help calculate the number of bytes the serialized form
    of the PostFixBuffer will take, without having to actually serialize it.  It was found that doing the heavy
    weight process of serializing it over and over again to just get the size was eating too much CPU.

    @return: An array of two int entries.  The first entry is how many extra bytes are added when adding the
        first thread to the threads JSON array and the second is how many extra bytes are added for all subsequent
        threads.  (The number differences by at least one due to the need for a comma to be inserted).
    @rtype: [int]
    """
    # An array of the number of bytes used to serialize the array when there are N threads in it (where N is the
    # index into size_by_entries).
    sizes_by_entries = []

    # Calculate sizes_by_entries by actually serialzing each case.
    threads = []
    test_string = 'A'
    for i in range(3):
        sizes_by_entries.append(len(scalyr_util.json_encode(threads)))

        # Add in another thread for the next round through the loop.
        threads.append({'id': test_string, 'name': test_string})

    # Now go back and calculate the deltas between the different cases.  We have to remember to subtract
    # out the length due to the id and name strings.

    test_string_len = len(scalyr_util.json_encode(test_string))
    result = []
    for i in range(1, 3):
        result.append(sizes_by_entries[i] - sizes_by_entries[i - 1] - 2 * test_string_len)

    return result


class PostFixBuffer(object):
    """Buffer for the items that must be written after the events JSON array, which typically means
    the client timestamp and the threads JSON array.

    This abstraction has optimizations in place to more efficiency keep track of the number of bytes the
    that will be used by the serialized form.

    Additionally, the buffer can be reset to a previous position.
    """
    def __init__(self, format_string):
        """Initializes the buffer.

        @param format_string: The format for the buffer.  The output of this buffer will be this format string
            with the keywords THREADS and TIMESTAMP replaced with the json serialized form of the threads
            JSON array and the timestamp.
        @type format_string: str
        """
        # Make sure the keywords are used in the format string.
        assert('THREADS' in format_string)
        assert('TIMESTAMP' in format_string)

        # The entries added to include in the threads JSON array in the request.
        self.__threads = []
        # The timestamp to include in the output.
        self.__client_timestamp = 0
        self.__format = format_string
        self.__current_size = len(self.content())

    # Static variable holding the number of extra bytes to add in when calculating the new size due to adding in
    # a new thread entry (beyond just the bytes due to the serialized thread id and thread name themselves).
    # This will have two entries.  See above for a better description.
    __per_thread_extra_bytes = _calculate_per_thread_extra_bytes()

    @property
    def length(self):
        """The number of bytes the serialized buffer will take.

        @return: The number of bytes
        @rtype: int
        """
        return self.__current_size

    def content(self, cache_size=True):
        """Serialize all the information for the post fix and return it.

        @param cache_size: Used for testing purposes.  Can be used to turn off a slop factor that will automatically
            fix differences between the calculated size and the actual size.  We turn this off for testing to make
            sure we catch these errors.
        @type cache_size: bool

        @return: The post fix to include at the end of the AddEventsRequest.
        @rtype: str
        """
        result = self.__format.replace('TIMESTAMP', str(self.__client_timestamp))
        result = result.replace('THREADS', scalyr_util.json_encode(self.__threads))

        # As an extra extra precaution, we update the current_size to be what it actually turned out to be.  We could
        # assert here to make sure it's always equal (it should be) but we don't want errors to cause issues for
        # customers.  Due to the way AddRequest uses this abstraction, we really really need to make sure
        # the length() returns the correct result after content() was invoked, so we add in this measure to be safe.
        if cache_size:
            self.__current_size = len(result)
        return result

    def set_client_timestamp(self, timestamp, fail_if_buffer_exceeds=None):
        """Updates the client timestamp that will be included in the post fix.

        @param timestamp: The timestamp.
        @param fail_if_buffer_exceeds: The maximum number of bytes that can be used by the post fix when serialized.
            If this is not None, and the size will exceed this amount when the timestamp is changed, then the
            timestamp is not changed and False is returned.

        @type timestamp: int|float
        @type fail_if_buffer_exceeds: None|int

        @return: True if the thread was added (can only return False if fail_if_buffer_exceeds is not None)
        @rtype: bool
        """
        new_timestamp = int(timestamp)
        size_difference = len(str(new_timestamp)) - len(str(self.__client_timestamp))

        if fail_if_buffer_exceeds is not None and self.__current_size + size_difference > fail_if_buffer_exceeds:
            return False

        self.__current_size += size_difference
        self.__client_timestamp = new_timestamp
        return True

    def add_thread_entry(self, thread_id, thread_name, fail_if_buffer_exceeds=None):
        """Adds in a new thread entry that will be included in the post fix.


        @param thread_id: The id of the thread.
        @param thread_name: The name of the thread.
        @param fail_if_buffer_exceeds: The maximum number of bytes that can be used by the post fix when serialized.
            If this is not None, and the size will exceed this amount when the thread entry is added, then the
            thread is not added and False is returned.

        @type thread_id: str
        @type thread_name: str
        @type fail_if_buffer_exceeds: None|int

        @return: True if the thread was added (can only return False if fail_if_buffer_exceeds is not None)
        @rtype: bool
        """
        # Calculate the size difference.  It is at least the size of taken by the serialized strings.
        size_difference = len(scalyr_util.json_encode(thread_name)) + len(scalyr_util.json_encode(thread_id))

        # Use the __per_thread_extra_bytes to calculate the additional bytes that will be consumed by serializing
        # the JSON object containing the thread id and name.  The number of extra bytes depends on whether or not
        # there is already an entry in the JSON array, so take that into consideration.
        num_threads = len(self.__threads)
        if num_threads < 1:
            size_difference += PostFixBuffer.__per_thread_extra_bytes[0]
        else:
            size_difference += PostFixBuffer.__per_thread_extra_bytes[1]

        if fail_if_buffer_exceeds is not None and self.__current_size + size_difference > fail_if_buffer_exceeds:
            return False

        self.__current_size += size_difference
        self.__threads.append({'id': thread_id, 'name': thread_name})
        return True

    @property
    def position(self):
        """Returns the current `position` for this buffer.

        This can be used to reset the buffer to a state before new thread entries were added or timestamps were set.

        @return: The position object.
        """
        # We store the information just as three entries in an array because we are lazy.
        return [self.__current_size, self.__client_timestamp, len(self.__threads)]

    def set_position(self, position):
        """Resets the buffer to a previous state.

        The contents of the thread JSON array and the client timestamp will be reset to whatever it was when
        `position` was invoked.

        @param position: The position to reset the buffer state to.
        """
        # The position value should by an array with three entries: the size, the client timestamp, and the number
        # of threads.  Since threads are always added one after another, it is sufficient just to truncate back to that
        # previous length.
        self.__current_size = position[0]
        self.__client_timestamp = position[1]
        assert(len(self.__threads) >= position[2])
        if position[2] < len(self.__threads):
            self.__threads = self.__threads[0:position[2]]


class Event(object):
    """Encapsulates a single event that will be included in an ``AddEventsRequest``.

    This abstraction has many optimizations to improve serialization time.
    """
    def __init__(self, thread_id=None, attrs=None, base=None):
        """Creates an instance of an event to include in an AddEventsRequest.

        This constructor has two ways of being used.

        First, specifying the thread_id and attributes that will apply to the event.  The attributes typically only
        include the attributes for the log file that the event belongs to. You then must set the per-log line
        attributes (such as timestamp and message) using the setters provided below.

        The second form is to create an event based on the copy of an already existing ``Event`` instance.  This
        decreases overall serialization time because the ``attrs`` and ``thread_id`` field's serialization is only
        performed once across all for the original copy and shared to all derived copies.

        This is meant to really optimize the case where we create one base ``Event`` object for each log file that
        we are uploading (specifying that log's thread id and attributes in the constructor).  Then, every time
        we upload a log line for that log, we copy the base ``Event`` instance and then set the per-log line
        attributes using the provided setters.

        @param thread_id:  Used if not specifying ``base``.  The thread id for the event.
        @param attrs:  Used if not specifying ``base``.  The attributes for the event, excluding any attributes
            that can be set via the provided setters.  If you include one of those attributes in ``attrs``, the
            resulting behavior is undefined.
        @param base:  Used if not specifying ``thread_id`` or ``attrs``.  The instance of ``Event`` to copy to
            create this instance.  Only the original ``thread_id`` and ``attrs`` that was passed into ``base``
            are copied.  Anything set using the provided ``setters`` will not be used.

        @type thread_id: str
        @type attrs: dict
        @type base: Event
        """
        # When we serialize this event object in an AddEventsRequest, it will have the following fields, in this
        # form:
        #   {
        #      thread_id: "234234",         // str, the thread id for the log.
        #      attrs: {
        #         <log attributes>          // the keys,values for all attributes for this log.
        #         message: "Log content",   // str, the log line content.
        #         rate: 0.8,                // float, if this is a subsampled line, the rate at each it was selected.
        #      },
        #      ts: "123123123",   // <str, the timestamp for the log line>
        #      si: "123123",      //<str, the sequence identifier>
        #      sn: 10,            // <int, the sequence number -- not provided if sd is provided>
        #      sd: 1,             // <int, the sequence number delta -- provided instead of sn>
        #   }
        #
        # So, we can pre-serialize the first part of the message based on thread_id and attrs, and keep a copy of
        # that to then serialize the rest of the per-log line fields for later.
        #
        # The serialization_base (this pre-serialization) will look like:
        #
        #   {
        #      thread_id: "234234",         // str, the thread id for the log.
        #      attrs: {
        #         <log attributes>          // the keys,values for all attributes for this log.
        #         message:
        #
        # Note, we put in the ``message`` field name, so the next thing we have to serialize is the log line content.
        # We also then have to close off the attrs object, and eventually the overall object to finish the
        # serialization.

        # We only stash a copy of attrs for debugging/testing purposes.  We really will just serialize it into
        # __serialization_base.
        self.__attrs = attrs
        if (attrs is not None or thread_id is not None) and base is not None:
            raise Exception('Cannot use both attrs/thread_id and base')

        self.__thread_id = None
        if base is not None:
            # We are creating an event that is a copy of an existing one.  Re-use the serialization base to capture
            # the per-log file attributes.
            self.__serialization_base = base.__serialization_base
            self.__attrs = base.__attrs
        else:
            self.__set_attributes( thread_id, attrs )

        # The typical per-event fields.  Note, all of the fields below are stored as strings, in the serialized
        # forms for their event fields EXCEPT message.  For example, since ``sequence_id`` should be a string on the
        # json object, the __sequence_id field will begin with a double quote.  HOWEVER, message (for optimization
        # purposes) is not pre-serialized and will not be blackslashed escaped/quoted before being added to the
        # output buffer.
        self.__message = None
        self.__timestamp = None
        self.__sequence_id = None
        self.__sequence_number = None
        self.__sequence_number_delta = None
        self.__sampling_rate = None
        # Whether or not any of the non-fast path fields were included.  The fast fields are message, timestamp, snd.
        self.__has_non_optimal_fields = False
        self.__num_optimal_fields = 0


    def __set_attributes( self, thread_id, attributes ):
        self.__thread_id = thread_id
        self.__attrs = attributes
        # A new event.  We have to create the serialization base using provided information/
        tmp_buffer = StringIO()
        # Open base for the event object.
        tmp_buffer.write('{')
        if thread_id is not None:
            tmp_buffer.write('thread:')
            tmp_buffer.write( scalyr_util.json_encode(thread_id) )
            tmp_buffer.write(', ')
        if attributes is not None:
            # Serialize the attributes object, but we have to remove the closing brace because we want to
            # insert more fields.
            tmp_buffer.write('attrs:')
            tmp_buffer.write( scalyr_util.json_encode(attributes) )
            _rewind_past_close_curly(tmp_buffer)
            tmp_buffer.write(',')
        else:
            # Open brace for the attributes object.
            tmp_buffer.write('attrs:{')

        # Add the message field into the json object.
        tmp_buffer.write('message:')

        self.__serialization_base = tmp_buffer.getvalue()


    def add_missing_attributes(self, attributes):
        """ Adds items attributes to the base_event's attributes if the base_event doesn't
        already have those attributes set
        """
        if self.__attrs:
            changed = False
            new_attrs = dict(self.__attrs)
            for key, value in attributes.iteritems():
                if not key in new_attrs:
                    changed = True
                    new_attrs[key] = value

            if changed:
                self.__set_attributes(self.__thread_id, new_attrs)
        else:
            self.__set_attributes(self.__thread_id, attributes)

    @property
    def attrs(self):
        """
        @return: The attributes object as originally based into the constructor or the constructor of the base
            object that was to create this instance.
        @rtype: dict
        """
        return self.__attrs

    def set_message(self, message):
        """Sets the message field for the attributes for this event.

        @param message:  The message content.
        @type message: str
        @return:  This object.
        @rtype: Event
        """
        if self.__message is None and message is not None:
            self.__num_optimal_fields += 1
        if message is unicode:
            self.__message = message.encode('utf-8')
        else:
            self.__message = message
        return self

    @property
    def message(self):
        """Used only for testing.
        @return:  The message content
        @rtype: str
        """
        return self.__message

    def set_timestamp(self, timestamp):
        """Sets the timestamp field for the attributes for this event.

        @param timestamp:  The timestamp, in nanoseconds past epoch.
        @type timestamp: long
        @return:  This object.
        @rtype: Event
        """
        # The timestamp field is serialized as a string to get around overflow issues, so put it in string form now.
        if self.__timestamp is None and timestamp is not None:
            self.__num_optimal_fields += 1
        self.__timestamp = '"%s"' % str(timestamp)
        return self

    @property
    def timestamp(self):
        """Used only for testing.

        @return: the timestamp for the event.
        @rtype: long
        """
        # We have to cut off the quotes we surrounded the field with when we serialized it.
        if self.__timestamp is not None:
            return long(self.__timestamp[1:-1])
        else:
            return None

    def set_sequence_id(self, sequence_id):
        """Sets the sequence id for the event.  If this is not invoked, no sequence id will be included
        in the serialized event.  (Which is an optimization that can be used if the sequence id is the same
        as the last serialized event's).

        @param sequence_id:  The unique id for the sequence this event belongs.  This must be globally unique and
            usually tied to a single log file.  Generally, use UUID here.
        @type sequence_id: long
        @return:  This object.
        @rtype: Event
        """
        # This is serialized as a string to get around overflow issues, so put in a string now.
        self.__sequence_id = '"%s"' % str(sequence_id)
        self.__has_non_optimal_fields = True
        return self

    @property
    def sequence_id(self):
        """Used for testing purposes only
        @return:  The sequence id or None if not set.
        @rtype: str
        """
        # We have to cut off the quotes we surrounded the field with when we serialized it.
        if self.__sequence_id is not None:
            return self.__sequence_id[1:-1]
        self.__has_non_optimal_fields = True
        return None

    def set_sequence_number(self, sequence_number):
        """Sets the sequence number for the event.  If this is not invoked, no sequence number will be included
        in the serialized event.  (Which is an optimization that can be used if the sequence id is the same
        as the last serialized event's and you use ``sequence_number_delta`` instead to specify the delta between
        this events sequence number and the last one.).

        @param sequence_number:  The sequence number for the event.
        @type sequence_number: long
        @return:  This object.
        @rtype: Event
        """
        self.__has_non_optimal_fields = True
        # It is serialized as a number, so just a toString is called for.
        self.__sequence_number = str(sequence_number)
        return self

    @property
    def sequence_number(self):
        """Used for testing purposes only.
        @return: The sequence number or None if not set.
        @rtype: long
        """
        # We have to convert it back to a number.
        if self.__sequence_number is not None:
            return long(self.__sequence_number)
        else:
            return None

    def set_sequence_number_delta(self, sequence_number_delta):
        """Sets the sequence number delta for the event.  If this is not invoked, no sequence number delta will be
        included in the serialized event.  (Which is what you should do if you specify a ``sequence_number`` instead).

        @param sequence_number_delta:  The delta between the last sequence number of the one for this event.
        @type sequence_number_delta: long
        @return:  This object.
        @rtype: Event
        """
        # It is serialized as a number, so just a toString is called for.
        if self.__sequence_number_delta is None and sequence_number_delta is not None:
            self.__num_optimal_fields += 1
        self.__sequence_number_delta = str(sequence_number_delta)
        return self

    @property
    def sequence_number_delta(self):
        """Uses for testing purposes only.
        @return:  The sequence number delta if set or None.
        @rtype: long
        """
        # We have to convert it back to a number.
        if self.__sequence_number_delta is not None:
            return long(self.__sequence_number_delta)
        else:
            return None

    def set_sampling_rate(self, rate):
        """Sets the sampling rate field for this event.

        @param rate The rate
        @type rate float
        @return:  This object.
        @rtype: Event
        """
        self.__has_non_optimal_fields = True
        self.__sampling_rate = str(rate)
        return self

    def serialize(self, output_buffer):
        """Serialize the event into ``output_buffer``.

        @param output_buffer: The buffer to serialize to.
        @type output_buffer: StringIO
        """
        output_buffer.write(self.__serialization_base)
        # Use a special serialization format for message so that we don't have to send CPU time escaping it.  This
        # is just a length prefixed format understood by Scalyr servers.
        json_lib.serialize_as_length_prefixed_string(self.__message, output_buffer)

        # We fast path the very common case of just a timestamp and sequence delta fields.
        if not self.__has_non_optimal_fields and self.__num_optimal_fields == 3:
            output_buffer.write('}')
            output_buffer.write(',sd:')
            output_buffer.write(self.__sequence_number_delta)
            output_buffer.write(',ts:')
            output_buffer.write(self.__timestamp)
        else:
            self.__write_field_if_not_none(',sample_rate:', self.__sampling_rate, output_buffer)
            # close off attrs object.
            output_buffer.write('}')

            self.__write_field_if_not_none(',ts:', self.__timestamp, output_buffer)
            self.__write_field_if_not_none(',si:', self.__sequence_id, output_buffer)
            self.__write_field_if_not_none(',sn:', self.__sequence_number, output_buffer)
            self.__write_field_if_not_none(',sd:', self.__sequence_number_delta, output_buffer)
        # close off the event object.
        output_buffer.write('}')

    def __write_field_if_not_none(self, field_name, field_value, output_buffer):
        """If the specified field value is not None, then emit the field name and the value to the output buffer.

        @param field_name: The text to emit before the value.
        @param field_value: The value to emit.
        @param output_buffer: The buffer to serialize to.

        @type field_name: str
        @type field_value: str or None
        @type output_buffer: StringIO
        """
        if field_value is not None:
            output_buffer.write(field_name)
            output_buffer.write(field_value)


def _rewind_past_close_curly(output_buffer):
    """A utility function for rewinding a buffer that had a JSON object emitted to it.  It rewinds past the
    last closing curly brace in the buffer, and then also erases the last non-whitespace character after that
    if it is a comma (which shouldn't happen in practice).  This is meant to prepare the buffer for emitting
    new fields into the JSON object's serialization.

    @param output_buffer:  The buffer to rewind.
    @type output_buffer: StringO
    """
    # Now go back and find the last '}' and delete it so that we can open up the JSON again.
    location = output_buffer.tell()
    while location > 0:
        location -= 1
        output_buffer.seek(location)
        if output_buffer.read(1) == '}':
            break

    # Now look for the first non-white character.  We need to add in a comma after it.
    last_char = None
    while location > 0:
        location -= 1
        output_buffer.seek(location)
        last_char = output_buffer.read(1)
        if not last_char.isspace():
            break

    # If the character happened to a comma, back up over that since we want to write our own comma.
    if location > 0 and last_char == ',':
        location -= 1

    if location < 0:
        raise Exception('Could not locate trailing "}" and non-whitespace in JSON serialization')

    # Now chop off everything after the character at the location.
    location += 1
    output_buffer.seek(location)
    output_buffer.truncate()


# The last timestamp used for any event uploaded to the server.  We need to guarantee that this is monotonically
# increasing so we track it in a global var.
__last_time_stamp__ = None

def _set_last_timestamp( val ):
    """
    exposed for testing
    """
    global __last_time_stamp__
    __last_time_stamp__ = val


class HTTPConnectionWithTimeout(httplib.HTTPConnection):
    """An HTTPConnection replacement with added support for setting a timeout on all blocking operations.

    Older versions of Python (2.4, 2.5) do not allow for setting a timeout directly on httplib.HTTPConnection
    objects.  This is meant to solve that problem generally.
    """
    def __init__(self, host, port, timeout):
        self.__timeout = timeout
        httplib.HTTPConnection.__init__(self, host, port)

    def connect(self):
        # This method is essentially copied from 2.7's httplib.HTTPConnection.connect.
        # If socket.create_connection then we use it (as it does in newer Pythons), otherwise, rely on our
        # own way of doing it.
        if hasattr(socket, 'create_connection'):
            self.sock = socket.create_connection((self.host, self.port), self.__timeout)
        else:
            self.sock = create_connection_helper(self.host, self.port, timeout=self.__timeout)
        if hasattr(self, '_tunnel_host') and self._tunnel_host:
            self._tunnel()


class HTTPSConnectionWithTimeoutAndVerification(httplib.HTTPSConnection):
    """An HTTPSConnection replacement that adds support for setting a timeout as well as performing server
    certificate validation.

    Older versions of Python (2.4, 2.5) do not allow for setting a timeout directly on httplib.HTTPConnection
    objects, nor do they perform validation of the server certificate.  However, if the user installs the ssl
    Python library, then it is possible to perform server certificate validation even on Python 2.4, 2.5.  This
    class implements the necessary support.
    """
    def __init__(self, host, port, timeout, ca_file, has_ssl):
        """
        Creates an instance.

        Params:
            host: The server host to connect to.
            port: The port to connect to.
            timeout: The timeout, in seconds, to use for all blocking operations on the underlying socket.
            ca_file:  If not None, then this is a file containing the certificate authority's root cert to use
                for validating the certificate sent by the server.  This must be None if has_ssl is False.
                If None is passed in, then no validation of the server certificate will be done whatsoever, so
                you will be susceptible to man-in-the-middle attacks.  However, at least your traffic will be
                encrypted.
            has_ssl:  True if the ssl Python library is available.
        """
        if not has_ssl and ca_file is not None:
            raise Exception('If has_ssl is false, you are not allowed to specify a ca_file because it has no affect.')
        self.__timeout = timeout
        self.__ca_file = ca_file
        self.__has_ssl = has_ssl
        httplib.HTTPSConnection.__init__(self, host, port)

    def connect(self):
        # If the ssl library is not available, then we just have to fall back on old HTTPSConnection.connect
        # method.  There are too many dependencies to implement it directly here.
        if not self.__has_ssl:
            # Unfortunately, the only way to set timeout is to temporarily set the global default timeout
            # for what it should be for this connection, and then reset it once the connection is established.
            # Messy, but not much we can do.
            old_timeout = None
            try:
                old_timeout = socket.getdefaulttimeout()
                socket.setdefaulttimeout(self.__timeout)
                httplib.HTTPSConnection.connect(self)
                return
            finally:
                socket.setdefaulttimeout(old_timeout)

        # Create the underlying socket.  Prefer Python's newer socket.create_connection method if it is available.
        if hasattr(socket, 'create_connection'):
            self.sock = socket.create_connection((self.host, self.port), self.__timeout)
        else:
            self.sock = create_connection_helper(self.host, self.port, timeout=self.__timeout)

        if hasattr(self, '_tunnel_host') and self._tunnel_host:
            self._tunnel()

        # Now ask the ssl library to wrap the socket and verify the server certificate if we have a ca_file.
        if self.__ca_file is not None:
            self.sock = ssl.wrap_socket(self.sock, ca_certs=self.__ca_file, cert_reqs=ssl.CERT_REQUIRED)
        else:
            self.sock = ssl.wrap_socket(self.sock, cert_reqs=ssl.CERT_NONE)


def create_connection_helper(host, port, timeout=None, source_address=None):
    """Creates and returns a socket connecting to host:port with the specified timeout.

    @param host: The host to connect to.
    @param port: The port to connect to.
    @param timeout: The timeout in seconds to use for all blocking operations on the socket.
    @param source_address: The source address, or None.

    @return: The connected socket
    """
    # This method was copied from Python 2.7's socket.create_connection.
    err = None
    for res in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        af, socktype, proto, canonname, sa = res
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            if timeout is not None:
                sock.settimeout(timeout)
            if source_address is not None:
                sock.bind(source_address)
            sock.connect(sa)
            return sock

        except socket.error, _:
            err = _
            if sock is not None:
                sock.close()

    if err is not None:
        raise err
    else:
        raise socket.error("getaddrinfo returns an empty list")
