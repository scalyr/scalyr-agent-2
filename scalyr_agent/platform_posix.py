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
import fcntl
import sys
import pwd
import os
import time
import atexit
import resource
import signal
import tempfile

from scalyr_agent.platform_controller import PlatformController, DefaultPaths, AgentAlreadyRunning
from scalyr_agent.platform_controller import CannotExecuteAsUser, AgentNotRunning
import scalyr_agent.util as scalyr_util

from __scalyr__ import get_install_root, TARBALL_INSTALL, DEV_INSTALL, PACKAGE_INSTALL

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

    def __init__(self, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        """Initializes the POSIX platform instance.
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
        self.__no_change_user = False
        # A list of log lines collected for debugging the initialization sequence.  The entries
        # are tuples of the line and a boolean indicating whether or not it is a debug entry.
        self.__init_log_lines = []
        self.__is_initializing = True

        # Whether or not to use the commandline in the pidfile to help protect against pid re-use.
        self.__verify_command_in_pidfile = False

        PlatformController.__init__(self)

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
        options_parser.add_option("", "--no-change-user", action="store_true", dest="no_change_user", default=False,
                                  help="Forces agent to not change which user is executing agent.  Requires the right "
                                       "user is already being used.  This is used internally to prevent infinite loops "
                                       "in changing to the correct user.  Users should not need to set this option.")

    def consume_options(self, options):
        """Invoked by the main method to allow the platform to consume any command line options previously requested
        in the 'add_options' call.

        @param options: The object containing the options as returned by the OptionParser.
        """
        self.__pidfile_from_options = options.pid_file
        self.__no_change_user = options.no_change_user

    def consume_config(self, config, path_to_config):
        """Invoked after 'consume_options' is called to set the Configuration object to be used.

        @param config: The configuration object to use.  It will be None if the configuration could not be parsed.
        @param path_to_config: The full path to file that was read to create the config object.

        @type config: configuration.Configuration
        @type path_to_config: str
        """
        # Now that we have the config and have consumed any options that we could have been specified, we need to
        # determine where we read the pidfile from.  Typically, this should be based on the configuration file, but
        # in the case where we cannot read it, we have to guess or use the commandline option.
        if config is not None:
            self.__pidfile = os.path.join(config.agent_log_path, 'agent.pid')
            self.__verify_command_in_pidfile = config.pidfile_advanced_reuse_guard

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

    def emit_init_log(self, logger, include_debug):
        """Writes any logged information the controller has collected about the initialization of the agent_service
        to the provided logger.

        This is required because the initialization sequence occurs before the agent log is set up to write to
        a file instead of standard out.  Using this, we can collect the information and then output it once the
        logger is set up.

        @param logger: The logger to use to write the information.
        @param include_debug:  If True, include debug level logging as well.
        @type logger: Logger
        @type include_debug: bool
        """
        logger.info('Emitting log lines saved during initialization: %s' % scalyr_util.get_pid_tid())
        for line_entry in self.__init_log_lines:
            if not line_entry[1] or include_debug:
                logger.info('     %s' % line_entry[0])

        if include_debug:
            logger.info('Parent pids:')
            current_child = os.getpid()
            current_parent = self.__get_ppid(os.getpid())

            remaining_parents = 10
            while current_parent is not None and remaining_parents > 0:
                if _can_read_command_line(current_parent):
                    logger.info('    ppid=%d cmd=%s parent_of=%d' % (current_parent,
                                                                     _read_command_line(current_parent),
                                                                     current_child))
                else:
                    logger.info('    ppid=%d cmd=Unknown parent_of=%d' % (current_parent, current_child))
                current_child = current_parent
                current_parent = self.__get_ppid(current_parent)
                remaining_parents -= 1
        return

    def __write_pidfile(self):
        """Writes the process's pid to a file"""
        atexit.register(self.__delpid)
        pid = os.getpid()

        fp = None
        try:
            fp = file(self.__pidfile, 'w+')
            # If we are on an OS that supports reading the commandline arguments from /proc, then use that
            # to write more unique information about the running process to help avoid pid collison.
            if self.__can_read_command_line(pid):
                fp.write('%d %s\n' % (pid, self.__read_command_line(pid)))
                self._log_init_debug('Wrote pidfile+ (orig_pid=%s) %s' % (original_pid, scalyr_util.get_pid_tid()))
            else:
                fp.write('%d\n' % pid)
                self._log_init_debug('Wrote pidfile (orig_pid=%s) %s' % (original_pid, scalyr_util.get_pid_tid()))
        finally:
            if fp is not None:
                fp.close()

    def __daemonize(self):
        """Fork off a background thread for execution.  If this method returns True, it is the new process, otherwise
        it is the original process.

        This will also populate the PID file with the new process id.

        This uses the UNIX double-fork magic, see Stevens' "Advanced
        Programming in the UNIX Environment" for details (ISBN 0201563177)
        http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
        """
        original_pid = os.getpid()

        def debug_logger(message):
            self._log_init_debug('%s (orig_pid=%s) %s' % (message, original_pid, scalyr_util.get_pid_tid()))

        def logger(message):
            self._log_init('%s (orig_pid=%s) %s' % (message, original_pid, scalyr_util.get_pid_tid()))

        # Create a temporary file that we will use to communicate between the calling process and the daemonize
        # process.
        reporter = StatusReporter()

        # The double fork thing is required to really dettach the eventual process for the current one, including
        # such weird details as making sure it can never be the session leader for the old process.

        # Do the first fork.

        debug_logger('Forking service')
        try:
            pid = os.fork()
            if pid > 0:
                # We are the calling process.  We will attempt to wait until we see the daemon process report its
                # status.
                status_line = reporter.read_status(timeout=30.0, timeout_status='timeout')
                if status_line == 'success':
                    return False
                elif status_line == 'alreadyRunning':
                    self.is_agent_running(fail_if_running=True)
                    raise AgentAlreadyRunning('The agent could not be started because it believes another agent '
                                              'is already running.')
                elif status_line == 'timeout':
                    sys.stderr.write('Warning, could not verify the agent started in the background.  '
                                     'May not be running.\n')
                    return False
                else:
                    sys.stderr.write("The agent appears to have failed to have started.  Error message was "
                                     "%s\n" % status_line)
                    sys.exit(1)
        except OSError, e:
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)
        except SystemExit, e:
            raise e
        except Exception, e:
            reporter.report_status('forked #1 failed due to generic error: %s' % str(e))
            sys.exit(1)

        debug_logger('Second fork')

        # noinspection PyBroadException
        try:
            # decouple from parent environment
            os.chdir("/")
            # noinspection PyArgumentList
            os.setsid()
            os.umask(0)

            # do second fork
            pid = os.fork()
            if pid > 0:
                # exit from second parent
                sys.exit(0)
        except OSError, e:
            reporter.report_status('fork #2 failed: %d (%s)' % (e.errno, e.strerror))
            sys.stderr.write('fork #2 failed: %d (%s)\n' % (e.errno, e.strerror))
            sys.exit(1)
        except SystemExit, e:
            raise e
        except Exception, e:
            reporter.report_status('forked #2 failed due to generic error: %s' % str(e))
            sys.exit(1)

        debug_logger('Finished forking')

        try:
            # redirect standard file descriptors
            sys.stdout.flush()
            sys.stderr.flush()
            si = file(self.__stdin, 'r')
            so = file(self.__stdout, 'a+')
            se = file(self.__stderr, 'a+', 0)
            os.dup2(si.fileno(), sys.stdin.fileno())
            os.dup2(so.fileno(), sys.stdout.fileno())
            os.dup2(se.fileno(), sys.stderr.fileno())

            # Write out our process id to the pidfile.
            pidfile = PidfileManager(self.__pidfile)
            pidfile.set_options(debug_logger=debug_logger, logger=logger,
                                check_command_line=self.__verify_command_in_pidfile)

            if not pidfile.write_pid():
                reporter.report_status('alreadyRunning')
                return False

            atexit.register(pidfile.delete_pid)

            reporter.report_status('success')
            logger('Process has been daemonized')
            return True
        except Exception, e:
            reporter.report_status('Finalizing fork failed due to generic error: %s' % str(e))
            sys.exit(1)

    def __get_ppid(self, pid):
        """Returns the pid of the parent process for pid.  If there is no parent or it cannot be determined, None.
        @param pid:  The id of the process whose parent should be found.
        @type pid: int

        @return: The parent process id, or None if there is none.
        @rtype: int|None
        """
        if os.path.isfile('/proc/%d/stat' % pid):
            pf = None
            try:
                # noinspection PyBroadException
                try:
                    pf = file('/proc/%d/stat' % pid, 'r')
                    ppid = int(pf.read().split()[3])
                    if ppid == 0:
                        return None
                    else:
                        return ppid
                except:
                    return None
            finally:
                if pf is not None:
                    pf.close()
        else:
            return None

    def _log_init(self, line, is_debug=False):
        """If we are still in the initialization phase (i.e., we have not started the agent service), then append
        the specified line to the list that will be written out in the ``emit_init_log`` method.

        @param line: The line containing information.
        @param is_debug:  True if this represents a debug level log record and should only be emitted to the actual
            log if the configuration's debug_init True is true.
        @type line: str
        @type is_debug: bool
        """
        if self.__is_initializing:
            current_time = time.time()
            time_str = '%s.%03dZ' % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(current_time)),
                                     int(current_time % 1 * 1000))
            self.__init_log_lines.append(['%s   (%s)' % (line, time_str), is_debug])

    def _log_init_debug(self, line):
        """If we are still in the initialization phase (i.e., we have not started the agent service), then append
        the specified line to the list that will be written out in the ``emit_init_log`` method and mark it
        as debug.

        @param line: The line containing debug information.
        @type line: str
        """
        self._log_init(line, True)

    def get_file_owner(self, file_path):
        """Returns the user name of the owner of the specified file.

        @param file_path: The path of the file.
        @type file_path: str

        @return: The user name of the owner.
        @rtype: str
        """
        return pwd.getpwuid(os.stat(file_path).st_uid).pw_name

    def get_current_user(self):
        """Returns the effective user name running this process.

        The effective user may not be the same as the initiator of the process if the process has escalated its
        privileges.

        @return: The name of the effective user running this process.
        @rtype: str
        """
        return pwd.getpwuid(os.geteuid()).pw_name

    def set_file_owner(self, file_path, owner):
        """Sets the owner of the specified file.

        @param file_path: The path of the file.
        @param owner: The new owner of the file.  This should be a string returned by either `get_file_ower` or
            `get_current_user`.
        @type file_path: str
        @type owner: str
        """
        os.chown(file_path, pwd.getpwnam(owner).pw_uid, -1)

    def run_as_user(self, user_name, script_file, script_binary, script_arguments):
        """Runs the specified script with the same arguments as the specified user.

        This will run the entire Python script so that it is executing as the specified user.
        It will also add in the '--no-change-user' option which can be used by the script being executed with the
        next process that it was the result of restart so that it probably shouldn't do that again.

        Note, in some system implementations, the current process is replaced by the new process, so this method
        does not ever return to the caller.

        @param user_name: The user to run as, typically 'root' or 'Administrator'.
        @param script_file: The path to the Python script file that was executed if it can be determined.  If it cannot
            then this will be None and script_binary will be supplied.
        @param script_binary:  The binary that is being executed.  This is only supplied if script_file is None.
            On some systems, such as Windows running a script frozen by py2exe, the script is embedded in an actual
            executable.
        @param script_arguments: The arguments passed in on the command line that need to be used for the new
            command line.

        @return The status code for the executed script, if it returns at all.

        @type user_name: str
        @type script_file: str|None
        @type script_binary: str|None
        @type script_arguments: list<str>

        @rtype int

        @raise CannotExecuteAsUser: Indicates that the current process could not change the specified user for
            some reason to execute the script.
        """
        if os.geteuid() != 0:
            raise CannotExecuteAsUser('Must be root to change users')
        if script_file is None:
            raise CannotExecuteAsUser('Must supply script file to execute')
        if self.__no_change_user:
            raise CannotExecuteAsUser('Multiple attempts of changing user detected -- a bug must be causing loop.')

        # Use sudo to re-execute this script with the correct user.  We also pass in --no-change-user to prevent
        # us from re-executing the script again to change the user, to
        # head of any potential bugs that could cause infinite loops.
        arguments = ['sudo', '-u', user_name, sys.executable, script_file, '--no-change-user'] + script_arguments

        print >>sys.stderr, ('Running as %s' % user_name)
        return os.execvp("sudo", arguments)

    def is_agent(self):
        """Checks to see if this current process is the official agent service.

        A result of zero, indicates this process is the official agent service.  All other values are platform
        specific codes indicating how it decided this process was not the agent service.

        @return: Zero if it is the current process, otherwise a platform specific code.
        @rtype: int
        """
        agent_pid = self.__read_pidfile()
        if agent_pid is not None:
            if agent_pid == os.getpid():
                return 0
            else:
                return agent_pid

        if os.path.isfile(self.__pidfile):
            return -1
        else:
            return -2

    def is_agent_running(self, fail_if_running=False, fail_if_not_running=False):
        """Returns true if the agent service is running, as determined by the pidfile.

        This will optionally raise an Exception with an appropriate error message if the agent is not running.

        @param fail_if_running:  True if the method should raise an Exception with a message about where the pidfile
            was read from.
        @param fail_if_not_running: True if the method should raise an Exception with a message about where the pidfile
            was read from.

        @type fail_if_running: bool
        @type fail_if_not_running: bool

        @return: True if the agent process is already running.
        @rtype: bool

        @raise AgentAlreadyRunning
        @raise AgentNotRunning
        """
        self._log_init_debug('Checking if agent is running %s' % scalyr_util.get_pid_tid())
        pid = self.__read_pidfile()

        if fail_if_running and pid is not None:
            raise AgentAlreadyRunning('The pidfile %s exists and indicates it is running pid=%d' % (
                self.__pidfile, pid))

        if fail_if_not_running and pid is None:
            raise AgentNotRunning('The pidfile %s does not exist or listed process is not running.' % self.__pidfile)

        return pid is not None

    def start_agent_service(self, agent_run_method, quiet, fork):
        """Start the daemon process by forking a new process.

        This method will invoke the agent_run_method that was passed in when initializing this object.
        """
        self._log_init_debug('Starting agent %s' % scalyr_util.get_pid_tid())

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
        if fork and not self.__daemonize():
            return

        # write pidfile
        self.__write_pidfile()

        # Register for the TERM and INT signals.  If we get a TERM, we terminate the process.  If we
        # get a INT, then we write a status file.. this is what a process will send us when the command
        # scalyr-agent-2 status -v is invoked.
        original_term = signal.signal(signal.SIGTERM, handle_terminate)
        original_interrupt = signal.signal(signal.SIGINT, handle_interrupt)

        try:
            self.__is_initializing = False
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
            message = ("Failed to stop the agent because it does not appear to be running.  pidfile %s does not exist"
                       " or listed process is not running.\n")
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

    def __read_pidfile(self):
        def debug_logger(message):
            self._log_init_debug('%s %s' % (message, scalyr_util.get_pid_tid()))

        def logger(message):
            self._log_init('%s %s' % (message, scalyr_util.get_pid_tid()))

        manager = PidfileManager(self.__pidfile)
        manager.set_options(debug_logger=debug_logger, logger=logger,
                            check_command_line=self.__verify_command_in_pidfile)
        return manager.read_pid()


class PidfileManager(object):
    """Used to read and write the pidfile for the running Scalyr Agent.

    This cleanly handles the race conditions that can occur when attempting to start up
    several copies of the agent process at the same time.  Therefore, you should always use this abstraction to
    both read and write the pidfile.
    """
    def __init__(self, pidfile):
        """Creates a manager to read and write the specified pidfile.

        @param pidfile:  The full path of the pidfile.
        @type pidfile: str
        """
        self.__pidfile = pidfile
        # The name of the file we must get an advisory lock on whenever we attempt to write the pidfile.
        self.__pidfile_lock = os.path.join(os.path.dirname(pidfile), '.%s.lock' % os.path.basename(pidfile))
        # A function that takes a single argument that will be invoked whenever this abstraction wishes to
        # report a message that should be included in the log.
        self.__logger = None
        # A function that takes a single argument that will be invoked whenever this abstraction wishes to
        # report a debug message.
        self.__debug_logger = None
        # Previously, whenever we wrote a pidfile, we included both the pid of the running agent and the command
        # of that process as read from the /proc file system.  The command line was suppose to provide some guard
        # against the cases where the pidfile is stale, but there happens to be another process running that has
        # the pid of the old agent process (pid reuse).  We would check both that the pid is running and that the
        # command line of that process is still the same as what was in the pid file.  However, we think this
        # has been causing false negatives on some systems, so we are disabling checking it by default now.  We still
        # write the command line to the pid file, but we do not check it.  We can override this with a config option.
        self.__check_command_line = True
        # Whether or not we have an advisory lock on the lock file.
        self.__locked = False
        # The file pointer for the open lock file.  When we close this, the advisory lock will go away.
        self.__lock_fd = None

    def read_pid(self, command_line=None):
        """Reads the pid file and returns the process id contained in it.

        This also verifies as best as it can that the process returned is running and is really an agent
        process.

        @param command_line:  For testing purposes only.  The value the system should use as the command line
            for the pid in the pid file.
        @type command_line: str
        @return The id of the agent process or None if there is none or it cannot be read.
        @rtype: int or None
        """
        try:
            pf = file(self.__pidfile, 'r')
            contents = pf.read().strip().split()
            pf.close()
        except IOError:
            self._log('Checked pidfile: does not exist')
            return None

        pid = int(contents[0])
        try:
            os.kill(pid, 0)
        except OSError, e:
            # ESRCH indicates the process is not running, in which case we ignore the pidfile.
            if e.errno == errno.ESRCH:
                self._log('Checked pidfile: missing')
                return None
            # EPERM indicates the current user does not have permission to signal the process.. so it exists
            # but may not be the agent process.  We will just try our /proc/pid/commandline trick below if we can.
            elif e.errno != errno.EPERM:
                raise e

        # If we got here, the process is running, and we have to see if we can determine if it is really the
        # original agent process.  For Linux systems with /proc, we see if the commandlines match up if
        # this instance is requested to.  For all other Posix systems, (Mac OS X, etc) we bail for now.

        # Read the command line of the current agent process as stored in the pidfile.  None means it
        # could not be read.
        if len(contents) >= 2:
            command_line_from_pidfile = contents[1]
        else:
            self._log_debug('Could not retrieve commandline from pidfile')
            command_line_from_pidfile = None

        # Get the commandline of the process whose pid is stored in the pidfile.  This is only set to
        # None if we cannot retrieve it.
        if _can_read_command_line(pid) and command_line is None:
            command_line = _read_command_line(pid)
        else:
            self._log_debug('Could not retrieve commandline from /proc')

        # We can only attempt the check if we had a pidfile that contained the commandline -- otherwise
        # we might be working with an old pidfile that doesn't have it.
        if command_line_from_pidfile is not None:
            commands_match = command_line_from_pidfile == command_line
        else:
            commands_match = True

        # We always log a message if we see a command mismatch because this could be an indication of a bug
        if not commands_match:
            self._log('Mismatch between commands seen in pidfile and on /proc: "%s" vs "%s"' %
                      (str(command_line_from_pidfile), str(command_line)))

        if not self.__check_command_line:
            self._log('Checked pidfile: exists')
            return pid
        elif command_line is None:
            # We could not read the command from /proc so we do not do the check either.
            self._log('Checked pidfile: exists*')
            return pid
        elif command_line_from_pidfile is None:
            # There was no command line in the pidfile, so we skip the check as well..
            self._log('Checked pidfile: exists#')
            return pid

        if commands_match:
            self._log('Checked pidfile: exists+')
            return pid
        else:
            self._log('Checked pidfile: missing+')
            return None

    def write_pid(self, pid=None, command_line=None):
        """Attempts to update the pidfile to write the pid of the current process in it.

        This will not succeed if another running process's pid is already in the pidfile.

        @param pid:  For testing purposes only.  The pid to write into the file (instead of the current process's pid).
        @param command_line:  For testing purposes only.  The command line to use when writing into the pidfile
            instead of the command line of the current process.

        @type pid: int
        @type command_line: str or unknown
        @return:  True iff the pid file was successfully updated with this process's pid.  False if there is another
            pid in the pidfile of a running process.
        @rtype: bool
        """
        # write pidfile.  We only allow writing to the pidfile if you have an advisory lock on the lock file.
        # This will block until we have the lock, but that's ok.
        self._log('Writing pidfile')
        self._lock_pidfile()
        try:
            # Once we have the lock, we have to make sure the original pid file still indicates an agent process
            # is still not running.  We have to be holding the lock when we read this to make sure it is a true
            # compare and swap.
            if self.read_pid() is not None:
                self._log('Did not write pidfile: exists')
                return False

            # Now we can write it.
            if pid is None:
                pid = os.getpid()

            # To make updating the pidfile atomic, we first write to a temporary file and then rename it.
            tmp_pidfile = '%s.tmp' % self.__pidfile
            fp = None
            try:
                fp = file(tmp_pidfile, 'w+')
                # If we are on an OS that supports reading the commandline arguments from /proc, then use that
                # to write more unique information about the running process to help avoid pid collison.
                if _can_read_command_line(pid) or command_line is not None:
                    if command_line is None:
                        command_line = _read_command_line(pid)
                    fp.write('%d %s\n' % (pid, command_line))
                    self._log('Wrote pidfile+, commit pending')
                else:
                    fp.write('%d\n' % pid)
                    self._log('Wrote pidfile, commit pending')

                # make sure that all data is on disk
                # see http://stackoverflow.com/questions/7433057/is-rename-without-fsync-safe
                fp.flush()
                os.fsync(fp.fileno())
                fp.close()

                fp = None

            finally:
                if fp is not None:
                    fp.close()

            os.rename(tmp_pidfile, self.__pidfile)
            self._log('Committed pidfile')
            return True

        finally:
            self._unlock_pidfile()

    def delete_pid(self):
        """Deletes the pid file"""
        if os.path.isfile(self.__pidfile):
            os.remove(self.__pidfile)

    def set_options(self, logger=None, debug_logger=None, check_command_line=None):
        """Sets some options related to managing the pid.

        @param logger A callback that takes a single argument ``message``.  This callback will be invoked
            whenever the abstraction wishes to log a message.  We have to take this approach rather than
            just relying on the logger abstractions because the process has not opened the agent log by the time
            the pidfile is being checked.
        @param debug_logger A callback that takes a single argument ``message``.  This callback will be invoked
            whenever the abstraction wishes to log a debug message.
        @param check_command_line:  Whether or not, when reading the pidfile, the command in the pidfile should
            be checked against the running process in order to verify it is still the same process.  This is
            an advanced option to help protect against issues due to pid reuse, but in practice, we believe this
            is causing false negatives and are disabling it for now.

        @type logger: Function(str)
        @type debug_logger: Function(str)
        @type check_command_line: bool
        """
        if logger is not None:
            self.__logger = logger
        if debug_logger is not None:
            self.__debug_logger = debug_logger
        if check_command_line is not None:
            self.__check_command_line = check_command_line

    def _lock_pidfile(self):
        """Blocks until this process has an advisory lock on the pidfile's lock file.
        """
        if self.__lock_fd is not None:
            raise Exception('Trying to lock pidfile when it is already locked.')
        # We have to be sure we create the pidfile lock only once so everyone sees it.
        attempts = 50
        if not os.path.isfile(self.__pidfile_lock):
            self._log('Creating pid lock file')
        while not os.path.isfile(self.__pidfile_lock) and attempts > 0:
            attempts -= 1
            fd = None
            try:
                try:
                    fd = os.open(self.__pidfile_lock, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    """ @type: int"""
                    os.write(fd, 'lock\n')
                    os.close(fd)
                    fd = None
                except OSError, e:
                    if e.errno == errno.EEXIST:
                        continue
                    else:
                        raise e
            finally:
                if fd is not None:
                    os.close(fd)

        if not os.path.isfile(self.__pidfile_lock):
            raise Exception('Could not create the pid lock file for some reason')

        self.__lock_fd = file(self.__pidfile_lock, 'w')
         # This will block until we are the only process with a lock on the file.  Blocking is ok for now..
        fcntl.lockf(self.__lock_fd, fcntl.LOCK_EX)
        self.__locked = True

    def _unlock_pidfile(self):
        """Release this process's advisory lock on the pidfile's lock file.
        """
        if self.__lock_fd is None or not self.__locked:
            raise Exception('Trying to unlock pidfile when it is not locked.')
        try:
            self.__lock_fd.close()
            self.__locked = False
        finally:
            self.__lock_fd = None

    def _log_debug(self, message):
        if self.__debug_logger is not None:
            self.__debug_logger(message)

    def _log(self, message):
        if self.__logger is not None:
            self.__logger(message)


class StatusReporter(object):
    """Used to send back a status message to process A from process B where process A has forked process B.

    The status message is just a single string of text.

    This is implemented by writing and reading bytes out of a shared temporary file.
    """
    def __init__(self, duplicate_reporter=None):
        """Creates an instance.
        @param duplicate_reporter:  Only used for test.  If given, this instance will use a duplicate of
            ``duplicate_reporter``'s underlying file used for communication.  This pretty much simulates what the
            StatusReporter instances will look like after a fork.
        @type duplicate_reporter: StatusReporter
        """
        self.__has_reported = False
        if duplicate_reporter is None:
            self.__fp = tempfile.TemporaryFile()
        else:
            source_fp = duplicate_reporter.__fp
            # For this to work, we have to make sure tempfile.TemporaryFile gave us back a real file (rather than
            # a wrapper as indicated by having a file attribute), which it should for POSIX systems.
            assert not hasattr(source_fp, 'file')

            self.__fp = os.fdopen(os.dup(source_fp.fileno()), 'w+b')

            assert self.__fp.fileno() != source_fp.fileno()

    def close(self):
        """Closes the status reporter.  This must be invoked by all processes.
        """
        self.__fp.close()

    def report_status(self, message):
        """Report the specified string back to the other process listening on this instance.

        @param message: The text string to send.  For safety's sake, this probably should only include low ascii
            characters.
        @type message: str
        """
        # We write out the number of bytes in the message followed by the message.  The number of bytes might be
        # different from the message length in the case of higher ascii, but we'll punt on that for now.
        self.__fp.write('%d\n' % len(message))
        self.__fp.write('%s' % message)
        self.__fp.flush()

    def read_status(self, timeout=None, timeout_status=None):
        """Blocks, waiting for the status message to be reported.

        @param timeout:  If not None, this will only block until the specified number of seconds has passed.  After
           which, ``timeout_status`` is returned for this method.
        @param timeout_status:  The string to return when the timeout has been reached.

        @type timeout: float
        @type timeout_status: str

        @return:  The reported status message, or ``timeout_status`` if the timeout has been reached.
        @rtype: str
        """
        if timeout is not None:
            deadline = time.time() + timeout
        else:
            deadline = None

        while True:
            if deadline is not None and time.time() > deadline:
                return timeout_status
            self.__fp.seek(0)
            num_bytes = self.__fp.readline()
            if num_bytes != '':
                message = self.__fp.read()
                if len(message) == int(num_bytes):
                    return message
            time.sleep(0.20)

    @property
    def has_reported(self):
        """Whether or not this process has invoked ``report_status``.
        @return:  True if this process has invoked ``report_status``.
        @rtype: bool
        """
        return self.__has_reported


def _can_read_command_line(pid):
    """Returns True if the commandline arguments for the specified process can be read.

    @param pid: The id of the process
    @type pid: int
    @return: True if it can be read.
    @rtype: bool
    """
    return os.path.isfile('/proc/%d/cmdline' % pid)


def _read_command_line(pid):
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
