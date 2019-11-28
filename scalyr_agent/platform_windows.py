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
import errno

__author__ = 'guy.hoozdis@gmail.com'

import sys
import struct
import random
import os

if sys.platform != 'win32':
    raise Exception('Attempting to load platform_windows module on a non-Windows machine')

# noinspection PyUnresolvedReferences
import servicemanager
# noinspection PyUnresolvedReferences
import win32serviceutil
# noinspection PyUnresolvedReferences
import win32service
# noinspection PyUnresolvedReferences
import win32event
# noinspection PyUnresolvedReferences
import win32file
# noinspection PyUnresolvedReferences
import win32api
# noinspection PyUnresolvedReferences
import win32security
# noinspection PyUnresolvedReferences
import win32process
# noinspection PyUnresolvedReferences
import _winreg
# noinspection PyUnresolvedReferences
import win32pipe
# noinspection PyUnresolvedReferences
import winerror
# noinspection PyUnresolvedReferences
import pywintypes
# noinspection PyUnresolvedReferences
import win32com.shell.shell

try:
    import psutil
except ImportError:
    psutil = None
    raise Exception('You must install the python module "psutil" to run on Windows.  Typically, this can be done with'
                    'the following command:  pip install psutil')

from __scalyr__ import get_install_root, scalyr_init
scalyr_init()

from scalyr_agent.json_lib import JsonObject
from scalyr_agent.util import RedirectorServer, RedirectorClient, RedirectorError
from scalyr_agent.platform_controller import PlatformController, DefaultPaths, CannotExecuteAsUser, AgentNotRunning
from scalyr_agent.platform_controller import AgentAlreadyRunning


# The path where we store our entries in the registry.
_REG_PATH = r"SOFTWARE\Scalyr\Settings"
# The registry key where we store the path to the configuration file.
_CONFIG_KEY = 'ConfigPath'
# The agent service name to use when registering the service with Windows.
_SCALYR_AGENT_SERVICE_ = "ScalyrAgentService"
_SCALYR_AGENT_SERVICE_DISPLAY_NAME_ = "Scalyr Agent Service"
_SERVICE_DESCRIPTION_ = "Collects logs and metrics and forwards them to Scalyr.com"
# A custom control message that is used to signal the agent should generate a detailed status report.
_SERVICE_CONTROL_DETAILED_REPORT_ = win32service.SERVICE_USER_DEFINED_CONTROL - 1


def _set_config_path_registry_entry(value):
    """Updates the Windows registry entry for the configuration file path.

    We store this configuration file path this way so that if the service is restarted, it knows the last location
    of the configuration file.

    @param value: The file path
    @type value: str
    """
    _winreg.CreateKey(_winreg.HKEY_LOCAL_MACHINE, _REG_PATH)
    registry_key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, _REG_PATH, 0,
                                   _winreg.KEY_WRITE)
    _winreg.SetValueEx(registry_key, _CONFIG_KEY, 0, _winreg.REG_SZ, value)
    _winreg.CloseKey(registry_key)
    return True


def _get_config_path_registry_entry(default_config_path):
    """Returns the current value for the configuration file path from the Windows registry.

    @param default_config_path: The path to use for the configuration file if the registry entry does not exist.
    @type default_config_path: str

    @return: The file path.
    @rtype: str
    """
    try:
        registry_key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, _REG_PATH, 0, _winreg.KEY_READ)
        value, regtype = _winreg.QueryValueEx(registry_key, _CONFIG_KEY)
        _winreg.CloseKey(registry_key)
        return value
    except EnvironmentError:
        return default_config_path


# noinspection PyPep8Naming
class ScalyrAgentService(win32serviceutil.ServiceFramework):
    """Implements the Windows service interface and exports the Scalyr Agent as a service.
    """
    # The following fields must be present for py2exe to detect this as a service implementation.
    _svc_name_ = _SCALYR_AGENT_SERVICE_
    _svc_display_name_ = _SCALYR_AGENT_SERVICE_DISPLAY_NAME_

    def __init__(self, *args):
        self.controller = None
        win32serviceutil.ServiceFramework.__init__(self, *args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)

    def log(self, msg):
        servicemanager.LogInfoMsg(msg)

    def error(self, msg):
        servicemanager.LogErrorMsg(msg)

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
            win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)
        except Exception, e:
            self.error('Error, causing Windows Service to exit early %s' % str(e))
            self.SvcStop()

    def start(self):
        from scalyr_agent.agent_main import ScalyrAgent
        self.controller = WindowsPlatformController()
        config_path = _get_config_path_registry_entry(self.controller.default_paths.config_file_path)
        try:
            ScalyrAgent.agent_run_method(self.controller, config_path, perform_config_check=True)
        except Exception, e:
            self.error('Error seen while starting the Scalyr Agent: {}'.format(e))
            self.error('Still attempting to run agent, but you must fix error.  Agent will re-read configuration file '
                       'without restarting it.')
            ScalyrAgent.agent_run_method(self.controller, config_path, perform_config_check=False)

    def SvcOther(self, control):
        # See if the control signal is our custom one, otherwise dispatch it to the superclass.
        if _SERVICE_CONTROL_DETAILED_REPORT_ == control:
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

        # Controls whether or not we warn the user via stdout that we are about to escalate to Administrator privileges.
        self.__no_escalation_warning = False

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
        # NOTE: For this module, it is assumed that the 'install_type' is always PACKAGE_INSTALL

        root = get_install_root()
        logdir = os.path.join(root, 'log')
        libdir = os.path.join(root, 'data')
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

    def get_default_monitors(self, config):
        """Returns the default monitors to use for this platform.

        This method should return a list of dicts containing monitor configuration options just as you would specify
        them in the configuration file.  The list may be empty.

        @param config The configuration object to use.
        @type config configuration.Configuration

        @return: The default monitors
        @rtype: list<dict>
        """
        result = []
        if config.implicit_metric_monitor:
            result.append(JsonObject(module='scalyr_agent.builtin_monitors.windows_system_metrics'))
        if config.implicit_agent_process_metrics_monitor:
            result.append(JsonObject(module='scalyr_agent.builtin_monitors.windows_process_metrics',
                                     pid='$$', id='agent'))
        return result

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
        if self.__no_change_user:
            raise CannotExecuteAsUser('Multiple attempts of escalating privileges detected -- a bug must be causing '
                                      'loop.')

        if not self.__no_escalation_warning:
            print 'The process requires Administrator permissions to complete this action.'
            print 'Attempting to escalate privileges, which will require user confirmation or the Administrator '
            print 'password through a dialog box that is about to be shown.'
            raw_input('Hit Enter to continue and view the dialog box.')

        return self._run_as_administrators(script_binary, script_arguments + ['--no-change-user'])

    def _run_as_administrators(self, executable, arguments):
        """Invokes the specified executable with the specified arguments, escalating the privileges of the process
        to Administrators.

        All output that process generates to stdout/stderr will be echoed to this process's stdout/stderr.

        Note, this can only be used on executables that accept the `--redirect-to-pipe` option to allow for this
        process to capture the output from the escalated process.

        Note, Windows will ask for confirmation and/or an Administrator password before the process is escalated.

        @param executable: The path to the Windows executable to run escalated.
        @param arguments: An array of arguments to supply to the executable.

        @type executable: str
        @type arguments: []

        @return: The exit code of the process.
        @rtype: int
        """
        client = PipeRedirectorClient()
        arguments = arguments + ['--redirect-to-pipe', client.pipe_name]

        child_process = win32com.shell.shell.ShellExecuteEx(fMask=256 + 64, lpVerb='runas', lpFile=executable,
                                                            lpParameters=' '.join(arguments))
        client.start()

        proc_handle = child_process['hProcess']
        win32event.WaitForSingleObject(proc_handle, -1)

        client.stop()
        return win32process.GetExitCodeProcess(proc_handle)

    def is_agent_running(self, fail_if_running=False, fail_if_not_running=False):
        """Returns true if the agent service is running, as determined by this platform implementation.

        This will optionally raise an Exception with an appropriate error message if the agent is running or not
        runnning.

        @param fail_if_running:  True if the method should raise an Exception with a platform-specific error message
            explaining how it determined the agent is running.
        @param fail_if_not_running: True if the method should raise an Exception with a platform-specific error message
            explaining how it determined the agent is not running.

        @type fail_if_running: bool
        @type fail_if_not_running: bool

        @return: True if the agent process is already running.
        @rtype: bool

        @raise AgentAlreadyRunning
        @raise AgentNotRunning
        """

        hscm = None
        hs = None

        try:
            hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            hs = win32serviceutil.SmartOpenService(hscm, _SCALYR_AGENT_SERVICE_,
                                                   win32service.SERVICE_QUERY_STATUS)
            status = win32service.QueryServiceStatusEx(hs)

            state = status['CurrentState']

            is_running = state in (win32service.SERVICE_RUNNING, win32service.SERVICE_START_PENDING)
            if fail_if_running and is_running:
                pid = status['ProcessId']
                raise AgentAlreadyRunning('The operating system reports the Scalyr Agent Service is running with '
                                          'pid=%d' % pid)
            if fail_if_not_running and not is_running:
                raise AgentNotRunning('The operating system reports the Scalyr Agent Service is not running')

            return state in (win32service.SERVICE_RUNNING, win32service.SERVICE_START_PENDING)

        finally:
            if hs is not None:
                win32service.CloseServiceHandle(hs)
            if hscm is not None:
                win32service.CloseServiceHandle(hscm)

    def start_agent_service(self, agent_run_method, quiet, fork=True):
        """Start the agent service using the platform-specific method.

        This method must return once the agent service has been started.

        @param agent_run_method: The method to invoke to actually run the agent service.  This method takes one
            argument, the reference to this controller.  Note, if your platform implementation cannot use this
            function pointer (because the service is running in a separate address space and cannot be passed this
            pointer), then instead of invoking this method, you may invoke ScalyrAgent.agent_run_method instead.
        @param quiet: True if only error messages should be printed to stdout, stderr.
        @param fork: True if the agent should run in a child process.  Note: When false, status information will not
            work under windows.

        @type agent_run_method: func(PlatformController)
        @type quiet: bool
        """
        # NOTE:  The config_main.py file relies on it being ok to pass in None for agent_run_method.
        # If this assumption changes, fix that in config_main.py.
        _set_config_path_registry_entry(self.__config_file_path)
        if fork:
            win32serviceutil.StartService(_SCALYR_AGENT_SERVICE_)
        else:
            if agent_run_method:
                agent_run_method(self)

        if not quiet:
            print 'The agent has started.'

    def stop_agent_service(self, quiet):
        """Stops the agent service using the platform-specific method.

        This method must return only after the agent service has terminated.

        @param quiet: True if only error messages should be printed to stdout, stderr.
        @type quiet: bool
        """
        try:
            if not quiet:
                print 'Sending control signal to stop agent service.'
            win32serviceutil.StopService(_SCALYR_AGENT_SERVICE_)
            if not quiet:
                print 'Agent service has stopped.'
        except win32api.error, e:
            if e[0] == winerror.ERROR_SERVICE_NOT_ACTIVE:
                raise AgentNotRunning('The operating system indicates the Scalyr Agent Service is not running.')
            elif e[0] == winerror.ERROR_SERVICE_DOES_NOT_EXIST:
                raise AgentNotRunning('The operating system indicates the Scalyr Agent Service is not installed.  '
                                      'This indicates a failed installation.  Try reinstalling the agent.')
            else:
                raise e

    def get_usage_info(self):
        """Returns CPU and memory usage information.

        It returns the results in a tuple, with the first element being the number of
        CPU seconds spent in user land, the second is the number of CPU seconds spent in system land,
        and the third is the current resident size of the process in bytes."""
        process_info = psutil.Process()

        cpu_usage = process_info.cpu_times()
        user_cpu = cpu_usage.user
        system_cpu = cpu_usage.system

        return user_cpu, system_cpu, process_info.memory_info().rss

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
        try:
            win32serviceutil.ControlService(_SCALYR_AGENT_SERVICE_, _SERVICE_CONTROL_DETAILED_REPORT_)
        except win32api.error, e:
            if e[0] == winerror.ERROR_SERVICE_NOT_ACTIVE:
                return errno.ESRCH
            elif e[0] == winerror.ERROR_SERVICE_DOES_NOT_EXIST:
                raise AgentNotRunning('The operating system indicates the Scalyr Agent Service is not installed.  '
                                      'This indicates a failed installation.  Try reinstalling the agent.')
            else:
                raise e

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

        options_parser.add_option("-n", "--no-warn-escalation", action="store_true", dest="no_escalation_warning",
                                  default=False,
                                  help="This will disable the warning message (and requirement to push enter) that is "
                                       "printed to standard out before the process attempts to use Administrator "
                                       "permissions.  This does not disable the dialog box that pops up since the OS"
                                       "requires that dialog box to be presented.")

    def consume_options(self, options):
        """Invoked by the main method to allow the platform to consume any command line options previously requested
        in the 'add_options' call.

        @param options: The object containing the options as returned by the OptionParser.
        """
        self.__no_change_user = options.no_change_user
        self.__no_escalation_warning = options.no_escalation_warning

        if options.redirect_pipe is not None:
            redirection = PipeRedirectorServer(options.redirect_pipe)
            redirection.start()
            atexit.register(redirection.stop)


class PipeRedirectorServer(RedirectorServer):
    """Implements a server that will listen on a pipe named for a client connection and then send all bytes written to
    its stdout/stderr to that client.

    This is used to pipe the output of an esclated process to the one that invoked it.  Due to the interfaces exposed
    to Python, the command that allows for you to run an escalated process does not allow you to directly capture
    its stdout/stderr.. so we pass in a special option to the spawned process that allows us to transfer the
    stdout/stderr over the named pipe.
    """
    def __init__(self, pipe_name):
        self.__full_pipe_name = r'\\.\pipe\%s' % pipe_name
        RedirectorServer.__init__(self, PipeRedirectorServer.ServerChannel(self.__full_pipe_name))

    class ServerChannel(RedirectorServer.ServerChannel):
        """Provides the channel implementation for receiving client connections over a named pipe.
        """
        def __init__(self, name):
            self.__full_pipe_name = name
            self.__pipe_handle = None

        def accept_client(self, timeout=None):
            """Blocks until a client connects to the server.

            One the client has connected, then the `write` method can be used to write to it.

            @param timeout: The maximum number of seconds to wait for the client to connect before raising an
                `RedirectorError` exception.
            @type timeout: float|None

            @return:  True if a client has been connected, otherwise False.
            @rtype: bool
            """
            scaled_timeout = None
            if timeout is not None:
                scaled_timeout = int(timeout * 1000)
            self.__pipe_handle = win32pipe.CreateNamedPipe(self.__full_pipe_name, win32pipe.PIPE_ACCESS_OUTBOUND,
                                                           win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT,
                                                           1, 65536, 65536, scaled_timeout, None)

            return win32pipe.ConnectNamedPipe(self.__pipe_handle, None) == 0

        def write(self, content):
            """Writes the bytes to the connected client.

            @param content: The bytes
            @type content: str
            """
            win32file.WriteFile(self.__pipe_handle, content)

        def close(self):
            """Closes the channel to the client.
            """
            try:
                win32file.WriteFile(self.__pipe_handle, struct.pack('I', 0))
                win32file.FlushFileBuffers(self.__pipe_handle)
            finally:
                win32pipe.DisconnectNamedPipe(self.__pipe_handle)
                self.__pipe_handle = None


class PipeRedirectorClient(RedirectorClient):
    """Implements the client-side of the redirection service.

    This class creates a thread that will connect to a `PipeRedirectorServer` and print all of the sent back
    bytes to stdout or stderr.
    """
    def __init__(self, pipe_name=None):
        """Constructs a new client.

        @param pipe_name: The file portion of the named pipe.  If None is provided, then this instance will generate
            a random one that can be accessed through the `pipe_name` property.  This should be given to the server
            so it knows which pipe name to use.
        @type pipe_name: str
        """
        if pipe_name is None:
            pipe_name = 'scalyr_agent_redir_%d' % random.randint(0, 4096)
        self.__pipe_name = pipe_name
        self.__full_pipe_name = r'\\.\pipe\%s' % pipe_name
        RedirectorClient.__init__(self, PipeRedirectorClient.ClientChannel(self.__full_pipe_name))

    @property
    def pipe_name(self):
        return self.__pipe_name

    class ClientChannel(object):
        """Implements the client channel that connects to a named pipe and can receive data from it.
        """
        def __init__(self, full_pipe_name):
            self.__full_pipe_name = full_pipe_name
            self.__pipe_handle = None

        def connect(self):
            """Attempts to connect to the server, but does not block.

            @return: True if the channel is now connected.
            @rtype: bool
            """
            try:
                if win32pipe.WaitNamedPipe(self.__full_pipe_name, 10) != 0:
                    self.__pipe_handle = win32file.CreateFile(self.__full_pipe_name, win32file.GENERIC_READ, 0, None,
                                                              win32file.OPEN_EXISTING, 0, None)
                    return True
                else:
                    return False
            except pywintypes.error, e:
                if e[0] == winerror.ERROR_FILE_NOT_FOUND:
                    return False
                else:
                    raise e

        def peek(self):
            """Returns the number of bytes available for reading without blocking.

            @return A two values, the first the number of bytes, and the second, an error code.  An error code
            of zero indicates there was no error.

            @rtype (int, int)
            """
            result = win32pipe.PeekNamedPipe(self.__pipe_handle, 1024)
            if result:
                return result[1], 0
            else:
                return 0, 1

        def read(self, num_bytes_to_read):
            """Reads the specified number of bytes from the server and returns them.  This will block until the
            bytes are read.

            @param num_bytes_to_read: The number of bytes to read
            @type num_bytes_to_read: int
            @return: The bytes
            @rtype: str
            """
            (result, data) = win32file.ReadFile(self.__pipe_handle, num_bytes_to_read)
            if result == 0:
                return data
            else:
                raise RedirectorError('Saw result code of %d with data len=%d' % (result, len(data)))

        def close(self):
            """Closes the channel to the server.
            """
            if self.__pipe_handle is not None:
                win32file.CloseHandle(self.__pipe_handle)
                self.__pipe_handle = None

if __name__ == "__main__":
    sys.exit(win32serviceutil.HandleCommandLine(ScalyrAgentService))
