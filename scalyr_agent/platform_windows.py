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

__author__ = 'guy.hoozdis@gmail.com'

import sys

if sys.platform != 'win32':
    raise Exception('Attempting to load platform_windows module on a non-Windows machine')

# TODO:
#  * Control flow (agent_run_method returns => stop service)
import servicemanager
import win32serviceutil
import win32service
import win32event
import win32api

import psutil

# TODO(windows): Get rid of this logging method, or name it to something better.
def log(msg):
    servicemanager.LogInfoMsg(msg)

from scalyr_agent.json_lib import JsonObject

# TODO(windows): Remove this once we verify that adding the service during dev stag works correclty
try:
    from scalyr_agent.platform_controller import PlatformController, DefaultPaths, AgentAlreadyRunning
except:
    etype, emsg, estack = sys.exc_info()
    log("%s - %s" % (etype, emsg.message))



# TODO(windows): Remove including the monitors directly here.
from scalyr_agent.builtin_monitors import windows_process_metrics, windows_system_metrics, test_monitor






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


class ScalyrAgentService(win32serviceutil.ServiceFramework):
    # TODO(windows): Do these really need to be separate vars.  If so, then document them.
    _svc_name_ = "ScalyrAgentService"
    _svc_display_name_ = "Scalyr Agent Service"
    _svc_description_ = "Hosts Scalyr metric collectors"

    # Custom/user defined control messages
    SERVICE_CONTROL_DETAILED_REPORT = win32service.SERVICE_USER_DEFINED_CONTROL - 1 


    def __init__(self, *args):
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
        from scalyr_agent.agent_main import ScalyrAgent, create_commandline_parser

        self.controller = PlatformController.new_platform()
        parser = create_commandline_parser()
        self.controller.add_options(parser)
        options, args = parser.parse_args(['start'])
        self.controller.consume_options(options)

        self.log("Calling agent_run_method()")
        agent = ScalyrAgent(self.controller)
        agent.agent_run_method(self.controller, options.config_filename)
        self.log("Exiting agent_run_method()")

    def SvcOther(self, control):
        self.log('SvcOther (control=%d)' % control)
        if ScalyrAgentService.SERVICE_CONTROL_DETAILED_REPORT == control:
            self.controller.invoke_status_handler()
        else:
            win32serviceutil.ServiceFramework.SvcOther(self, control)


class WindowsPlatformController(PlatformController):
    """A controller instance for Microsoft's Windows platforms
    """

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
        # TODO: These are not ideal paths, just something to get us started.
        from os import path, environ
        #root = environ.get('ScalyrRoot', path.abspath(path.dirname(__file__)))
        pf = environ.get('ProgramFiles(x86)')
        root = path.join(pf, 'Scalyr')
        logdir = path.join(root, 'log')
        libdir = path.join(root, 'lib')
        config = path.join(root, 'agent.json')

        #return DefaultPaths(
        #        r'\Temp\scalyr\log',
        #        r'\Temp\scalyr\agent.json',
        #        r'\Temp\scalyr\lib')
        return DefaultPaths(logdir, config, libdir)

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
        # TODO(windows): Probably need to throw an error here since we do not support changing the user at this
        # time on windows.
        # TODO: Selects user based on owner of the config file.  Do we want to do the same thing on this platform?
        pass

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
        win32serviceutil.ControlService(ScalyrAgentService._svc_name_, ScalyrAgentService.SERVICE_CONTROL_DETAILED_REPORT)


if __name__ == "__main__":
    try:
        rc = win32serviceutil.HandleCommandLine(ScalyrAgentService)
    except:
        log('ERROR: got an exeption in main')
    else:
        log('SUCCESS: no exception in main')
    sys.exit(rc)
