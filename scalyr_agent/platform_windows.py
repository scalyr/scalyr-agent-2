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
# author: Scott Sullivan <guy.hoozdis@gmail.com>
import atexit

__author__ = 'guy.hoozdis@gmail.com'

import sys
import time
import struct
import threading
import random
import os

if sys.platform != 'win32':
    raise Exception('Attempting to load platform_windows module on a non-Windows machine')

# TODO:
#  * Control flow (agent_run_method returns => stop service)
import servicemanager
import win32serviceutil
import win32service
import win32event
import win32file
import win32api
import win32security
import win32process
import _winreg
import win32pipe
import winerror
import pywintypes

import win32com

try:
    import psutil
except ImportError:
    raise Exception('You must install the python module "psutil" to run on Windows.  Typically, this can be done with'
                    'the following command:  pip install psutil')

# TODO(windows): Get rid of this logging method, or name it to something better.
def log(msg):
    servicemanager.LogInfoMsg(msg)

from __scalyr__ import get_install_root, scalyr_init
scalyr_init()

from scalyr_agent.json_lib import JsonObject
from scalyr_agent.util import StoppableThread

# TODO(windows): Remove this once we verify that adding the service during dev stag works correclty
try:
    from scalyr_agent.platform_controller import PlatformController, DefaultPaths, CannotExecuteAsUser
    from scalyr_agent.platform_controller import AgentAlreadyRunning, ChangeUserNotSupported
except:
    etype, emsg, estack = sys.exc_info()
    log("%s - %s" % (etype, emsg.message))





# TODO(windows): Rename and document this method.
def QueryServiceStatusEx(servicename):
    hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        hs = win32serviceutil.SmartOpenService(hscm, servicename, win32service.SERVICE_QUERY_STATUS)
        try:
            status = win32service.QueryServiceStatusEx(hs)
        finally:
            win32service.CloseServiceHandle(hs)
    finally:
        win32service.CloseServiceHandle(hscm)
    return status

_REG_PATH = r"SOFTWARE\Scalyr\Settings"
_CONFIG_KEY = 'ConfigPath'


def _set_config_path_registry_entry(value):
    _winreg.CreateKey(_winreg.HKEY_LOCAL_MACHINE, _REG_PATH)
    registry_key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, _REG_PATH, 0,
                                   _winreg.KEY_WRITE)
    _winreg.SetValueEx(registry_key, _CONFIG_KEY, 0, _winreg.REG_SZ, value)
    _winreg.CloseKey(registry_key)
    return True


def _get_config_path_registry_entry():
    registry_key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, _REG_PATH, 0,
                                   _winreg.KEY_READ)
    value, regtype = _winreg.QueryValueEx(registry_key, _CONFIG_KEY)
    _winreg.CloseKey(registry_key)
    return value


class ScalyrAgentService(win32serviceutil.ServiceFramework):
    # TODO(windows): Do these really need to be separate vars.  If so, then document them.
    _svc_name_ = "ScalyrAgentService"
    _svc_display_name_ = "Scalyr Agent Service"
    _svc_description_ = "Hosts Scalyr metric collectors"

    # Custom/user defined control messages
    SERVICE_CONTROL_DETAILED_REPORT = win32service.SERVICE_USER_DEFINED_CONTROL - 1 

    def __init__(self, *args):
        self.controller = None
        win32serviceutil.ServiceFramework.__init__(self, *args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)

    def log(self, msg):
        servicemanager.LogInfoMsg(msg)

    def sleep(self, sec):
        win32api.Sleep(sec*1000, True)

    def SvcStop(self):
        self.log('Stopping scalyr service')
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self._stop_event)
        self.controller.invoke_termination_handler()
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        self.ReportServiceStatus(win32service.SERVICE_START_PENDING)
        try:
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            self.log('Starting service')
            self.start()
            self.log('Waiting for stop event')
            win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)
            self.log('Stop event triggered')
        except Exception, e:
            self.log('ERROR: {}'.format(e))
            self.SvcStop()

    def start(self):
        # TODO(windows): Get rid of need to for the parser.  Fix this method.
        # Remove the parser.
        from scalyr_agent.agent_main import ScalyrAgent
        self.controller = WindowsPlatformController()
        ScalyrAgent.agent_run_method(self.controller, _get_config_path_registry_entry())

    def SvcOther(self, control):
        if ScalyrAgentService.SERVICE_CONTROL_DETAILED_REPORT == control:
            self.controller.invoke_status_handler()
        else:
            win32serviceutil.ServiceFramework.SvcOther(self, control)


class WindowsPlatformController(PlatformController):
    """A controller instance for Microsoft's Windows platforms
    """
    def __init__(self):
        """Initializes the Windows platform instance.
        """
        # The method to invoke when termination is requested.
        self.__termination_handler = None
        # The method to invoke when status is requested by another process.
        self.__status_handler = None
        # The file path to the configuration.  We need to stash this so it is available when start is invoked.
        self.__config_file_path = None

        # The local domain Administrators name.
        self.__local_administrators = u'%s\\Administrators' % win32api.GetComputerName()

        self.__no_change_user = False

        PlatformController.__init__(self)

    def invoke_termination_handler(self):
        if self.__termination_handler:
            self.__termination_handler()

    def invoke_status_handler(self):
        if self.__status_handler:
            self.__status_handler()

    def can_handle_current_platform(self):
        """Returns true if this platform object can handle the server this process is running on.

        @return: True if this platform instance can handle the current server.
        @rtype: bool
        """
        return 'win32' == sys.platform

    @property
    def default_paths(self):
        """Returns the default paths to use for various configuration options for this platform.

        @return: The default paths
        @rtype: DefaultPaths
        """
        # TODO(windows): Fix this method.
        # NOTE: For this module, it is assumed that the 'install_type' is always PACKAGE_INSTALL

        root = get_install_root()
        logdir = os.path.join(root, 'log')
        libdir = os.path.join(root, 'lib')
        config = os.path.join(root, 'config', 'agent.json')

        return DefaultPaths(logdir, config, libdir)

    def consume_config(self, config, path_to_config):
        """Invoked after 'consume_options' is called to set the Configuration object to be used.

        This will be invoked before the scalyr-agent-2 command performs any real work and while stdout and stderr
        are still be displayed to the screen.

        @param config: The configuration object to use.  It will be None if the configuration could not be parsed.
        @param path_to_config: The full path to file that was read to create the config object.

        @type config: configuration.Configuration
        @type path_to_config: str
        """
        self.__config_file_path = os.path.abspath(path_to_config)

    @property
    def default_monitors(self):
        """Returns the default monitors to use for this platform.

        This is guaranteed to be invoked after consume_config is called to allow implementations to make what they
        return be dependent on configuration options.

        This method should list of dicts containing monitor configuration options just as you would specify them in
        the configuration file.  The list may be empty.

        @return: The default monitors
        @rtype: list<dict>
        """
        monitors = [
            JsonObject(
                module='scalyr_agent.builtin_monitors.windows_system_metrics'
            ),
            JsonObject(
                module='scalyr_agent.builtin_monitors.windows_process_metrics',
                pid='$$',
                id='agent'
            ),
        ]
        return monitors

    def get_file_owner(self, file_path):
        """Returns the user name of the owner of the specified file.

        @param file_path: The path of the file.
        @type file_path: str

        @return: The user name of the owner.
        @rtype: str
        """
        sd = win32security.GetFileSecurity(file_path, win32security.OWNER_SECURITY_INFORMATION)
        owner_sid = sd.GetSecurityDescriptorOwner()
        name, domain, account_type = win32security.LookupAccountSid(None, owner_sid)
        if name == 'Administrators':
            return self.__local_administrators
        else:
            return u'%s\\%s' % (domain, name)

    def set_file_owner(self, file_path, owner):
        """Sets the owner of the specified file.

        @param file_path: The path of the file.
        @param owner: The new owner of the file.  This should be a string returned by either `get_file_ower` or
            `get_current_user`.
        @type file_path: str
        @type owner: str
        """
        # Lookup the user info by their name.  We need their sid, which will be in the 0th element of user_info.
        domain_user = owner.split('\\')
        user_info = win32security.LookupAccountName(domain_user[0], domain_user[1])

        # Get the current acl so we can just replace the owner information.
        owner_acl = win32security.GetFileSecurity(file_path, win32security.OWNER_SECURITY_INFORMATION)

        owner_acl.SetSecurityDescriptorOwner(user_info[0], True)
        win32security.SetFileSecurity(file_path, win32security.OWNER_SECURITY_INFORMATION, owner_acl)

    def get_current_user(self):
        """Returns the effective user name running this process.

        The effective user may not be the same as the initiator of the process if the process has escalated its
        privileges.

        @return: The name of the effective user running this process.
        @rtype: str
        """
        # As a little hack, we pretend anyone that has administrative privilege is running as
        # the local user 'Administrators' (note the 's').  This will result in us setting the configuration file
        # to be owned by 'Administrators' which is the right thing to do.
        if win32com.shell.shell.IsUserAnAdmin():
            return self.__local_administrators
        else:
            return win32api.GetUserNameEx(win32api.NameSamCompatible)

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
        if user_name != self.__local_administrators:
            raise CannotExecuteAsUser('The current Scalyr Agent implementation only supports running the agent as %s' %
                                      self.__local_administrators)
        if script_binary is None:
            raise CannotExecuteAsUser('The current Scalyr Agent implementation only supports running binaries when '
                                      'executing as another user.')

        return _run_as_administrators(script_binary, script_arguments + ['--no-change-user'])

    def is_agent_running(self, fail_if_running=False):
        """Returns true if the agent service is running, as determined by this platform implementation.

        This will optionally raise an Exception with an appropriate error message if the agent is not running.

        @param fail_if_running:  True if the method should raise an Exception with a platform-specific error message
            explaining how it determined the agent is not running.
        @type fail_if_running: bool

        @return: True if the agent process is already running.
        @rtype: bool

        @raise AgentAlreadyRunning: If the agent is running and fail_if_running is True.
        """
        status = QueryServiceStatusEx(ScalyrAgentService._svc_name_)
        state = status['CurrentState']

        if fail_if_running and state in (win32service.SERVICE_RUNNING, win32service.SERVICE_START_PENDING):
            pid = status['ProcessId']
            raise AgentAlreadyRunning('The agent appears to be running pid=%d' % pid) 

        return state in (win32service.SERVICE_RUNNING, win32service.SERVICE_START_PENDING)

    def start_agent_service(self, agent_run_method, quiet):
        """Start the agent service using the platform-specific method.

        This method must return once the agent service has been started.

        @param agent_run_method: The method to invoke to actually run the agent service.  This method takes one
            argument, the reference to this controller.  Note, if your platform implementation cannot use this
            function pointer (because the service is running in a separate address space and cannot be passed this
            pointer), then instead of invoking this method, you may invoke ScalyrAgent.agent_run_method instead.
        @param quiet: True if only error messages should be printed to stdout, stderr.

        @type agent_run_method: func(PlatformController)
        @type quiet: bool
        """
        # TODO: Add Error handling.  Insufficient privileges will raise an exception
        # that is currently unhandled.
        _set_config_path_registry_entry(self.__config_file_path)
        win32serviceutil.StartService(ScalyrAgentService._svc_name_)

    def stop_agent_service(self, quiet):
        """Stops the agent service using the platform-specific method.

        This method must return only after the agent service has terminated.

        @param quiet: True if only error messages should be printed to stdout, stderr.
        @type quiet: bool
        """
        # TODO: Add Error handling. Trying to stop a service that isn't running
        # will raise an exception that is currently unhandled.
        win32serviceutil.StopService(ScalyrAgentService._svc_name_)

    def get_usage_info(self):
        """Returns CPU and memory usage information.

        It returns the results in a tuple, with the first element being the number of
        CPU seconds spent in user land, the second is the number of CPU seconds spent in system land,
        and the third is the current resident size of the process in bytes."""
        # TODO: Implement the data structure (cpu, sys, phy_ram)
        # TODO(windows): Fix the RAM value.
        cpu_usage = psutil.cpu_times()
        user_cpu = cpu_usage.user
        system_cpu = cpu_usage.system
        return (user_cpu, system_cpu, 0)

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

    def request_agent_status(self):
        """Invoked by a process that is not the agent to request the current agent dump the current detail
        status to the status file.

        This is used to implement the 'scalyr-agent-2 status -v' feature.

        @return: If there is an error, an errno that describes the error.  errno.EPERM indicates the current does not
            have permission to request the status.  errno.ESRCH indicates the agent is not running.
        """
        # TODO(czerwin): Return an appropriate error message.
        win32serviceutil.ControlService(ScalyrAgentService._svc_name_,
                                        ScalyrAgentService.SERVICE_CONTROL_DETAILED_REPORT)

    def add_options(self, options_parser):
        """Invoked by the main method to allow the platform to add in platform-specific options to the
        OptionParser used to parse the commandline options.

        @param options_parser:
        @type options_parser: optparse.OptionParser
        """
        options_parser.add_option("", "--redirect-to-pipe", dest="redirect_pipe",
                                  help="Used to redirect stdin/stdout to a named pipe.  Used internally.")
        options_parser.add_option("", "--no-change-user", action="store_true", dest="no_change_user", default=False,
                                  help="Forces agent to not change which user is executing agent.  Requires the right "
                                       "user is already being used.  This is used internally to prevent infinite loops "
                                       "in changing to the correct user.  Users should not need to set this option.")

    def consume_options(self, options):
        """Invoked by the main method to allow the platform to consume any command line options previously requested
        in the 'add_options' call.

        @param options: The object containing the options as returned by the OptionParser.
        """
        self.__no_change_user = options.no_change_user

        if options.redirect_pipe is not None:
            redirection = PipeRedirectorServer(options.redirect_pipe)
            redirection.start()
            atexit.register(redirection.stop)


class PipeRedirectorServer(object):
    def __init__(self, pipe_name):
        self.__pipe_name = pipe_name
        self.__pipe_handle = None
        self.__pipe_lock = threading.Lock()
        self.__old_stdout = None
        self.__old_stderr = None

    def start(self):
        self.__pipe_handle = win32pipe.CreateNamedPipe(self.__pipe_name, win32pipe.PIPE_ACCESS_OUTBOUND,
                                                       win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT,
                                                       1, 65536, 65536, 5000, None)

        win32pipe.ConnectNamedPipe(self.__pipe_handle, None)
        self.__old_stdout = sys.stdout
        self.__old_stderr = sys.stderr

        sys.stdout = PipeRedirectorServer.Redirector(0, self._write_stream)
        sys.stderr = PipeRedirectorServer.Redirector(1, self._write_stream)

    def _write_stream(self, stream_id, content):
        encoded_content = unicode(content).encode('utf-8')
        code = len(encoded_content) * 2 + stream_id

        self.__pipe_lock.acquire()
        try:
            if self.__pipe_lock is not None:
                win32file.WriteFile(self.__pipe_handle, struct.pack('I', code) + encoded_content)
            elif stream_id == 0:
                sys.stdout.write(content)
            else:
                sys.stderr.write(content)
        finally:
            self.__pipe_lock.release()

    def stop(self):
        self.__pipe_lock.acquire()
        try:
            win32file.WriteFile(self.__pipe_handle, struct.pack('I', 0))
            win32file.FlushFileBuffers(self.__pipe_handle)
            win32pipe.DisconnectNamedPipe(self.__pipe_handle)
            self.__pipe_handle = None
        finally:
            self.__pipe_lock.release()

        sys.stdout = self.__old_stdout
        sys.stderr = self.__old_stderr

    class Redirector(object):
        def __init__(self, stream_id, writer_func):
            self.__writer_func = writer_func
            self.__stream_id = stream_id

        def write(self, output_buffer):
            self.__writer_func(self.__stream_id, output_buffer)


class PipeRedirectorClient(StoppableThread):
    def __init__(self, pipe_name=None):
        StoppableThread.__init__(self)
        if pipe_name is None:
            pipe_name = 'scalyr_agent_redir_%d' % random.randint(0, 4096)
        self.__pipe_name = r'\\.\pipe\%s' % pipe_name

    def run(self):
        file_exists = False
        overall_deadline = time.time() + 60.0

        while self._is_running():
            try:
                win32pipe.WaitNamedPipe(self.__pipe_name, 100)
                file_exists = True
                break
            except pywintypes.error, e:
                if e[0] == winerror.ERROR_FILE_NOT_FOUND:
                    self._sleep_for_busy_loop(overall_deadline)

        if not self._is_running():
            return

        if not file_exists:
            print >>sys.stderr, 'Unable to receive stdout/stdin from running process, giving up.'
            return

        file_handle = None

        try:
            file_handle = win32file.CreateFile(self.__pipe_name, win32file.GENERIC_READ, 0, None,
                                               win32file.OPEN_EXISTING, 0, None)

            while self._is_running():
                # Busy wait for bytes to become available.
                while self._is_running():
                    (tmp_buffer, num_bytes_available, result) = win32pipe.PeekNamedPipe(file_handle, 1024)
                    if num_bytes_available > 0:
                        break
                    self._sleep_for_busy_loop(overall_deadline)

                code = struct.unpack('I', win32file.ReadFile(file_handle, 4)[1])[0]    # Read str length
                if code == 0:
                    break
                bytes_to_read = code >> 1
                stream_id = code % 2

                content = win32file.ReadFile(file_handle, bytes_to_read)[1].decode('utf-8')
                if stream_id == 0:
                    sys.stdout.write(content)
                else:
                    sys.stderr.write(content)
        finally:
            if file_handle is not None:
                win32file.CloseHandle(file_handle)

    @property
    def pipe_name(self):
        return self.__pipe_name

    def _is_running(self):
        return self._run_state.is_running()

    def _sleep_for_busy_loop(self, deadline):
        timeout = deadline - time.time()
        if timeout < 0:
            raise Exception('The operation took too long, giving up.')
        elif timeout > .01:
            timeout = .01
        self._run_state.sleep_but_awaken_if_stopped(timeout)


def _run_as_administrators(executable, arguments):
    client = PipeRedirectorClient()
    arguments = arguments + ['--redirect-to-pipe', client.pipe_name]

    child_process = win32com.shell.shell.ShellExecuteEx(fMask=256 + 64, lpVerb='runas', lpFile=executable,
                                                        lpParameters=' '.join(arguments))
    client.start()

    proc_handle = child_process['hProcess']
    win32event.WaitForSingleObject(proc_handle, -1)

    client.stop()
    return win32process.GetExitCodeProcess(proc_handle)

if __name__ == "__main__":
    try:
        rc = win32serviceutil.HandleCommandLine(ScalyrAgentService)
    except:
        log('ERROR: got an exeption in main')
    else:
        log('SUCCESS: no exception in main')
    sys.exit(rc)
