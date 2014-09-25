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

# Based on code by Sander Marechal posted at
# http://web.archive.org/web/20131017130434/http://www.jejik.com/articles/2007/02/a_simple_unix_linux_daemon_in_python/


class UnixDaemonController:
    """A controller instance for Unix-like platforms.

    The controller manages such platform dependent tasks as:
      - Forking a daemon thread to run the agent process in the background
      - Implementing the scheme that determine if the agent process is already running on the host,
        such as by using a PID file.
      - Stopping the agent process.
      - Sending signals to the running agent process.

    TODO:  This is meant to be a central place to put the platform-specific code.  However, it has not been
    full baked yet since we have not yet implemented the Windows version.  When we do implement the Windows version,
    we expect to change this abstraction, create a common base class, and then implement the Windows version as well.
    """

    def __init__(self, pidfile, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.pidfile = pidfile

    def __daemonize(self):
        """Fork off a background thread for execution.  When this method returns, it will be on the new process.

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
                sys.exit(0)
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
        si = file(self.stdin, 'r')
        so = file(self.stdout, 'a+')
        se = file(self.stderr, 'a+', 0)
        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

        # write pidfile
        atexit.register(self.delpid)
        pid = os.getpid()

        fp = None
        try:
            fp = file(self.pidfile, 'w+')
            # If we are on an OS that supports reading the commandline arguments from /proc, then use that
            # to write more unique information about the running process to help avoid pid collison.
            if self.__can_read_command_line(pid):
                fp.write('%d %s\n' % (pid, self.__read_command_line(pid)))
            else:
                fp.write('%d\n' % pid)
        finally:
            if fp is not None:
                fp.close()

    def delpid(self):
        """Deletes the pid file"""
        os.remove(self.pidfile)

    def __read_pidfile(self):
        """Reads the pid file and returns the process id contained in it.

        This also verifies as best as it can that the process returned is running and is really an agent
        process.

        @return The id of the agent process or None if there is none or it cannot be read.
        @rtype: int or None
        """
        try:
            pf = file(self.pidfile, 'r')
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

    def run_as_user(self, user_id, script_file):
        """Restarts this process with the same arguments as the specified user.

        This will re-run the entire Python script so that it is executing as the specified user.
        It will also add in the '--no-change-user' option which can be used by the script being executed with the
        next proces that it was the result of restart so that it probably shouldn't do that again.

        @param user_id: The user id to run as, typically 0 for root.
        @param script_file: The path to the Python script file that was executed.

        @type user_id: int
        @type script_file: str
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
            arguments = ['sudo', '-u', user_name, sys.executable, script_file, '--no-change-user'] + sys.argv[1:]

            print >>sys.stderr, ('Running as %s' % user_name)
            os.execvp("sudo", arguments)

    def is_running(self):
        """
        @return: True if the agent process is already running.
        @rtype: bool
        """
        pid = self.__read_pidfile()
        # TODO: Add in check for the pid file exists but the process is not running.
        return pid is not None

    def fail_if_already_running(self):
        """Exit the process with a non-zero status if the agent is already running.
        """
        pid = self.__read_pidfile()
        if pid:
            message = "The agent appears to be running pid=%d.  pidfile %s does exists.\n"
            sys.stderr.write(message % (pid, self.pidfile))
            sys.exit(1)

    def start_daemon(self, run_method, handle_terminate_method):
        """Start the daemon process by forking a new process.

        @param run_method:  The method to invoke once the fork is complete and this is a daemon process.
        @param handle_terminate_method:  The method to invoke if the daemon process is requested to be terminated
            (such as by receiving a TERM signal)
        """
        # Check for a pidfile to see if the daemon already runs
        self.fail_if_already_running()

        # noinspection PyUnusedLocal
        def handle_terminate(signal_num, frame):
            handle_terminate_method()

        original = signal.signal(signal.SIGTERM, handle_terminate)

        # Start the daemon
        self.__daemonize()
        result = run_method()

        signal.signal(signal.SIGTERM, original)

        if result is not None:
            sys.exit(result)
        else:
            sys.exit(99)

    def stop_daemon(self, quiet):
        """Stop the daemon

        @param quiet:  If True, the only error information will be printed to stdout and stderr.
        """
        # Get the pid from the pidfile
        try:
            pf = file(self.pidfile, 'r')
            pid = int(pf.read().strip())
            pf.close()
        except IOError:
            pid = None

        if not pid:
            message = "The agent does not appear to be running.  pidfile %s does not exist.\n"
            sys.stderr.write(message % self.pidfile)
            return 0  # not an error in a restart

        if not quiet:
            print 'Sending signal to terminate agent.'

        # Try killing the daemon process
        try:
            # Do 5 seconds worth of TERM signals.  If that doesn't work, KILL it.
            term_attempts = 50
            while term_attempts > 0:
                os.kill(pid, signal.SIGTERM)
                UnixDaemonController.__sleep(0.1)
                term_attempts -= 1

            if not quiet:
                print 'Still waiting for agent to terminate, sending KILL signal.'

            while 1:
                os.kill(pid, signal.SIGKILL)
                UnixDaemonController.__sleep(0.1)

        except OSError, err:
            err = str(err)
            if err.find("No such process") > 0:
                if os.path.exists(self.pidfile):
                    os.remove(self.pidfile)
            else:
                print 'Unable to terminate agent.'
                print str(err)
                return 1

        if not quiet:
            # Warning, do not change this output.  The config_main.py file looks for this message when
            # upgrading a tarball install to make sure the agent was running.
            print 'Agent has stopped.'

        return 0

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

    def request_status(self):
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

    def register_for_status_requests(self, handler):
        """Register a method to be invoked if this process is requested to report its status.

        This is used to implement the 'scalyr-agent-2 status -v' feature.

        @param handler:  The method to invoke when status is requested.
        @type handler: func
        """
        # noinspection PyUnusedLocal
        def wrapped_handler(signal_num, frame):
            handler()
        signal.signal(signal.SIGINT, wrapped_handler)

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