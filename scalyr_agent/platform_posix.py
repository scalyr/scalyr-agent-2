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

import errno
import sys
import pwd
import os
import time
import atexit
import resource
import signal

from scalyr_agent.platform_controller import PlatformController, DefaultPaths, AgentAlreadyRunning
from scalyr_agent.platform_controller import TARBALL_INSTALL, DEV_INSTALL, PACKAGE_INSTALL

from __scalyr__ import get_install_root

# Based on code by Sander Marechal posted at
# http://web.archive.org/web/20131017130434/http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/


class PosixPlatformController(PlatformController):
    """A controller instance for Unix-like platforms.

    The controller manages such platform dependent tasks as:
      - Forking a daemon thread to run the agent process in the background
      - Implementing the scheme that determine if the agent process is already running on the host,
        such as by using a PID file.
      - Stopping the agent process.
      - Sending signals to the running agent process.
    """

    def __init__(self, install_type, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        """Initializes the POSIX platform instance.

        @param install_type: One of the constants describing the install type, such as PACKAGE_INSTALL, TARBALL_INSTALL,
            or DEV_INSTALL.

        @type install_type: int
        """
        self.__stdin = stdin
        self.__stdout = stdout
        self.__stderr = stderr
        # The file name storing the pid.
        self.__pidfile = None
        # The pidfile specified on the commandline using the flags, if any.  This gives the user a chance to
        # specify the pidfile if the configuration cannot be read.
        self.__pidfile_from_options = None

        # The method to invoke when termination is requested.
        self.__termination_handler = None
        # The method to invoke when status is requested by another process.
        self.__status_handler = None
        PlatformController.__init__(self, install_type)

    def can_handle_current_platform(self):
        """Returns true if this platform object can handle the server this process is running on.

        @return:  True if this platform instance can handle the current server.
        @rtype: bool
        """
        # TODO:  For now, we only support POSIX.  Once we get Windows support in, will need to change this to
        # not return True when we should be using Windows.
        return True

    def add_options(self, options_parser):
        """Invoked by the main method to allow the platform to add in platform-specific options to the
        OptionParser used to parse the commandline options.

        @param options_parser:
        @type options_parser: optparse.OptionParser
        """
        options_parser.add_option(
            "-p", "--pid-file", dest="pid_file",
            help="The path storing the running agent's process id.  Only used if config cannot be parsed.")

    def consume_options(self, options):
        """Invoked by the main method to allow the platform to consume any command line options previously requested
        in the 'add_options' call.

        @param options: The object containing the options as returned by the OptionParser.
        """
        self.__pidfile_from_options = options.pid_file

    def consume_config(self, config):
        """Invoked after 'consume_options' is called to set the Configuration object to be used.

        @param config: The configuration object to use.  It will be None if the configuration could not be parsed.
        @type config: configuration.Configuration
        """
        # Now that we have the config and have consumed any options that we could have been specified, we need to
        # determine where we read the pidfile from.  Typically, this should be based on the configuration file, but
        # in the case where we cannot read it, we have to guess or use the commandline option.
        if config is not None:
            self.__pidfile = os.path.join(config.agent_log_path, 'agent.pid')
        elif self.__pidfile_from_options is None:
            self.__pidfile = os.path.join(self.default_paths.agent_log_path, 'agent.pid')
            print >> sys.stderr, 'Assuming pid file is \'%s\'.  Use --pid-file to override.' % self.__pidfile
        else:
            self.__pidfile = os.path.abspath(self.__pidfile_from_options)
            print >> sys.stderr, 'Using pid file \'%s\'.' % self.__pidfile

    @property
    def default_paths(self):
        """Returns the default paths to use for various configuration options for this platform.

        @return: The default paths
        @rtype: DefaultPaths
        """
        # TODO: Change this to something that is not Linux-specific.  Maybe we should always just default
        # to the home directory location.
        if self._install_type == PACKAGE_INSTALL:
            return DefaultPaths('/var/log/scalyr-agent-2',
                                '/etc/scalyr-agent-2/agent.json',
                                '/var/lib/scalyr-agent-2')
        elif self._install_type == TARBALL_INSTALL:
            install_location = get_install_root()
            return DefaultPaths(os.path.join(install_location, 'log'),
                                os.path.join(install_location, 'config', 'agent.json'),
                                os.path.join(install_location, 'data'))
        else:
            assert(self._install_type == DEV_INSTALL)
            # For developers only.  We default to a directory ~/scalyr-agent-dev for storing
            # all log/data information, and then require a log, config, and data subdirectory in each of those.
            base_dir = os.path.join(os.path.expanduser('~'), 'scalyr-agent-dev')
            return DefaultPaths(os.path.join(base_dir, 'log'),
                                os.path.join(base_dir, 'config', 'agent.json'),
                                os.path.join(base_dir, 'data'))

    def __daemonize(self):
        """Fork off a background thread for execution.  If this method returns True, it is the new process, otherwise
        it is the original process.

        This will also populate the PID file with the new process id.

        This uses the UNIX double-fork magic, see Stevens' "Advanced
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        """
        # The double fork thing is required to really dettach the eventual process for the current one, including
        # such weird details as making sure it can never be the session leader for the old process.

        # Do the first fork.
        try:
            pid = os.fork()
            if pid > 0:
                # exit first parent
                return False
        except OSError, e:
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)

        # decouple from parent environment
        os.chdir("/")
        # noinspection PyArgumentList
        os.setsid()
        os.umask(0)

        # do second fork
        try:
            pid = os.fork()
            if pid > 0:
                # exit from second parent
                sys.exit(0)
        except OSError, e:
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)

        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        si = file(self.__stdin, 'r')
        so = file(self.__stdout, 'a+')
        se = file(self.__stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        # write pidfile
        atexit.register(self.__delpid)
        pid = os.getpid()

        fp = None
        try:
            fp = file(self.__pidfile, 'w+')
            # If we are on an OS that supports reading the commandline arguments from /proc, then use that
            # to write more unique information about the running process to help avoid pid collison.
            if self.__can_read_command_line(pid):
                fp.write('%d %s\n' % (pid, self.__read_command_line(pid)))
            else:
                fp.write('%d\n' % pid)
        finally:
            if fp is not None:
                fp.close()

        return True

    def __delpid(self):
        """Deletes the pid file"""
        os.remove(self.__pidfile)

    def __read_pidfile(self):
        """Reads the pid file and returns the process id contained in it.

        This also verifies as best as it can that the process returned is running and is really an agent
        process.

        @return The id of the agent process or None if there is none or it cannot be read.
        @rtype: int or None
        """
        try:
            pf = file(self.__pidfile, 'r')
            contents = pf.read().strip().split()
            pf.close()
        except IOError:
            return None

        pid = int(contents[0])
        try:
            os.kill(pid, 0)
        except OSError, e:
            # ESRCH indicates the process is not running, in which case we ignore the pidfile.
            if e.errno == errno.ESRCH:
                return None
            # EPERM indicates the current user does not have permission to signal the process.. so it exists
            # but may not be the agent process.  We will just try our /proc/pid/commandline trick below if we can.
            elif e.errno != errno.EPERM:
                raise e

        # If we got here, the process is running, and we have to see if we can determine if it is really the
        # original agent process.  For Linux systems with /proc, we see if the commandlines match up.
        # For all other Posix systems, (Mac OS X, etc) we bail for now.
        if not self.__can_read_command_line(pid):
            return pid

        # Handle the case that we have an old pid file that didn't have the commandline right into it.
        if len(contents) == 1:
            return pid

        command_line = self.__read_command_line(pid)
        if contents[1] == command_line:
            return pid
        else:
            return None

    def __can_read_command_line(self, pid):
        """Returns True if the commandline arguments for the specified process can be read.

        @param pid: The id of the process
        @type pid: int
        @return: True if it can be read.
        @rtype: bool
        """
        return os.path.isfile('/proc/%d/cmdline' % pid)

    def __read_command_line(self, pid):
        """Reads the commandline arguments for the specified pid and returns the contents.

        @param pid: The id of the process.
        @type pid: int

        @return: The commandline arguments with no spaces.
        @rtype: str
        """
        pf = None
        try:
            pf = file('/proc/%d/cmdline' % pid, 'r')
            return pf.read().strip()
        finally:
            if pf is not None:
                pf.close()

    def run_as_user(self, user_id, script_file, script_arguments):
        """Restarts this process with the same arguments as the specified user.

        This will re-run the entire Python script so that it is executing as the specified user.
        It will also add in the '--no-change-user' option which can be used by the script being executed with the
        next proces that it was the result of restart so that it probably shouldn't do that again.

        @param user_id: The user id to run as, typically 0 for root.
        @param script_file: The path to the Python script file that was executed.
        @param script_arguments: The arguments passed in on the command line that need to be used for the new
            command line.

        @type user_id: int
        @type script_file: str
        @type script_arguments: list<str>
        """
        user_name = pwd.getpwuid(user_id).pw_name
        if os.geteuid() != user_id:
            if os.geteuid() != 0:
                print >>sys.stderr, ('Failing, cannot start scalyr_agent as correct user.  The current user (%s) does '
                                     'not own the config file and cannot change to that user because '
                                     'not root.' % user_name)
                sys.exit(1)
            # Use sudo to re-execute this script with the correct user.  We also pass in --no-change-user to prevent
            # us from re-executing the script again to change the user, to
            # head of any potential bugs that could cause infinite loops.
            arguments = ['sudo', '-u', user_name, sys.executable, script_file, '--no-change-user'] + script_arguments

            print >>sys.stderr, ('Running as %s' % user_name)
            os.execvp("sudo", arguments)

    def is_agent_running(self, fail_if_running=False):
        """Returns true if the agent service is running, as determined by the pidfile.

        This will optionally raise an Exception with an appropriate error message if the agent is not running.

        @param fail_if_running:  True if the method should raise an Exception with a message about where the pidfile
            was read from.
        @type fail_if_running: bool

        @return: True if the agent process is already running.
        @rtype: bool
        """
        pid = self.__read_pidfile()
        if not fail_if_running:
            return pid is not None

        if pid is not None:
            raise AgentAlreadyRunning('The agent appears to be running pid=%d.  pidfile %s does exist.' % (
                pid, self.__pidfile))

    def start_agent_service(self, agent_run_method, quiet):
        """Start the daemon process by forking a new process.

        This method will invoke the agent_run_method that was passed in when initializing this object.
        """
        # noinspection PyUnusedLocal
        def handle_terminate(signal_num, frame):
            if self.__termination_handler is not None:
                self.__termination_handler()

        # noinspection PyUnusedLocal
        def handle_interrupt(signal_num, frame):
            if self.__status_handler is not None:
                self.__status_handler()

        # Start the daemon by forking off a new process.  When it returns, we are either the original process
        # or the new forked one.  If it are the original process, then we just return.
        if not self.__daemonize():
            return

        # Register for the TERM and INT signals.  If we get a TERM, we terminate the process.  If we
        # get a INT, then we write a status file.. this is what a process will send us when the command
        # scalyr-agent-2 status -v is invoked.
        original_term = signal.signal(signal.SIGTERM, handle_terminate)
        original_interrupt = signal.signal(signal.SIGINT, handle_interrupt)

        try:
            result = agent_run_method(self)

            if result is not None:
                sys.exit(result)
            else:
                sys.exit(99)

        finally:
            signal.signal(signal.SIGTERM, original_term)
            signal.signal(signal.SIGINT, original_interrupt)

    def stop_agent_service(self, quiet):
        """Stop the daemon

        @param quiet:  If True, the only error information will be printed to stdout and stderr.
        """
        # Get the pid from the pidfile
        pid = self.__read_pidfile()

        if not pid:
            message = ("The agent does not appear to be running.  pidfile %s does not exist or listed process"
                       " is not running.\n")
            sys.stderr.write(message % self.__pidfile)
            return 0  # not an error in a restart

        if not quiet:
            print 'Sending signal to terminate agent.'

        # Try killing the daemon process
        try:
            # Do 5 seconds worth of TERM signals.  If that doesn't work, KILL it.
            term_attempts = 50
            while term_attempts > 0:
                os.kill(pid, signal.SIGTERM)
                PosixPlatformController.__sleep(0.1)
                term_attempts -= 1

            if not quiet:
                print 'Still waiting for agent to terminate, sending KILL signal.'

            while 1:
                os.kill(pid, signal.SIGKILL)
                PosixPlatformController.__sleep(0.1)

        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                if os.path.exists(self.__pidfile):
                    os.remove(self.__pidfile)
            else:
                print 'Unable to terminate agent.'
                print str(err)
                return 1

        if not quiet:
            # Warning, do not change this output.  The config_main.py file looks for this message when
            # upgrading a tarball install to make sure the agent was running.
            print 'Agent has stopped.'

        return 0

    def request_agent_status(self):
        """Invoked by a process that is not the agent to request the current agent dump the current detail
        status to the status file.

        This is used to implement the 'scalyr-agent-2 status -v' feature.

        @return: If there is an error, an errno that describes the error.  errno.EPERM indicates the current does not
            have permission to request the status.  errno.ESRCH indicates the agent is not running.
        """

        pid = self.__read_pidfile()
        if pid is None:
            return errno.ESRCH

        try:
            os.kill(pid, signal.SIGINT)
        except OSError, e:
            if e.errno == errno.ESRCH or e.errno == errno.EPERM:
                return e.errno
            raise e
        return None

    def register_for_termination(self, handler):
        """Register a method to be invoked if the agent service is requested to terminated.

        This should only be invoked by the agent service once it has begun to run.

        @param handler: The method to invoke when termination is requested.
        @type handler:  func
        """
        self.__termination_handler = handler

    def register_for_status_requests(self, handler):
        """Register a method to be invoked if this process is requested to report its status.

        This is used to implement the 'scalyr-agent-2 status -v' feature.

        This should only be invoked by the agent service once it has begun to run.

        @param handler:  The method to invoke when status is requested.
        @type handler: func
        """
        self.__status_handler = handler

    @staticmethod
    def __sleep(seconds):
        # noinspection PyBroadException
        try:
            time.sleep(seconds)
        except Exception:
            print 'Ignoring exception while sleeping'

    def sleep(self, seconds):
        """Sleeps for at most the specified number of seconds while also handling signals.

        Python does not do a great job of handling signals quickly when you invoke the normal time.sleep().
        This method is a Unix-specific implementation of a sleep that should do better quickly handling signals while
        sleeping.

        This method may return earlier than the requested number of seconds if a signal is received.

        @param seconds: The number of seconds to sleep for.
        """

        # We schedule an alarm signal for x=seconds out in the future.
        # noinspection PyUnusedLocal
        def handle_alarm(signal_num, frame):
            pass

        signal.signal(signal.SIGALRM, handle_alarm)
        signal.alarm(seconds)

        # Wait for either the alarm to go off or for us to receive a SIGINT.
        signal.pause()

        # Remove the alarm if it is still pending.
        signal.alarm(0)

    def get_usage_info(self):
        """Returns CPU and memory usage information.

        It returns the results in a tuple, with the first element being the number of
        CPU seconds spent in user land, the second is the number of CPU seconds spent in system land,
        and the third is the current resident size of the process in bytes."""

        usage_info = resource.getrusage(resource.RUSAGE_SELF)
        user_cpu = usage_info[0]
        system_cpu = usage_info[1]
        rss_size = usage_info[2]

        return user_cpu, system_cpu, rss_size
