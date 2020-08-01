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

from __future__ import unicode_literals
from __future__ import absolute_import
from __future__ import print_function

__author__ = "czerwin@scalyr.com"

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
from io import open

import six

from scalyr_agent import scalyr_logging
from scalyr_agent.platform_controller import (
    PlatformController,
    DefaultPaths,
    AgentAlreadyRunning,
)
from scalyr_agent.platform_controller import CannotExecuteAsUser, AgentNotRunning
import scalyr_agent.util as scalyr_util

from scalyr_agent.__scalyr__ import (
    get_install_root,
    TARBALL_INSTALL,
    DEV_INSTALL,
    PACKAGE_INSTALL,
)

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

    def __init__(self, stdin="/dev/null", stdout="/dev/null", stderr="/dev/null"):
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
            "-p",
            "--pid-file",
            dest="pid_file",
            help="The path storing the running agent's process id.  Only used if config cannot be parsed.",
        )
        options_parser.add_option(
            "",
            "--no-change-user",
            action="store_true",
            dest="no_change_user",
            default=False,
            help="Forces agent to not change which user is executing agent.  Requires the right "
            "user is already being used.  This is used internally to prevent infinite loops "
            "in changing to the correct user.  Users should not need to set this option.",
        )

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
            self.__pidfile = os.path.join(config.agent_log_path, "agent.pid")
            self.__verify_command_in_pidfile = config.pidfile_advanced_reuse_guard

        elif self.__pidfile_from_options is None:
            self.__pidfile = os.path.join(
                self.default_paths.agent_log_path, "agent.pid"
            )
            print(
                "Assuming pid file is '%s'.  Use --pid-file to override."
                % self.__pidfile,
                file=sys.stderr,
            )
        else:
            self.__pidfile = os.path.abspath(self.__pidfile_from_options)
            print("Using pid file '%s'." % self.__pidfile, file=sys.stderr)

    @property
    def default_paths(self):
        """Returns the default paths to use for various configuration options for this platform.

        @return: The default paths
        @rtype: DefaultPaths
        """
        # TODO: Change this to something that is not Linux-specific.  Maybe we should always just default
        # to the home directory location.
        if self._install_type == PACKAGE_INSTALL:
            return DefaultPaths(
                "/var/log/scalyr-agent-2",
                "/etc/scalyr-agent-2/agent.json",
                "/var/lib/scalyr-agent-2",
            )
        elif self._install_type == TARBALL_INSTALL:
            install_location = get_install_root()
            return DefaultPaths(
                os.path.join(install_location, "log"),
                os.path.join(install_location, "config", "agent.json"),
                os.path.join(install_location, "data"),
            )
        else:
            assert self._install_type == DEV_INSTALL
            # For developers only.  We default to a directory ~/scalyr-agent-dev for storing
            # all log/data information, and then require a log, config, and data subdirectory in each of those.
            base_dir = os.path.join(os.path.expanduser("~"), "scalyr-agent-dev")
            return DefaultPaths(
                os.path.join(base_dir, "log"),
                os.path.join(base_dir, "config", "agent.json"),
                os.path.join(base_dir, "data"),
            )

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
        logger.info(
            "Emitting log lines saved during initialization: %s"
            % scalyr_util.get_pid_tid()
        )
        for line_entry in self.__init_log_lines:
            if not line_entry[1] or include_debug:
                logger.info("     %s" % line_entry[0])

        if include_debug:
            logger.info("Parent pids:")
            current_child = os.getpid()
            current_parent = self.__get_ppid(os.getpid())

            remaining_parents = 10
            while current_parent is not None and remaining_parents > 0:
                if _can_read_command_line(current_parent):
                    logger.info(
                        "    ppid=%d cmd=%s parent_of=%d"
                        % (
                            current_parent,
                            _read_command_line(current_parent),
                            current_child,
                        )
                    )
                else:
                    logger.info(
                        "    ppid=%d cmd=Unknown parent_of=%d"
                        % (current_parent, current_child)
                    )
                current_child = current_parent
                current_parent = self.__get_ppid(current_parent)
                remaining_parents -= 1
        return

    def __write_pidfile(self, debug_logger=None, logger=None):
        pidfile = PidfileManager(self.__pidfile)
        pidfile.set_options(debug_logger=debug_logger, logger=logger)

        writer = pidfile.create_writer()
        release_callback = writer.write_pid()
        if release_callback is None:
            return False

        atexit.register(release_callback)
        return True

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
            self._log_init_debug(
                "%s (orig_pid=%s) %s"
                % (message, original_pid, scalyr_util.get_pid_tid())
            )

        def logger(message):
            self._log_init(
                "%s (orig_pid=%s) %s"
                % (message, original_pid, scalyr_util.get_pid_tid())
            )

        # Create a temporary file that we will use to communicate between the calling process and the daemonize
        # process.
        reporter = StatusReporter()

        # The double fork thing is required to really dettach the eventual process for the current one, including
        # such weird details as making sure it can never be the session leader for the old process.

        # Do the first fork.

        debug_logger("Forking service")
        try:
            pid = os.fork()
            if pid > 0:
                # We are the calling process.  We will attempt to wait until we see the daemon process report its
                # status.
                status_line = reporter.read_status(
                    timeout=30.0, timeout_status="timeout"
                )
                if status_line == "success":
                    return False
                elif status_line == "alreadyRunning":
                    self.is_agent_running(fail_if_running=True)
                    raise AgentAlreadyRunning(
                        "The agent could not be started because it believes another agent "
                        "is already running."
                    )
                elif status_line == "timeout":
                    sys.stderr.write(
                        "Warning, could not verify the agent started in the background.  "
                        "May not be running.\n"
                    )
                    return False
                else:
                    sys.stderr.write(
                        "The agent appears to have failed to have started.  Error message was "
                        "%s\n" % status_line
                    )
                    sys.exit(1)
        except OSError as e:
            sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)
        except SystemExit as e:
            raise e
        except Exception as e:
            reporter.report_status(
                "forked #1 failed due to generic error: %s" % six.text_type(e)
            )
            sys.exit(1)

        debug_logger("Second fork")

        # noinspection PyBroadException
        try:
            # decouple from parent environment
            os.chdir("/")
            # noinspection PyArgumentList
            os.setsid()
            # set umask to be consistent with common settings on linux systems.  This makes the standalone agent
            # created-file permissions consistent with that of docker/k8s agents (no write permissions for group and
            # others)
            os.umask(0o022)

            # do second fork
            pid = os.fork()
            if pid > 0:
                # exit from second parent
                sys.exit(0)
        except OSError as e:
            reporter.report_status("fork #2 failed: %d (%s)" % (e.errno, e.strerror))
            sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
            sys.exit(1)
        except SystemExit as e:
            raise e
        except Exception as e:
            reporter.report_status(
                "forked #2 failed due to generic error: %s" % six.text_type(e)
            )
            sys.exit(1)

        debug_logger("Finished forking")

        try:
            # redirect standard file descriptors
            sys.stdout.flush()
            sys.stderr.flush()
            si = open(self.__stdin, "r")
            so = open(self.__stdout, "a+")
            # 2->TODO io.open does not allow buffering disabling on text files. So open it as binary.
            se = open(self.__stderr, "ba+", 0)
            os.dup2(si.fileno(), sys.stdin.fileno())
            os.dup2(so.fileno(), sys.stdout.fileno())
            os.dup2(se.fileno(), sys.stderr.fileno())
            si.close()
            so.close()
            se.close()

            # Write out our process id to the pidfile.
            if not self.__write_pidfile(debug_logger=debug_logger, logger=logger):
                reporter.report_status("alreadyRunning")
                return False

            reporter.report_status("success")
            logger("Process has been daemonized")
            return True
        except Exception as e:
            reporter.report_status(
                "Finalizing fork failed due to generic error: %s" % six.text_type(e)
            )
            sys.exit(1)

    def __get_ppid(self, pid):
        """Returns the pid of the parent process for pid.  If there is no parent or it cannot be determined, None.
        @param pid:  The id of the process whose parent should be found.
        @type pid: int

        @return: The parent process id, or None if there is none.
        @rtype: int|None
        """
        if os.path.isfile("/proc/%d/stat" % pid):
            pf = None
            try:
                # noinspection PyBroadException
                try:
                    pf = open("/proc/%d/stat" % pid, "r")
                    ppid = int(pf.read().split()[3])
                    if ppid == 0:
                        return None
                    else:
                        return ppid
                except Exception:
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
            time_str = "%s.%03dZ" % (
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(current_time)),
                int(current_time % 1 * 1000),
            )
            self.__init_log_lines.append(["%s   (%s)" % (line, time_str), is_debug])

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
            On some systems, such as Windows running a script frozen by PyInstaller, the script is embedded in an actual
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
            raise CannotExecuteAsUser("Must be root to change users")
        if script_file is None:
            raise CannotExecuteAsUser("Must supply script file to execute")
        if self.__no_change_user:
            raise CannotExecuteAsUser(
                "Multiple attempts of changing user detected -- a bug must be causing loop."
            )

        # Use sudo to re-execute this script with the correct user.  We also pass in --no-change-user to prevent
        # us from re-executing the script again to change the user, to
        # head of any potential bugs that could cause infinite loops.
        arguments = [
            "sudo",
            "-u",
            user_name,
            sys.executable,
            script_file,
            "--no-change-user",
        ] + script_arguments

        print("Running as %s" % user_name, file=sys.stderr)
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
        self._log_init_debug(
            "Checking if agent is running %s" % scalyr_util.get_pid_tid()
        )
        pid = self.__read_pidfile()

        if fail_if_running and pid is not None:
            raise AgentAlreadyRunning(
                "The pidfile %s exists and indicates it is running pid=%d"
                % (self.__pidfile, pid)
            )

        if fail_if_not_running and pid is None:
            raise AgentNotRunning(
                "The pidfile %s does not exist or listed process is not running."
                % self.__pidfile
            )

        return pid is not None

    def start_agent_service(self, agent_run_method, quiet, fork=True):
        """Start the daemon process by forking a new process.

        This method will invoke the agent_run_method that was passed in when initializing this object.
        """
        self._log_init_debug("Starting agent %s" % scalyr_util.get_pid_tid())

        # NOTE: Other code calls "_log_init_debug" method which is responsible for buffering the
        # log lines until the agent initialization phase has finished.
        # We don't need to do that and can use a regular logger object inside the signal handlers,
        # because by the time signal handlers are set up and signal handler function is called,
        # agent and logging initialization process is already completed.
        logger = scalyr_logging.getLogger("scalyr_agent")

        # noinspection PyUnusedLocal
        def handle_interrupt(signal_num, frame):
            """
            Signal handler which is invoked on SIGINT signal.

            It takes care of gracefully shutting down the process when running in foreground
            (non-fork) mode.
            """
            logger.debug("Received SIGINT signal")

            if not fork:
                # When forking is disabled and main process runs in the foreground, we can't CTRL+C
                # to work as expected and result in the termination handler being started and
                # process exiting.
                sys.stderr.write(
                    "Received CTRL+C, starting termination handler and exiting...\n"
                )
                handle_terminate(signal_num, frame)
                return

        # noinspection PyUnusedLocal
        def handle_terminate(signal_num, frame):
            """
            Signal handler which is invoked on SIGTERM signal.

            It takes care of invoking the agent termination handler function.
            """
            # Termination handler will cause log handlers to be closed so we need to check if they
            # are still opened before trying to log a message.
            if not scalyr_logging.HANDLERS_CLOSED:
                logger.debug("Received SIGTERM signal")

            if self.__termination_handler is not None:
                if not scalyr_logging.HANDLERS_CLOSED:
                    logger.debug("Invoking termination handler...")
                self.__termination_handler()

        # noinspection PyUnusedLocal
        def handle_sigusr1(signal_num, frame):
            """
            Signal handler which is invoked on SIGUSR1 signal.

            It takes care of invoking the status handler function.
            """
            logger.debug("Received SIGUSR1 signal")

            if self.__status_handler is not None:
                logger.debug("Invoking status handler...")
                self.__status_handler()

        # Start the daemon by forking off a new process.  When it returns, we are either the original process
        # or the new forked one.  If it are the original process, then we just return.
        if fork:
            if not self.__daemonize():
                return
        else:
            # we are not a fork, so write the pid to a file
            if not self.__write_pidfile():
                raise AgentAlreadyRunning(
                    "The pidfile %s exists and indicates it is running pid=%s"
                    % (self.__pidfile, six.text_type(self.__read_pidfile()))
                )

        # Register signal handlers for various signals.
        # On TERM we terminate the process, in USR1 we write a status file and on INT we terminate
        # the process when running in foreground (non-fork) mode
        # scalyr-agent-2 status -v uses SIGUSR1 underneath
        # scalyr-agent-2 status -H uses SIGUSR2 underneath
        original_term = signal.signal(signal.SIGTERM, handle_terminate)
        original_interrupt = signal.signal(signal.SIGINT, handle_interrupt)
        original_usr1 = signal.signal(signal.SIGUSR1, handle_sigusr1)

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
            signal.signal(signal.SIGUSR1, original_usr1)

    def stop_agent_service(self, quiet):
        """Stop the daemon

        @param quiet:  If True, the only error information will be printed to stdout and stderr.
        """
        # Get the pid from the pidfile
        pid = self.__read_pidfile()

        if not pid:
            message = (
                "Failed to stop the agent because it does not appear to be running.  pidfile %s does not exist"
                " or listed process is not running.\n"
            )
            sys.stderr.write(message % self.__pidfile)
            return 0  # not an error in a restart

        if not quiet:
            print("Sending signal to terminate agent.")

        # Try killing the daemon process
        try:
            # Do 5 seconds worth of TERM signals.  If that doesn't work, KILL it.
            term_attempts = 50
            while term_attempts > 0:
                os.kill(pid, signal.SIGTERM)
                PosixPlatformController.__sleep(0.1)
                term_attempts -= 1

            if not quiet:
                print("Still waiting for agent to terminate, sending KILL signal.")

            while 1:
                os.kill(pid, signal.SIGKILL)
                # Workaround for defunct / hanging process when using --no-fork
                os.waitpid(pid, 0)
                PosixPlatformController.__sleep(0.1)

        except OSError as err:
            err = six.text_type(err)
            if "No such process" in err or "No child processes" in err:
                if os.path.exists(self.__pidfile):
                    os.remove(self.__pidfile)
            else:
                print("Unable to terminate agent.")
                print(six.text_type(err))
                return 1

        if not quiet:
            # Warning, do not change this output.  The config_main.py file looks for this message when
            # upgrading a tarball install to make sure the agent was running.
            print("Agent has stopped.")

        return 0

    def request_agent_status(self):
        """Invoked by a process that is not the agent to request the current agent dump the current detail
        status to the status file.

        This is used to implement the 'scalyr-agent-2 status -v' and `-H` features.

        @return: If there is an error, an errno that describes the error.  errno.EPERM indicates the current does not
            have permission to request the status.  errno.ESRCH indicates the agent is not running.
        """

        pid = self.__read_pidfile()
        if pid is None:
            return errno.ESRCH

        try:
            os.kill(pid, signal.SIGUSR1)
        except OSError as e:
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

        This is used to implement the 'scalyr-agent-2 status -v' and `-H` features.

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
            print("Ignoring exception while sleeping")

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
            self._log_init_debug("%s %s" % (message, scalyr_util.get_pid_tid()))

        def logger(message):
            self._log_init("%s %s" % (message, scalyr_util.get_pid_tid()))

        manager = PidfileManager(self.__pidfile)
        manager.set_options(debug_logger=debug_logger, logger=logger)
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
        # A function that takes a single argument that will be invoked whenever this abstraction wishes to
        # report a message that should be included in the log.
        self.__logger = None
        # A function that takes a single argument that will be invoked whenever this abstraction wishes to
        # report a debug message.
        self.__debug_logger = None

    def read_pid(self):
        """Reads the pid file and returns the process id contained in it.

        This also verifies as best as it can that the process returned is running and is really an agent
        process.

        Note, if the agent is just in the process of starting, this might still return None due to race conditions.

        @return The id of the agent process or None if there is none or it cannot be read.
        @rtype: int or None
        """
        # The current invariants on the pidfile:
        #    - Contents: "$pid locked\n" where $pid is the process of the running agent.
        #          We used "locked" to distinguish that the agent is using the new method of locking the pidfile
        #          by holding a flock on it.  Finally, it is really important we terminate it with a newline
        #          because when we read the file, it is how we know if the file has been finished being written.
        #    - While the agent is running:
        #       * holds an exclusive flock on the pid file.
        #    - When the agent terminates:
        #       * the flock is released and the file is deleted.  Note, due to crashes, the file may not be
        #         actually deleted.
        #
        # Note, we do have to handle legacy pidfiles with this code base -- after all, when we upgrade,
        # we need the new agent to understand that the old one is still running.
        # So, if the pidfile does not have 'locked' in it, we fall back to the scheme where we look to see if the
        # pid is still running using a kill call.
        pf = None
        self._log_debug("Reading pidfile")
        try:
            # Read the pidfile
            try:
                pf = open(self.__pidfile, "r")
                raw_contents = pf.read()
            except IOError:
                self._log("Checked pidfile: does not exist")
                return None

            if "\n" not in raw_contents:
                # This means the write to the pidfile is half-finished, so we just pretend like the file
                # did not exist.  This means the higher level code will think the agent isn't running, but
                # that's ok because this can have false negatives (and the agent is just starting, so who's to
                # say that we looked before it had even written the file).
                self._log("Checked pidfile: not finished writing")
                return None
            contents = raw_contents.strip().split()

            # Attempt to get a lock on it to see if the agent process is actually still holding a lock on it.
            try:
                fcntl.flock(pf, fcntl.LOCK_SH | fcntl.LOCK_NB)
                was_locked = False
                try:
                    fcntl.flock(pf, fcntl.LOCK_UN)
                except IOError as e:
                    self._log_debug(
                        "Unexpected error seen releasing lock: %s" % six.text_type(e)
                    )
            except IOError as e:
                # Triggered if the LOCK_SH call fails, indicating another process holds the lock.
                if (e.errno == errno.EAGAIN) or (e.errno == errno.EACCES):
                    was_locked = True
                else:
                    self._log_debug(
                        "Unexpected error seen checking on lock status: %s"
                        % six.text_type(e)
                    )
                    was_locked = False
            pf.close()
            pf = None

        finally:
            if pf is not None:
                pf.close()

        pid = int(contents[0])

        # If the pid file was locked, we know the agent is still running.
        if was_locked:
            self._log("Checked pidfile: exists")
            return pid

        # If contents contains a single item (the pid), then we are using the latest version of the pidfile which
        # only stores the pid, and which is locked for the duration of the agent process.
        # If we are here, then the file is not locked, in which case the process is no longer running
        # (since the file was not locked)
        if len(contents) == 1:
            self._log("Checked pidfile: missing-")
            return None

        # If we see 'locked' in the pidfile, then we know an older agent did write it, but it's no longer running
        # (since the file was not locked).
        if len(contents) == 2 and contents[1] == "locked":
            self._log("Checked pidfile: missing-")
            return None

        # We have a legacy agent pid file.  We see if the process is still alive on the pid in the pidfile.
        try:
            os.kill(pid, 0)
        except OSError as e:
            # ESRCH indicates the process is not running, in which case we ignore the pidfile.
            if e.errno == errno.ESRCH:
                self._log("Checked pidfile: missing+")
                return None
            # EPERM indicates the current user does not have permission to signal the process.. so, we just assume
            # it is the agent.
            elif e.errno != errno.EPERM:
                raise e

        self._log("Checked pidfile: exists*")
        return pid

    def create_writer(self):
        """Creates an object that will help atomically locking the pidfile and updating it to point to the
        current process.

        @return: An object that can be used to write the pid.
        @rtype: PidfileManager.PidWriter
        """
        return PidfileManager.PidWriter(self.__pidfile, self)

    def set_options(self, logger=None, debug_logger=None):
        """Sets some options related to managing the pid.

        @param logger A callback that takes a single argument ``message``.  This callback will be invoked
            whenever the abstraction wishes to log a message.  We have to take this approach rather than
            just relying on the logger abstractions because the process has not opened the agent log by the time
            the pidfile is being checked.
        @param debug_logger A callback that takes a single argument ``message``.  This callback will be invoked
            whenever the abstraction wishes to log a debug message.

        @type logger: Function(str)
        @type debug_logger: Function(str)
        """
        if logger is not None:
            self.__logger = logger
        if debug_logger is not None:
            self.__debug_logger = debug_logger

    def _log_debug(self, message):
        if self.__debug_logger is not None:
            self.__debug_logger(message)

    def _log(self, message):
        if self.__logger is not None:
            self.__logger(message)

    class PidWriter(object):
        """Used to atomically acquire the lock on the pidfile and rewrite its contents to point to
        the current process.

        This abstraction breaks acquiring the lock into a separate operation from updating it.  That's because
        we could acquire the lock before we fork the agent, because flocks are passed to child processes.  This
        would simplify the child process' logic (because it would know for sure it can be the new agent).  However,
        this approach is currently controlled using a config flag because not all POSIX systems have a true
        implement of flock and I'm too nervous to turn it on.  After all, it just solves a very particular
        race condition.
        """

        def __init__(self, pidfile, manager):
            """Initializes the writer.

            @param pidfile  The path to the pidfile.
            @param manager:  The instance of the manager that created this writer.
            @type pidfile: str
            @type manager: PidfileManager
            """
            self.__pidfile = pidfile
            self.__manager = manager
            self.__locked_fd = None

        def acquire_pid_lock(self):
            """Atomically acquire the lock on the pid file, if no one else has the lock.

            If the file does not exist, this call will create it.  If the file does exist, its contents
            are not changed until ``write_pid`` is actually invoked.

            You do not need to invoke this before ``write_pid``.  If it has not been invoked, ``write_pid`` will
            acquire the lock.

            This can be used by a parent process to lock the pidfile and then have a forked child process actually
            write its pid to the pidfile.

            This method is guaranteed to not give false positive (saying you have the lock when there is another
            process has it).

            @return:  If the lock was acquired, then a function that, when invoked, will release the lock.  If
                the lock was not acquired, None.  Note, you may disregard the returned function if you subsequently
                invoke ``write_pid``.  IMPORTANT:  Do not release the lock on the pidfile until the agent process
                terminates.
            @rtype: Func
            """
            # By the time we leave this method, we must either have a lock on the file
            # or we saw that the file exists and we could not get the lock on it.

            # Note, it's important to call read_pid to see if it things an agent is running since ``read_pid``
            # checks legancy pid methods, whereas the code below only checks the current pid scheme.
            if self.__manager.read_pid() is not None:
                return None

            # Check if file exists, and if not, we have to be sure to create exclusively... we have to guarantee
            # that there is only one inode out there for this file among all processes ... we can't create the
            # file in one process, get an fd for it, and then have another process create the file again (unknowningly
            # overwriting the first one) and get another fd for it.  That would mean they would be getting locks on
            # different files.
            fd = None
            """ @type: int"""
            if not os.path.isfile(self.__pidfile):
                try:
                    self._log_debug("Creating pidfile")
                    fd = os.open(self.__pidfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except OSError as e:
                    if e.errno != errno.EEXIST:
                        raise e

            if fd is None:
                try:
                    # If the file already exist, open it for write.. but be sure not to create it if it does not
                    # exist.  That would mean someone, since our os.path.isfile check deleted it... which means
                    # an agent just finished... we pretend like we got a colision and couldn't become the agent.
                    fd = os.open(self.__pidfile, os.O_WRONLY)
                    self._log_debug("Opened pidfile for writing")
                except OSError as e:
                    if e.errno == errno.ENOENT:
                        # Someone just deleted the pid file.. an agent is just finishing, so just say we couldn't
                        # acquire the lock.
                        self._log("Acquire pidfile failed*")
                        return None
                    else:
                        raise e

            fp = None
            try:
                try:
                    # Grab the lock on the file if possible.
                    fp = os.fdopen(fd, "w")
                    fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except IOError as e:
                    if (e.errno == errno.EAGAIN) or (e.errno == errno.EACCES):
                        # Someone else had the lock.
                        self._log("Acquire pidfile failed-")
                        return None
                    else:
                        raise e

                self.__locked_fd = fp
                self._log("Acquire succeeded")
                fp = None
                fd = None
                return self.__release_lock
            finally:
                if fp is not None:
                    fp.close()
                elif fd is not None:
                    os.close(fd)

        def write_pid(self, pid=None):
            """Writes the current process id into the pid file, acquiring the lock if needed.

            This must be invoked to actually update the contents of the pidfile.  It is not necessary to invoke
            ``acquire_pid_lock`` before invoking this method.

            This will not return a false positive.  If the method indicates the pidfile was successfully locked
            and acquired, then no other process believes it is the agent.

            @param pid:  The pid to write into the pidfile.  This is only used for testing.  If None, the current
                processes pid is used.
            @type pid: int
            @return:  If the lock was acquired and the pid was successfully written, then returns a function that, when
                invoked, will release the lock.  This function should be used in place of any previous one returned
                by ``acquire_pid_lock``.  IMPORTANT:  Do not release the lock on the pidfile until the agent process
                terminates.
            @rtype: Func
            """
            if self.__locked_fd is None:
                self.acquire_pid_lock()
            else:
                # If we already acquire_pid_lock was already invoked, then we might be using the scheme where a
                # parent process acquired it separately.  To help cover over the fact some POSIX systems do not
                # have a proper flock implementation, try to make sure we really have the lock.
                try:
                    fcntl.flock(self.__locked_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._log_debug("Refreshed pidfile lock")
                except IOError as e:
                    if (e.errno == errno.EAGAIN) or (e.errno == errno.EACCES):
                        self._log("Write pidfile failed-")
                        return None
                    else:
                        raise e

            if self.__locked_fd is None:
                self._log("Write pidfile failed+")
                return None

            if pid is None:
                pid = os.getpid()

            fp = self.__locked_fd
            fp.truncate()
            # Very important that we terminate this with a newline.
            fp.write("%d\n" % pid)
            self._log("Wrote pidfile")

            # make sure that all data is on disk
            fp.flush()
            os.fsync(fp.fileno())

            return self.__release_lock

        def __release_lock(self):
            """Invoked to release the lock on the pidfile.

            This should only be called when the process terminates.
            @return:
            @rtype:
            """
            if self.__locked_fd is None:
                return

            os.unlink(self.__pidfile)
            try:
                fcntl.flock(self.__locked_fd, fcntl.LOCK_UN)
            except IOError as e:
                self._log("Unexpected error seen releasing lock: %s" % six.text_type(e))

            self.__locked_fd.close()
            self.__locked_fd = None

        def _log_debug(self, message):
            # noinspection PyProtectedMember
            self.__manager._log_debug(message)

        def _log(self, message):
            # noinspection PyProtectedMember
            self.__manager._log(message)


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
            assert not hasattr(source_fp, "file")

            self.__fp = os.fdopen(os.dup(source_fp.fileno()), "w+b")

            assert self.__fp.fileno() != source_fp.fileno()

    def close(self):
        """Closes the status reporter.  This must be invoked by all processes.
        """
        self.__fp.close()

    def report_status(self, message):
        """Report the specified string back to the other process listening on this instance.

        @param message: The text string to send.  For safety's sake, this probably should only include low ascii
            characters.
        @type message: six.text_type
        """
        # We write out the number of bytes in the message followed by the message.  The number of bytes might be
        # different from the message length in the case of higher ascii, but we'll punt on that for now.
        # 2->TODO message needs to be encoded in Python3
        encoded_message = message.encode("utf-8")
        self.__fp.write(b"%d\n" % len(encoded_message))
        self.__fp.write(b"%s" % encoded_message)
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
            if num_bytes != b"":
                message = self.__fp.read()
                if len(message) == int(num_bytes):
                    # 2->TODO return unicode
                    return message.decode("utf-8")
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
    return os.path.isfile("/proc/%d/cmdline" % pid)


def _read_command_line(pid):
    """Reads the commandline arguments for the specified pid and returns the contents.

    @param pid: The id of the process.
    @type pid: int

    @return: The commandline arguments with no spaces.
    @rtype: str
    """
    pf = None
    try:
        pf = open("/proc/%d/cmdline" % pid, "r")
        return pf.read().strip()
    finally:
        if pf is not None:
            pf.close()
