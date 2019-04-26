#!/usr/bin/env python
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
###
# chkconfig: 2345 98 02
# description: Manages the Scalyr Agent 2, which provides log copying
#     and basic system metric collection.
###
### BEGIN INIT INFO
# Provides: scalyr-agent-2
# Required-Start: $network
# Required-Stop: $network
# Default-Start: 2 3 4 5
# Default-Stop: 0 1 6
# Description: Manages the Scalyr Agent 2, which provides log copying
#     and back system metric collection.
### END INIT INFO
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import errno
import gc
import os
import sys
import time

from __scalyr__ import SCALYR_VERSION, scalyr_init

# We must invoke this since we are an executable script.
scalyr_init()

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as scalyr_util
import scalyr_agent.remote_shell as remote_shell

# We have to be careful to set this logger class very early in processing, even before other
# imports to ensure that any loggers created are AgentLoggers.
from scalyr_agent.monitors_manager import MonitorsManager
from scalyr_agent.scalyr_monitor import UnsupportedSystem

# Set up the main logger.  We set it up initially to log to standard out,
# but once we run fork off the daemon, we will use a rotating log file.
log = scalyr_logging.getLogger('scalyr_agent')

scalyr_logging.set_log_destination(use_stdout=True)


from optparse import OptionParser

from scalyr_agent.scalyr_client import ScalyrClientSession
from scalyr_agent.copying_manager import CopyingManager
from scalyr_agent.configuration import Configuration
from scalyr_agent.util import RunState, ScriptEscalator
from scalyr_agent.agent_status import AgentStatus
from scalyr_agent.agent_status import ConfigStatus
from scalyr_agent.agent_status import OverallStats
from scalyr_agent.agent_status import report_status
from scalyr_agent.platform_controller import PlatformController, AgentAlreadyRunning, CannotExecuteAsUser
from scalyr_agent.platform_controller import AgentNotRunning

STATUS_FILE = 'last_status'


def _update_disabled_until( config_value, current_time ):
    if config_value is not None:
        return config_value + current_time
    else:
        return current_time

def _check_disabled( current_time, other_time, message ):
    result = (current_time < other_time)
    if result:
        log.log( scalyr_logging.DEBUG_LEVEL_0, "%s disabled for %d more seconds" % (message, other_time - current_time) )
    return result

class ScalyrAgent(object):
    """Encapsulates the entire Scalyr Agent 2 application.
    """
    def __init__(self, platform_controller):
        """Initialize the object.

        @param platform_controller:  The controller for this platform.
        @type platform_controller: PlatformController
        """
        # NOTE:  This abstraction is not thread safe, but it does not need to be.  Even the calls to
        # create the status file are always issued on the main thread since that's how signals are handled.

        # The current config being used to run the agent.  This may not be the latest
        # version of the config, if that latest version had parsing errors.
        self.__config = None
        # The platform-specific controller that does things like fork daemon processes, sleeps, etc.
        self.__controller = platform_controller
        # A helper for running this script as another user if need be.
        self.__escalator = None

        # The DefaultPaths object for defining the default paths for various things like the log directory based on
        # the platform.
        self.__default_paths = platform_controller.default_paths

        self.__config_file_path = None
        # If the current contents of the configuration file has errors in it, then this will be set to the config
        # object produced by reading it.
        self.__current_bad_config = None
        # The last time the configuration file was checked to see if it had changed.
        self.__last_config_check_time = None
        self.__start_time = None
        # The path where the agent log file is being written.
        self.__log_file_path = None
        # The current copying manager.
        self.__copying_manager = None
        # The current monitors manager.
        self.__monitors_manager = None
        # The current ScalyrClientSession to use for sending requests.
        self.__scalyr_client = None

        # Tracks whether or not the agent should still be running.  When a terminate signal is received,
        # the run state is set to false.  Threads are expected to notice this and finish as quickly as
        # possible.
        self.__run_state = None

        # Whether or not the unsafe debugging mode is running (meaning the RemoteShell is accepting connections
        # on the local host port and the memory profiler is turned on).  Note, this mode is very unsafe since
        # arbitrary python commands can be executed by any user on the system as the user running the agent.
        self.__unsafe_debugging_running = False
        # A reference to the remote shell debug server.
        self.__debug_server = None
        # Used below for a small cache for a slight optimization.
        self.__last_verify_config = None

    @staticmethod
    def agent_run_method(controller, config_file_path, perform_config_check=False):
        """Begins executing the agent service on the current thread.

        This will not return until the service is requested to terminate.

        This method can be used as an entry point by PlatformControllers that cannot invoke the ``agent_run_method``
        argument passed in the ``start_agent_service`` method.  It immediately because execution of the service.

        @param controller: The controller to use to run the service.
        @param config_file_path: The path to the configuration file to use.
        @param perform_config_check:  If true, will check common configuration errors such as forgetting to
            provide an api token and raise an exception if they fail.

        @type controller: PlatformController
        @type config_file_path: str
        @type perform_config_check: bool

        @return: The return code when the agent exits.
        @rtype: int
        """
        class Options(object):
            pass

        my_options = Options()
        my_options.quiet = True
        my_options.verbose = False
        my_options.no_fork = True
        my_options.no_change_user = True
        my_options.no_check_remote = False

        if perform_config_check:
            command = 'inner_run_with_checks'
        else:
            command = 'inner_run'
        try:
            return ScalyrAgent(controller).main(config_file_path, command, my_options)
        except:
            log.exception('Agent failed while running.  Will be shutting down.')
            raise

    def main(self, config_file_path, command, command_options):
        """Run the Scalyr Agent.

        @param config_file_path: The path to the configuration file.
        @param command: The command passed in at the commandline for the agent to execute, such as 'start', 'stop', etc.
        @param command_options: The options from the commandline.  These will include 'quiet', 'verbose', etc.

        @type config_file_path: str
        @type command: str

        @return:  The exit status code to exit with, such as 0 for success.
        @rtype: int
        """
        quiet = command_options.quiet
        verbose = command_options.verbose
        no_fork = command_options.no_fork
        no_check_remote = False

        # We process for the 'version' command early since we do not need the configuration file for it.
        if command == 'version':
            print 'The Scalyr Agent 2 version is %s' % SCALYR_VERSION
            return 0

        # Read the configuration file.  Fail if we can't read it, unless the command is stop or status.
        if config_file_path is None:
            config_file_path = self.__default_paths.config_file_path

        self.__config_file_path = config_file_path

        try:
            self.__config = self.__read_and_verify_config(config_file_path)

            # check if not a tty and override the no check remote variable
            if not sys.stdout.isatty():
                no_check_remote = not self.__config.check_remote_if_no_tty
        except Exception, e:
            # We ignore a bad configuration file for 'stop' and 'status' because sometimes you do just accidentally
            # screw up the config and you want to let the rest of the system work enough to do the stop or get the
            # status.
            if command != 'stop' and command != 'status':
                raise Exception('Error reading configuration file: %s\n'
                                'Terminating agent, please fix the configuration file and restart agent.' % str(e))
            else:
                self.__config = None
                print >> sys.stderr, 'Could not parse configuration file at \'%s\'' % config_file_path

        self.__controller.consume_config(self.__config, config_file_path)

        self.__escalator = ScriptEscalator(self.__controller, config_file_path, os.getcwd(),
                                           command_options.no_change_user)

        if command_options.no_check_remote is not None:
            no_check_remote = True

        # noinspection PyBroadException
        try:
            # Execute the command.
            if command == 'start':
                return self.__start(quiet, no_fork, no_check_remote)
            elif command == 'inner_run_with_checks':
                self.__perform_config_checks(no_check_remote)
                return self.__run(self.__controller)
            elif command == 'inner_run':
                return self.__run(self.__controller)
            elif command == 'stop':
                return self.__stop(quiet)
            elif command == 'status' and not verbose:
                return self.__status()
            elif command == 'status' and verbose:
                if self.__config is not None:
                    agent_data_path = self.__config.agent_data_path
                else:
                    agent_data_path = self.__default_paths.agent_data_path
                    print >> sys.stderr, 'Assuming agent data path is \'%s\'' % agent_data_path
                return self.__detailed_status(agent_data_path)
            elif command == 'restart':
                return self.__restart(quiet, no_fork, no_check_remote)
            elif command == 'condrestart':
                return self.__condrestart(quiet, no_fork, no_check_remote)
            else:
                print >> sys.stderr, 'Unknown command given: "%s".' % command
                return 1
        except SystemExit:
            return 0
        except Exception, e:
            # We special case the inner_run_with checks since we know that exception is human-readable.
            if command == 'inner_run_with_checks':
                raise e
            else:
                raise Exception('Caught exception when attempt to execute command %s.  Exception was %s' %
                                (command, str(e)))

    def __read_and_verify_config(self, config_file_path):
        """Reads the configuration and verifies it can be successfully parsed including the monitors existing and
        having valid configurations.

        @param config_file_path: The path to read the configuration from.
        @type config_file_path: str

        @return: The configuration object.
        @rtype: scalyr_agent.Configuration
        """
        config = self.__make_config(config_file_path)
        self.__verify_config(config)
        return config

    def __make_config(self, config_file_path):
        """Make Configuration object. Does not read nor verify.

        You must call ``__verify_config`` to read and fully verify the configuration.

        @param config_file_path: The path to read the configuration from.
        @type config_file_path: str

        @return: The configuration object.
        @rtype: scalyr_agent.Configuration
        """
        return Configuration(config_file_path, self.__default_paths, log)

    def __verify_config(self, config, disable_create_monitors_manager=False,
                                      disable_create_copying_manager=False,
                                      disable_cache_config=False):
        """Verifies the passed-in configuration object is valid, and that the referenced monitors exist and have
        valid configuration.

        @param config: The configuration object.
        @type config: scalyr_agent.Configuration
        @return: A boolean value indicating whether or not the configuration was fully verified
        """
        try:
            config.parse()

            if disable_create_monitors_manager:
                log.info( "verify_config - creation of monitors manager disabled" )
                return False

            monitors_manager = MonitorsManager(config, self.__controller)

            if disable_create_copying_manager:
                log.info( "verify_config - creation of copying manager disabled" )
                return False

            copying_manager = CopyingManager(config, monitors_manager.monitors)
            # To do the full verification, we have to create the managers.  However, this call does not need them,
            # but it is very likely the caller of this method will invoke ``__create_worker_thread`` next, so let's
            # save them for that call.  This helps us avoid having to read and instantiate the monitors multiple times.
            if disable_cache_config:
                log.info( "verify_config - not caching verify_config results" )
                self.__last_verify_config = None
                # return true here because config is verified, just not cached
                # this means the rest of the loop will continue but the config
                # will be verified again when the worker thread is created
                return True

            self.__last_verify_config = {
                'config': config,
                'monitors_manager': monitors_manager,
                'copying_manager': copying_manager
            }
        except UnsupportedSystem, e:
            # We want to emit a better error message for this exception, so capture it here.
            raise Exception('Configuration file uses a monitor that is not supported on this system Monitor \'%s\' '
                            'cannot be used due to: %s.  If you require support for this monitor for your system, '
                            'please e-mail contact@scalyr.com' % (e.monitor_name, str(e)))
        return True

    def __create_worker_thread(self, config):
        """Creates the worker thread that will run the copying and monitor managers for the specified configuration.

        @param config: The configuration object.
        @type config: scalyr_agent.Configuration

        @return: The worker thread object to use.  You must start it.
        @rtype: WorkerThread
        """
        # Use the cached results from __last_verify_config if available.  If not, force it to create them.
        if self.__last_verify_config is None or self.__last_verify_config['config'] is not config:
            self.__verify_config(config)
        return WorkerThread(self.__last_verify_config['config'], self.__last_verify_config['copying_manager'],
                            self.__last_verify_config['monitors_manager'])

    def __perform_config_checks(self, no_check_remote):
        """Perform checks for common configuration errors.  Raises an exception with a human-readable message
        if any of the checks fail.

        In particular, this checks if (1) the user has actually entered an api_key, (2) the agent process can
        write to the logs directory, (3) we can send a request to the the configured scalyr server
        and (4) the api key is correct.
        """
        # Make sure the user has set an API key... a common step that can be forgotten.
        # If they haven't set it, it will have REPLACE_THIS as the value since that's what is in the template.
        if self.__config.api_key == 'REPLACE_THIS' or self.__config.api_key == '':
            raise Exception('Error, you have not set a valid api key in the configuration file.\n'
                            'Edit the file %s and replace the value for "api_key" with a valid logs '
                            'write key for your account.\n'
                            'You can see your write logs keys at https://www.scalyr.com/keys' %
                            self.__config.file_path)

        self.__verify_can_write_to_logs_and_data(self.__config)

        # Send a test message to the server to make sure everything works.  If not, print a decent error message.
        if not no_check_remote:
            client = self.__create_client(quiet=True)
            try:
                ping_result = client.ping()
                if ping_result != 'success':
                    if 'badClientClockSkew' in ping_result:
                        # TODO:  The server does not yet send this error message, but it will in the future.
                        raise Exception('Sending request to the server failed due to bad clock skew.  The system clock '
                                        'on this host is too off from actual time.  Please fix the clock and try to '
                                        'restart the agent.')
                    elif 'invalidApiKey' in ping_result:
                        # TODO:  The server does not yet send this error message, but it will in the future.
                        raise Exception('Sending request to the server failed due to an invalid API key.  This probably '
                                        'means the \'api_key\' field in configuration file  \'%s\' is not correct.  '
                                        'Please visit https://www.scalyr.com/keys and copy a Write Logs key into the '
                                        '\'api_key\' field in the configuration file' % self.__config.file_path)
                    else:
                        raise Exception('Failed to send request to the server.  The server address could be wrong, '
                                        'there maybe a network connectivity issue, or the provided api_token could be '
                                        'incorrect.  You can disable this check with --no-check-remote-server.')
            finally:
                client.close()

    def __start(self, quiet, no_fork, no_check_remote):
        """Executes the start command.

        This will perform some initial checks to see if the agent can be started, such as making sure it can
        read and write to the logs and data directory, and that it can send a successful message to the
        Scalyr servers (therefore verifying the authentication token is correct.)

        After it determines that the agent is likely to be able to run, it will start the real agent.  If no_fork
        is False, then a new process will be started in the background and this method will return.  Otherwise,
        this method will not return.

        @param quiet: True if output should be kept to a minimal and only record errors that occur.
        @param no_fork: True if this method should not fork a separate process to run the agent, but run it
            directly instead.  If it is False, then a daemon process will be forked and will run the agent.
        @param no_check_remote:  True if this method should not try to contact the remote Scalyr servers to
            verify connectivity.  If it does try to contact the remote servers and it cannot connect, then
            the script exits with a failure.
        @type quiet: bool
        @type no_fork: bool
        @type no_check_remote: bool

        @return:  The exit status code for the process.
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            return self.__escalator.change_user_and_rerun_script('start the scalyr agent')

        # Make sure we do not try to start it up again.
        self.__fail_if_already_running()

        # noinspection PyBroadException
        try:
            self.__perform_config_checks(no_check_remote)
        except Exception, e:
            print >> sys.stderr
            print >> sys.stderr, '%s' % str(e)
            print >> sys.stderr, 'Terminating agent, please fix the error and restart the agent.'
            return 1

        if not no_fork:
            # Do one last check to just cut down on the window of race conditions.
            self.__fail_if_already_running()

            if not quiet:
                if no_check_remote:
                    print "Configuration verified, starting agent in background."
                else:
                    print "Configuration and server connection verified, starting agent in background."
            self.__controller.start_agent_service(self.__run, quiet, fork=True)
        else:
            self.__controller.start_agent_service(self.__run, quiet, fork=False)

        return 0

    def __handle_terminate(self):
        """Invoked when the process is requested to shutdown, such as by a signal"""
        if self.__run_state.is_running():
            log.info('Received signal to shutdown, attempt to shutdown cleanly.')
            self.__run_state.stop()

    def __detailed_status(self, data_directory):
        """Execute the status -v command.

        This will request the current agent to dump its detailed status to a file in the data directory, which
        this process will then read.

        @param data_directory: The path to the data directory.
        @type data_directory: str

        @return:  An exit status code for the status command indicating success or failure.
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            try:
                return self.__escalator.change_user_and_rerun_script('retrieved detailed status', handle_error=False)
            except CannotExecuteAsUser:
                # For now, we just ignore the error and try to get the status anyway.  This might work on Linux
                # platforms depending on permissions.  This is legacy behavior.
                pass

        try:
            self.__controller.is_agent_running(fail_if_not_running=True)
        except AgentNotRunning, e:
            print 'The agent does not appear to be running.'
            print "%s" % str(e)
            return 1

        # The status works by sending telling the running agent to dump the status into a well known file and
        # then we read it from there, echoing it to stdout.
        if not os.path.isdir(data_directory):
            print >> sys.stderr, ('Cannot get status due to bad config.  The data path "%s" is not a directory' %
                                  data_directory)
            return 1

        status_file = os.path.join(data_directory, STATUS_FILE)

        # This users needs to zero out the current status file (if it exists), so they need write access to it.
        # When we do create the status file, we give everyone read/write access, so it should not be an issue.
        if os.path.isfile(status_file) and not os.access(status_file, os.W_OK):
            print >> sys.stderr, ('Cannot get status due to insufficient permissions.  The current user does not '
                                  'have write access to "%s" as required.' % status_file)
            return 1

        # Zero out the current file so that we can detect once the agent process has updated it.
        if os.path.isfile(status_file):
            f = file(status_file, 'w')
            f.truncate(0)
            f.close()

        # Signal to the running process.  This should cause that process to write to the status file
        result = self.__controller.request_agent_status()
        if result is not None:
            if result == errno.ESRCH:
                print >> sys.stderr, 'The agent does not appear to be running.'
                return 1
            elif result == errno.EPERM:
                # TODO:  We probably should just get the name of the user running the agent and output it
                # here, instead of hard coding it to root.
                print >> sys.stderr, ('To view agent status, you must be running as the same user as the agent. '
                                      'Try running this command as root or Administrator.')
                return 2

        # We wait for five seconds at most to get the status.
        deadline = time.time() + 5

        # Now loop until we see it show up.
        while True:
            if os.path.isfile(status_file) and os.path.getsize(status_file) > 0:
                break

            if time.time() > deadline:
                if self.__config is not None:
                    agent_log = os.path.join(self.__config.agent_log_path, 'agent.log')
                else:
                    agent_log = os.path.join(self.__default_paths.agent_log_path, 'agent.log')
                print >> sys.stderr, ('Failed to get status within 5 seconds.  Giving up.  The agent process is '
                                      'possibly stuck.  See %s for more details.' % agent_log)
                return 1

            time.sleep(0.03)

        if not os.access(status_file, os.R_OK):
            print >> sys.stderr, ('Cannot get status due to insufficient permissions.  The current user does not '
                                  'have read access to "%s" as required.' % status_file)
            return 1

        fp = open(status_file)
        for line in fp:
            print line.rstrip()
        fp.close()

        return 0

    def __stop(self, quiet):
        """Stop the current agent.

        @param quiet: Whether or not only errors should be written to stdout.
        @type quiet: bool

        @return: the exit status code
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            return self.__escalator.change_user_and_rerun_script('stop the scalyr agent')

        try:
            self.__controller.is_agent_running(fail_if_not_running=True)
            status = self.__controller.stop_agent_service(quiet)
            return status
        except AgentNotRunning, e:
            print >> sys.stderr, 'Failed to stop the agent because it does not appear to be running.'
            print >> sys.stderr, "%s" % str(e)
            return 0  # For the sake of restart, we need to return non-error code here.

    def __status(self):
        """Execute the 'status' command to indicate if the agent is running or not.

        @return: The exit status code.  It will return zero only if it is running.
        @rtype: int
        """
        if self.__controller.is_agent_running():
            print 'The agent is running. For details, use "scalyr-agent-2 status -v".'
            return 0
        else:
            print 'The agent does not appear to be running.'
            return 4

    def __condrestart(self, quiet, no_fork, no_check_remote):
        """Execute the 'condrestart' command which will only restart the agent if it is already running.

        @param quiet: True if output should be kept to a minimal and only record errors that occur.
        @param no_fork: True if this method should not fork a separate process to run the agent, but run it
            directly instead.  If it is False, then a daemon process will be forked and will run the agent.
        @param no_check_remote:  True if this method should not try to contact the remote Scalyr servers to
            verify connectivity.  If it does try to contact the remote servers and it cannot connect, then
            the script exits with a failure.

        @type quiet: bool
        @type no_fork: bool
        @type no_check_remote: bool

        @return: the exit status code
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            return self.__escalator.change_user_and_rerun_script('restart the scalyr agent')

        if self.__controller.is_agent_running():
            if not quiet:
                print 'Agent is running, restarting now.'
            if self.__stop(quiet) != 0:
                print >>sys.stderr, 'Failed to stop the running agent.  Cannot restart until it is killed.'
                return 1

            return self.__start(quiet, no_fork, no_check_remote)
        elif not quiet:
            print 'Agent is not running, not restarting.'
            return 0
        else:
            return 0

    def __restart(self, quiet, no_fork, no_check_remote):
        """Execute the 'restart' which will start the agent, stopping the existing agent if it is running.

        @param quiet: True if output should be kept to a minimal and only record errors that occur.
        @param no_fork: True if this method should not fork a separate process to run the agent, but run it
            directly instead.  If it is False, then a daemon process will be forked and will run the agent.
        @param no_check_remote:  True if this method should not try to contact the remote Scalyr servers to
            verify connectivity.  If it does try to contact the remote servers and it cannot connect, then
            the script exits with a failure.

        @type quiet: bool
        @type no_fork: bool
        @type no_check_remote: bool

        @return: the exit status code, zero if it was successfully restarted, non-zero if it was not running or
            could not be started.
        @rtype: int
        """
        # First, see if we have to change the user that is executing this script to match the owner of the config.
        if self.__escalator.is_user_change_required():
            return self.__escalator.change_user_and_rerun_script('restart the scalyr agent')

        if self.__controller.is_agent_running():
            if not quiet:
                print 'Agent is running, stopping it now.'
            if self.__stop(quiet) != 0:
                print >>sys.stderr, 'Failed to stop the running agent.  Cannot restart until it is killed'
                return 1

        return self.__start(quiet, no_fork, no_check_remote)

    def __print_force_https_message( self, scalyr_server, raw_scalyr_server ):
        """Convenience function for printing a message stating whether the scalyr_server was forced to use https"""
        if scalyr_server != raw_scalyr_server:
            log.info( "Forcing https protocol for server url: %s -> %s.  You can prevent this by setting the `allow_http` global config option, but be mindful that there are security implications with doing this, including tramsitting your Scalyr api key over an insecure connection." % (raw_scalyr_server, scalyr_server ) )

    def __run(self, controller):
        """Runs the Scalyr Agent 2.

        This method will not return until a TERM signal is received or a fatal error occurs.

        @param controller The controller that started this agent service.
        @type controller: PlatformController

        @return: the exit status code
        @rtype: int
        """

        self.__start_time = time.time()
        controller.register_for_termination(self.__handle_terminate)

        # Register handler for when we get an interrupt signal.  That indicates we should dump the status to
        # a file because a user has run the 'detailed_status' command.
        self.__controller.register_for_status_requests(self.__report_status_to_file)

        # The stats we track for the lifetime of the agent.  This variable tracks the accumulated stats since the
        # last stat reset (the stats get reset every time we read a new configuration).
        base_overall_stats = OverallStats()
        # We only emit the overall stats once ever ten minutes.  Track when we last reported it.
        last_overall_stats_report_time = time.time()
        # We only emit the bandwidth stats once every minute.  Track when we last reported it.
        last_bw_stats_report_time = last_overall_stats_report_time

        # The thread that runs the monitors and and the log copier.
        worker_thread = None

        try:
            # noinspection PyBroadException
            try:
                self.__run_state = RunState()
                self.__log_file_path = os.path.join(self.__config.agent_log_path, 'agent.log')
                scalyr_logging.set_log_destination(use_disk=True, max_bytes=self.__config.log_rotation_max_bytes,
                                                   backup_count=self.__config.log_rotation_backup_count,
                                                   logs_directory=self.__config.agent_log_path,
                                                   agent_log_file_path='agent.log')

                self.__update_debug_log_level(self.__config.debug_level)

                # We record where the log file currently is so that we can (in the worse case) start copying it
                # from this position.  That way we capture the first 'Starting scalyr agent' call.
                agent_log_position = self.__get_file_initial_position(self.__log_file_path)
                if agent_log_position is not None:
                    logs_initial_positions = {self.__log_file_path: agent_log_position}
                else:
                    logs_initial_positions = None

                log.info('Starting scalyr agent... (version=%s) %s' % (SCALYR_VERSION, scalyr_util.get_pid_tid()))
                log.log(scalyr_logging.DEBUG_LEVEL_1, 'Starting scalyr agent... (version=%s) %s' % (
                    SCALYR_VERSION, scalyr_util.get_pid_tid()))
                self.__controller.emit_init_log(log, self.__config.debug_init)

                self.__start_or_stop_unsafe_debugging()
                log.log(scalyr_logging.DEBUG_LEVEL_0, 'JSON library is %s' % (scalyr_util.get_json_lib()) )

                scalyr_server = self.__config.scalyr_server
                raw_scalyr_server = self.__config.raw_scalyr_server
                self.__print_force_https_message( scalyr_server, raw_scalyr_server )

                self.__scalyr_client = self.__create_client()

                def start_worker_thread(config, logs_initial_positions=None):
                    wt = self.__create_worker_thread(config)
                    # attach callbacks before starting monitors
                    wt.monitors_manager.set_user_agent_augment_callback(self.__scalyr_client.augment_user_agent)
                    wt.start(self.__scalyr_client, logs_initial_positions)
                    return wt, wt.copying_manager, wt.monitors_manager

                worker_thread, self.__copying_manager, self.__monitors_manager = start_worker_thread(self.__config, logs_initial_positions)
                current_time = time.time()

                disable_all_config_updates_until = _update_disabled_until( self.__config.disable_all_config_updates, current_time )
                disable_verify_config_until = _update_disabled_until( self.__config.disable_verify_config, current_time )
                disable_config_equivalence_check_until = _update_disabled_until( self.__config.disable_config_equivalence_check, current_time )
                disable_verify_can_write_to_logs_until = _update_disabled_until( self.__config.disable_verify_can_write_to_logs, current_time )
                disable_config_reload_until = _update_disabled_until( self.__config.disable_config_reload, current_time )
                disable_verify_config_create_monitors_manager_until = _update_disabled_until( self.__config.disable_verify_config_create_monitors_manager, current_time )
                disable_verify_config_create_copying_manager_until = _update_disabled_until( self.__config.disable_verify_config_create_copying_manager, current_time )

                config_change_check_interval = self.__config.config_change_check_interval

                gc_interval = self.__config.garbage_collect_interval
                last_gc_time = current_time

                prev_server = scalyr_server

                while not self.__run_state.sleep_but_awaken_if_stopped( config_change_check_interval ):

                    current_time = time.time()
                    self.__last_config_check_time = current_time

                    if self.__config.disable_overall_stats:
                        log.log( scalyr_logging.DEBUG_LEVEL_0, "overall stats disabled" )
                    else:
                        # Log the overall stats once every 10 mins.
                        if current_time > last_overall_stats_report_time + 600:
                            self.__log_overall_stats(self.__calculate_overall_stats(base_overall_stats))
                            last_overall_stats_report_time = current_time

                    if self.__config.disable_bandwidth_stats:
                        log.log( scalyr_logging.DEBUG_LEVEL_0, "bandwidth stats disabled" )
                    else:
                        # Log the bandwidth-related stats once every minute:
                        if current_time > last_bw_stats_report_time + 60:
                            self.__log_bandwidth_stats(self.__calculate_overall_stats(base_overall_stats))
                            last_bw_stats_report_time = current_time

                    log.log(scalyr_logging.DEBUG_LEVEL_1, 'Checking for any changes to config file')
                    new_config = None
                    try:
                        if _check_disabled( current_time, disable_all_config_updates_until, "all config updates" ):
                            continue

                        new_config = self.__make_config(self.__config_file_path)
                        # TODO:  By parsing the configuration file, we are doing a lot of work just to have it thrown
                        # out in a few seconds when we discover it is equivalent to the previous one.  Maybe we should
                        # rework the equivalence so that it can work on the raw files, but this is difficult since
                        # we need to parse the main configuration file to at least get the fragment directory.  For
                        # now, we will just wait this work.  We only do it once every 30 secs anyway.

                        if _check_disabled( current_time, disable_verify_config_until, "verify config" ):
                            continue

                        disable_create_monitors_manager=_check_disabled( current_time, disable_verify_config_create_monitors_manager_until, "verify config create monitors manager" )
                        disable_create_copying_manager=_check_disabled( current_time, disable_verify_config_create_copying_manager_until, "verify config create copying manager" )
                        disable_cache_config=self.__config.disable_verify_config_cache_config
                        verified = self.__verify_config(new_config,
                                                        disable_create_monitors_manager=disable_create_monitors_manager,
                                                        disable_create_copying_manager=disable_create_copying_manager,
                                                        disable_cache_config=disable_cache_config
                                                       )

                        # Skip the rest of the loop if the config wasn't fully verified because
                        # later code relies on the config being fully validated
                        if not verified:
                            continue

                        if self.__config.disable_update_debug_log_level:
                            log.log( scalyr_logging.DEBUG_LEVEL_0, "update debug_log_level disabled" )
                        else:
                            # Update the debug_level based on the new config.. we always update it.
                            self.__update_debug_log_level(new_config.debug_level)

                        # see if we need to perform a garbage collection
                        if gc_interval > 0 and current_time > (last_gc_time + gc_interval):
                            gc.collect()
                            last_gc_time = current_time

                        if _check_disabled( current_time, disable_config_equivalence_check_until, "config equivalence check" ):
                            continue

                        if self.__current_bad_config is None and new_config.equivalent(self.__config,
                                                                                       exclude_debug_level=True):
                            log.log(scalyr_logging.DEBUG_LEVEL_1, 'Config was not different than previous')
                            continue

                        if _check_disabled( current_time, disable_verify_can_write_to_logs_until, "verify check for writing to logs and data" ):
                            continue

                        self.__verify_can_write_to_logs_and_data(new_config)

                    except Exception, e:
                        if self.__current_bad_config is None:
                            log.error(
                                'Bad configuration file seen.  Ignoring, using last known good configuration file.  '
                                'Exception was "%s"', str(e), error_code='badConfigFile')
                        self.__current_bad_config = new_config
                        log.log(scalyr_logging.DEBUG_LEVEL_1, 'Config could not be read or parsed')
                        continue

                    if _check_disabled( current_time, disable_config_reload_until, "config reload" ):
                        continue

                    log.log(scalyr_logging.DEBUG_LEVEL_1, 'Config was different than previous.  Reloading.')
                    # We are about to reset the current workers and ScalyrClientSession, so we will lose their
                    # contribution to the stats, so recalculate the base.
                    base_overall_stats = self.__calculate_overall_stats(base_overall_stats)
                    log.info('New configuration file seen.')
                    log.info('Stopping copying and metrics threads.')
                    worker_thread.stop()

                    worker_thread = None

                    self.__config = new_config
                    self.__controller.consume_config(new_config, new_config.file_path)

                    self.__start_or_stop_unsafe_debugging()

                    # get the server and the raw server to see if we forced https
                    scalyr_server = self.__config.scalyr_server
                    raw_scalyr_server = self.__config.raw_scalyr_server

                    # only print a message if this is the first time we have seen this scalyr_server
                    # and the server field is different from the raw server field
                    if scalyr_server != prev_server:
                        self.__print_force_https_message( scalyr_server, raw_scalyr_server )

                    prev_server = scalyr_server

                    self.__scalyr_client = self.__create_client()

                    log.info('Starting new copying and metrics threads')
                    worker_thread, self.__copying_manager, self.__monitors_manager = start_worker_thread(new_config)


                    self.__current_bad_config = None
                    config_change_check_interval = self.__config.config_change_check_interval
                    gc_interval = self.__config.garbage_collect_interval

                    disable_all_config_updates_until = _update_disabled_until( self.__config.disable_all_config_updates, current_time )
                    disable_verify_config_until = _update_disabled_until( self.__config.disable_verify_config, current_time )
                    disable_config_equivalence_check_until = _update_disabled_until( self.__config.disable_config_equivalence_check, current_time )
                    disable_verify_can_write_to_logs_until = _update_disabled_until( self.__config.disable_verify_can_write_to_logs, current_time )
                    disable_config_reload_until = _update_disabled_until( self.__config.disable_config_reload, current_time )
                    disable_verify_config_create_monitors_manager_until = _update_disabled_until( self.__config.disable_verify_config_create_monitors_manager, current_time )
                    disable_verify_config_create_copying_manager_until = _update_disabled_until( self.__config.disable_verify_config_create_copying_manager, current_time )

                # Log the stats one more time before we terminate.
                self.__log_overall_stats(self.__calculate_overall_stats(base_overall_stats))

            except Exception:
                log.exception('Main run method for agent failed due to exception', error_code='failedAgentMain')
        finally:
            if worker_thread is not None:
                worker_thread.stop()

    def __fail_if_already_running(self):
        """If the agent is already running, prints an appropriate error message and exits the process.
        """
        try:
            self.__controller.is_agent_running(fail_if_running=True)
        except AgentAlreadyRunning, e:
            print >> sys.stderr, 'Failed to start agent because it is already running.'
            print >> sys.stderr, "%s" % str(e)
            sys.exit(4)

    def __update_debug_log_level(self, debug_level):
        """Updates the debug log level of the agent.
        @param debug_level: The debug level, ranging from 0 (no debug) to 5.

        @type debug_level: int
        """
        levels = [scalyr_logging.DEBUG_LEVEL_0, scalyr_logging.DEBUG_LEVEL_1, scalyr_logging.DEBUG_LEVEL_2,
                  scalyr_logging.DEBUG_LEVEL_3, scalyr_logging.DEBUG_LEVEL_4, scalyr_logging.DEBUG_LEVEL_5]

        scalyr_logging.set_log_level(levels[debug_level])

    def __create_client(self, quiet=False):
        """Creates and returns a new client to the Scalyr servers.

        @param quiet: If true, only errors should be written to stdout.
        @type quiet: bool

        @return: The client to use for sending requests to Scalyr, using the server address and API write logs
            key in the configuration file.
        @rtype: ScalyrClientSession
        """
        if self.__config.verify_server_certificate:
            ca_file = self.__config.ca_cert_path
        else:
            ca_file = None
        use_requests_lib = self.__config.use_requests_lib
        return ScalyrClientSession(self.__config.scalyr_server, self.__config.api_key, SCALYR_VERSION, quiet=quiet,
                                   request_deadline=self.__config.request_deadline, ca_file=ca_file,
                                   use_requests_lib=use_requests_lib, compression_type=self.__config.compression_type,
                                   compression_level=self.__config.compression_level,
                                   proxies=self.__config.network_proxies,
                                   disable_send_requests=self.__config.disable_send_requests)

    def __get_file_initial_position(self, path):
        """Returns the file size for the specified file.

        @param path: The path of the file
        @type path: str

        @return: The file size
        @rtype: int
        """
        try:
            return os.path.getsize(path)
        except OSError, e:
            if e.errno == errno.EPERM:
                log.warn('Insufficient permissions to read agent logs initial position')
                return None
            elif e.errno == errno.ENOENT:
                # If file doesn't exist, just return 0 as its initial position
                return 0
            else:
                log.exception('Error trying to read agent logs initial position')
                return None

    def __verify_can_write_to_logs_and_data(self, config):
        """Checks to make sure the user account running the agent has permission to read and write files
        to the log and data directories as specified in the config.

        If any verification fails, an exception is raised.

        @param config: The configuration
        @type config: Configuration
        """
        if not os.path.isdir(config.agent_log_path):
            raise Exception('The agent log directory \'%s\' does not exist.' % config.agent_log_path)

        if not os.access(config.agent_log_path, os.W_OK):
            raise Exception('User cannot write to agent log directory \'%s\'.' % config.agent_log_path)

        if not os.path.isdir(config.agent_data_path):
            raise Exception('The agent data directory \'%s\' does not exist.' % config.agent_data_path)

        if not os.access(config.agent_data_path, os.W_OK):
            raise Exception('User cannot write to agent data directory \'%s\'.' % config.agent_data_path)

    def __start_or_stop_unsafe_debugging(self):
        """Starts or stops the debugging tool.

        This runs a thread that listens to a server port and connects any incoming connection to a shell
        that can be used to execute Python commands to investigate issues on the live server.

        Since opening up a socket is dangerous, we control this with a configuration option and only use it
        when really needed.
        """
        should_be_running = self.__config.use_unsafe_debugging

        if should_be_running and not self.__unsafe_debugging_running:
            self.__unsafe_debugging_running = True
            self.__debug_server = remote_shell.DebugServer()
            self.__debug_server.start()
        elif not should_be_running and self.__unsafe_debugging_running:
            if self.__debug_server is not None:
                self.__debug_server.stop()
                self.__debug_server = None
            self.__unsafe_debugging_running = False

    def __generate_status(self):
        """Generates the server status object and returns it.

        The returned status object is used to create the detailed status page.

        @return: The status object filled in with the values from the current agent.
        @rtype: AgentStatus
        """
        # Basic agent stats first.
        result = AgentStatus()
        result.launch_time = self.__start_time
        result.user = self.__controller.get_current_user()
        result.version = SCALYR_VERSION
        result.server_host = self.__config.server_attributes['serverHost']
        result.scalyr_server = self.__config.scalyr_server
        result.log_path = self.__log_file_path

        # Describe the status of the configuration file.
        config_result = ConfigStatus()
        result.config_status = config_result

        config_result.last_check_time = self.__last_config_check_time
        if self.__current_bad_config is not None:
            config_result.path = self.__current_bad_config.file_path
            config_result.additional_paths = list(self.__current_bad_config.additional_file_paths)
            config_result.last_read_time = self.__current_bad_config.read_time
            config_result.status = 'Error, using last good configuration'
            config_result.last_error = self.__current_bad_config.last_error
            config_result.last_good_read = self.__config.read_time
            config_result.last_check_time = self.__last_config_check_time
        else:
            config_result.path = self.__config.file_path
            config_result.additional_paths = list(self.__config.additional_file_paths)
            config_result.last_read_time = self.__config.read_time
            config_result.status = 'Good'
            config_result.last_error = None
            config_result.last_good_read = self.__config.read_time

        # Include the copying and monitors status.
        if self.__copying_manager is not None:
            result.copying_manager_status = self.__copying_manager.generate_status()
        if self.__monitors_manager is not None:
            result.monitor_manager_status = self.__monitors_manager.generate_status()

        return result

    def __log_overall_stats(self, overall_stats):
        """Logs the agent_status message that we periodically write to the agent log to give overall stats.

        This includes such metrics as the number of logs being copied, the total bytes copied, the number of
        running monitors, etc.

        @param overall_stats: The overall stats for the agent.
        @type overall_stats: OverallStats
        """
        stats = overall_stats
        log.info('agent_status launch_time="%s" version="%s" watched_paths=%ld copying_paths=%ld total_bytes_copied=%ld'
                 ' total_bytes_skipped=%ld total_bytes_subsampled=%ld total_redactions=%ld total_bytes_failed=%ld '
                 'total_copy_request_errors=%ld total_monitor_reported_lines=%ld running_monitors=%ld dead_monitors=%ld'
                 ' user_cpu_=%f system_cpu=%f ram_usage=%ld' % (scalyr_util.format_time(stats.launch_time),
                                                                stats.version, stats.num_watched_paths,
                                                                stats.num_copying_paths, stats.total_bytes_copied,
                                                                stats.total_bytes_skipped, stats.total_bytes_subsampled,
                                                                stats.total_redactions, stats.total_bytes_failed,
                                                                stats.total_copy_requests_errors,
                                                                stats.total_monitor_reported_lines,
                                                                stats.num_running_monitors,
                                                                stats.num_dead_monitor, stats.user_cpu,
                                                                stats.system_cpu, stats.rss_size))

    def __log_bandwidth_stats(self, overall_stats):
        """Logs the agent_requests message that we periodically write to the agent log to give overall request
        stats.

        This includes such metrics the total bytes sent and received, failed requests, etc.

        @param overall_stats: The overall stats for the agent.
        @type overall_stats: OverallStats
        """
        stats = overall_stats
        # Ok, this is cheating, but we are going to hide some debug information in this line when it is turned on.
        if self.__config.debug_init:
            extra = ' is_agent=%d' % self.__controller.is_agent()
        else:
            extra = ''

        log.info('agent_requests requests_sent=%ld requests_failed=%ld bytes_sent=%ld compressed_bytes_sent=%ld bytes_received=%ld '
                 'request_latency_secs=%lf connections_created=%ld%s' % (stats.total_requests_sent,
                                                                         stats.total_requests_failed,
                                                                         stats.total_request_bytes_sent,
                                                                         stats.total_compressed_request_bytes_sent,
                                                                         stats.total_response_bytes_received,
                                                                         stats.total_request_latency_secs,
                                                                         stats.total_connections_created, extra))

    def __calculate_overall_stats(self, base_overall_stats):
        """Return a newly calculated overall stats for the agent.

        This will calculate the latest stats based on the running agent.  Since most stats only can be
        calculated since the last time the configuration file changed and was read, we need to seperately
        track the accumulated stats that occurred before the last config change.

        @param base_overall_stats: The accummulated stats from before the last config change.
        @type base_overall_stats: OverallStats

        @return:  The combined stats
        @rtype: OverallStats
        """
        current_status = self.__generate_status()

        delta_stats = OverallStats()

        watched_paths = 0
        copying_paths = 0

        # Accumulate all the stats from the running processors that are copying log files.
        if current_status.copying_manager_status is not None:
            delta_stats.total_copy_requests_errors = current_status.copying_manager_status.total_errors
            watched_paths = len(current_status.copying_manager_status.log_matchers)
            for matcher in current_status.copying_manager_status.log_matchers:
                copying_paths += len(matcher.log_processors_status)
                for processor_status in matcher.log_processors_status:
                    delta_stats.total_bytes_copied += processor_status.total_bytes_copied
                    delta_stats.total_bytes_skipped += processor_status.total_bytes_skipped
                    delta_stats.total_bytes_subsampled += processor_status.total_bytes_dropped_by_sampling
                    delta_stats.total_bytes_failed += processor_status.total_bytes_failed
                    delta_stats.total_redactions += processor_status.total_redactions

        running_monitors = 0
        dead_monitors = 0

        if current_status.monitor_manager_status is not None:
            running_monitors = current_status.monitor_manager_status.total_alive_monitors
            dead_monitors = len(current_status.monitor_manager_status.monitors_status) - running_monitors
            for monitor_status in current_status.monitor_manager_status.monitors_status:
                delta_stats.total_monitor_reported_lines += monitor_status.reported_lines
                delta_stats.total_monitor_errors += monitor_status.errors

        delta_stats.total_requests_sent = self.__scalyr_client.total_requests_sent
        delta_stats.total_requests_failed = self.__scalyr_client.total_requests_failed
        delta_stats.total_request_bytes_sent = self.__scalyr_client.total_request_bytes_sent
        delta_stats.total_compressed_request_bytes_sent = self.__scalyr_client.total_compressed_request_bytes_sent
        delta_stats.total_response_bytes_received = self.__scalyr_client.total_response_bytes_received
        delta_stats.total_request_latency_secs = self.__scalyr_client.total_request_latency_secs
        delta_stats.total_connections_created = self.__scalyr_client.total_connections_created

        # Add in the latest stats to the stats before the last restart.
        result = delta_stats + base_overall_stats

        # Overwrite some of the stats that are not affected by the add operation.
        result.launch_time = current_status.launch_time
        result.version = current_status.version
        result.num_watched_paths = watched_paths
        result.num_copying_paths = copying_paths
        result.num_running_monitors = running_monitors
        result.num_dead_monitors = dead_monitors

        (result.user_cpu, result.system_cpu, result.rss_size) = self.__controller.get_usage_info()

        return result

    def __report_status_to_file(self):
        """Handles the signal sent to request this process write its current detailed status out."""
        tmp_file = None
        try:
            # We do a little dance to write the status.  We write it to a temporary file first, and then
            # move it into the real location after the write has finished.  This way, the process watching
            # the file we are writing does not accidentally read it when it is only partially written.
            tmp_file_path = os.path.join(self.__config.agent_data_path, 'last_status.tmp')
            final_file_path = os.path.join(self.__config.agent_data_path, 'last_status')

            if os.path.isfile(final_file_path):
                os.remove(final_file_path)
            tmp_file = open(tmp_file_path, 'w')
            report_status(tmp_file, self.__generate_status(), time.time())
            tmp_file.close()
            tmp_file = None

            os.rename(tmp_file_path, final_file_path)
        except (OSError, IOError):
            log.exception('Exception caught will try to report status', error_code='failedStatus')
            if tmp_file is not None:
                tmp_file.close()


class WorkerThread(object):
    """A thread used to run the log copier and the monitor manager.
    """
    def __init__(self, configuration, copying_manager, monitors):
        self.__scalyr_client = None
        self.config = configuration
        self.copying_manager = copying_manager
        self.monitors_manager = monitors

    def start(self, scalyr_client, log_initial_positions=None):
        if self.__scalyr_client is not None:
            self.__scalyr_client.close()
        self.__scalyr_client = scalyr_client

        self.copying_manager.start_manager(scalyr_client, log_initial_positions)
        # We purposely wait for the copying manager to begin copying so that if the monitors create any new
        # files, they will be guaranteed to be copying up to the server starting at byte index zero.
        # Note, if copying never begins then the copying manager will sys exit, so this next call will never just
        # block indefinitely will the process hangs around.
        self.copying_manager.wait_for_copying_to_begin()
        self.monitors_manager.start_manager()

    def stop(self):
        log.debug('Shutting down monitors')
        self.monitors_manager.stop_manager()

        log.debug('Shutting copy monitors')
        self.copying_manager.stop_manager()

        log.debug('Shutting client')
        if self.__scalyr_client is not None:
            self.__scalyr_client.close()


if __name__ == '__main__':
    my_controller = PlatformController.new_platform()
    parser = OptionParser(usage='Usage: scalyr-agent-2 [options] (start|stop|status|restart|condrestart|version)',
                          version='scalyr-agent v' + SCALYR_VERSION)
    parser.add_option("-c", "--config-file", dest="config_filename",
                      help="Read configuration from FILE", metavar="FILE")
    parser.add_option("-q", "--quiet", action="store_true", dest="quiet", default=False,
                      help="Only print error messages when running the start, stop, and condrestart commands")
    parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False,
                      help="For status command, prints detailed information about running agent.")
    parser.add_option("", "--no-fork", action="store_true", dest="no_fork", default=False,
                      help="For the run command, does not fork the program to the background.")
    parser.add_option("", "--no-check-remote-server", action="store_true", dest="no_check_remote",
                      help="For the start command, does not perform the first check to see if the agent can "
                           "communicate with the Scalyr servers.  The agent will just keep trying to contact it in "
                           "the backgroudn until it is successful.  This is useful if the network is not immediately "
                           "available when the agent starts.")
    my_controller.add_options(parser)

    (options, args) = parser.parse_args()
    my_controller.consume_options(options)

    if len(args) < 1:
        print >> sys.stderr, 'You must specify a command, such as "start", "stop", or "status".'
        parser.print_help(sys.stderr)
        sys.exit(1)
    elif len(args) > 1:
        print >> sys.stderr, 'Too many commands specified.  Only specify one of "start", "stop", "status".'
        parser.print_help(sys.stderr)
        sys.exit(1)
    elif args[0] not in ('start', 'stop', 'status', 'restart', 'condrestart', 'version'):
        print >> sys.stderr, 'Unknown command given: "%s"' % args[0]
        parser.print_help(sys.stderr)
        sys.exit(1)

    if options.config_filename is not None and not os.path.isabs(options.config_filename):
        options.config_filename = os.path.abspath(options.config_filename)

    main_rc = 1
    try:
        main_rc = ScalyrAgent(my_controller).main(options.config_filename, args[0], options)
    except Exception, mainExcept:
        print >> sys.stderr, str(mainExcept)
        sys.exit(1)

    # We do this outside of the try block above because sys.exit raises an exception itself.
    sys.exit(main_rc)
