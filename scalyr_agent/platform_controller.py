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


import sys

from __scalyr__ import INSTALL_TYPE


class PlatformController:
    def __init__(self):
        """Initializes a platform instance.
        """
        self._install_type = INSTALL_TYPE

    # A list of PlatformController classes that have been registered for use.
    __platform_classes__ = []
    __platforms_registered__ = False

    @staticmethod
    def __register_supported_platforms():
        """Adds all available platforms to the '__platforms_registered__' array.
         a new platform class that could be instantiated during the 'new_platform' method.
        """
        if sys.platform == 'win32':
            from scalyr_agent.platform_windows import WindowsPlatformController
            PlatformController.__platform_classes__.append(WindowsPlatformController)
        else:
            from scalyr_agent.platform_linux import LinuxPlatformController
            PlatformController.__platform_classes__.append(LinuxPlatformController)

            from scalyr_agent.platform_posix import PosixPlatformController
            PlatformController.__platform_classes__.append(PosixPlatformController)

        PlatformController.__platforms_registered__ = True

    @staticmethod
    def new_platform():
        """Returns an instance of the first previously registered platform classes that can handle the server this
        process is running on.

        The platform class used is the first one that returns True when its 'can_handle_current_platform' method
        is invoked.  They are checked in order of registration.

        @return: The PlatformController instance to use
        @rtype: PlatformController
        """
        # If we haven't initialized the platforms array, then do so.
        if not PlatformController.__platforms_registered__:
            PlatformController.__register_supported_platforms()

        for platform_class in PlatformController.__platform_classes__:
            result = platform_class()
            if result.can_handle_current_platform():
                return result
        return None

    @property
    def install_type(self):
        """Returns the install type for the instance of the agent currently running.

        @return: The install type, one of PACKAGE_INSTALL, TARBALL_INSTALL, DEV_INSTALL
        @rtype: int
        """
        return self._install_type

    def can_handle_current_platform(self):
        """Returns true if this platform object can handle the server this process is running on.

        Derived classes must override this method.

        @return:  True if this platform instance can handle the current server.
        @rtype: bool
        """
        return False

    def add_options(self, options_parser):
        """Invoked by the main method to allow the platform to add in platform-specific options to the
        OptionParser used to parse the commandline options.

        This platform instance may add any option to the OptionParser that they wish.  They will be
        able to retrieve the value, if any, when 'consume_options' is invoked.

        @param options_parser:
        @type options_parser: optparse.OptionParser
        """
        pass

    def consume_options(self, options):
        """Invoked by the main method to allow the platform to consume any command line options previously requested
        in the 'add_options' call.

        This will always be invoked before the agent script perform any real actions, so the platform may use this
        to perform other actions such as execute the agent_main method if necessary.

        @param options: The object containing the options.
        @type options: object
        """
        pass

    def consume_config(self, config, path_to_config):
        """Invoked after 'consume_options' is called to set the Configuration object to be used.

        This will be invoked before the scalyr-agent-2 command performs any real work and while stdout and stderr
        are still be displayed to the screen.

        @param config: The configuration object to use.  It will be None if the configuration could not be parsed.
        @param path_to_config: The full path to file that was read to create the config object.

        @type config: configuration.Configuration
        @type path_to_config: str
        """
        pass

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
        return

    @property
    def default_paths(self):
        """Returns the default paths to use for various configuration options for this platform.

        @return: The default paths
        @rtype: DefaultPaths
        """
        return None

    # noinspection PyUnusedLocal
    def get_default_monitors(self, config):
        """Returns the default monitors to use for this platform.

        This method should return a list of dicts containing monitor configuration options just as you would specify
        them in the configuration file.  The list may be empty.

        @param config The configuration object to use.
        @type config configuration.Configuration

        @return: The default monitors
        @rtype: list<dict>
        """
        return []

    def get_file_owner(self, file_path):
        """Returns the user name of the owner of the specified file.

        @param file_path: The path of the file.
        @type file_path: str

        @return: The user name of the owner.
        @rtype: str
        """
        pass

    def set_file_owner(self, file_path, owner):
        """Sets the owner of the specified file.

        @param file_path: The path of the file.
        @param owner: The new owner of the file.  This should be a string returned by either `get_file_ower` or
            `get_current_user`.
        @type file_path: str
        @type owner: str
        """
        pass

    def get_current_user(self):
        """Returns the effective user name running this process.

        The effective user may not be the same as the initiator of the process if the process has escalated its
        privileges.

        @return: The name of the effective user running this process.
        @rtype: str
        """
        pass

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
        pass

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

    def is_agent(self):
        """Checks to see if this current process is the official agent service.

        A result of zero, indicates this process is the official agent service.  All other values are platform
        specific codes indicating how it decided this process was not the agent service.

        @return: Zero if it is the current process, otherwise a platform specific code.
        @rtype: int
        """
        return 0

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
        pass

    def stop_agent_service(self, quiet):
        """Stops the agent service using the platform-specific method.

        This method must return only after the agent service has terminated.

        @param quiet: True if only error messages should be printed to stdout, stderr.
        @type quiet: bool
        """
        pass

    def request_agent_status(self):
        """Invoked by a process that is not the agent to request the current agent dump the current detail
        status to the status file.

        This is used to implement the 'scalyr-agent-2 status -v' feature.

        @return: If there is an error, an errno that describes the error.  errno.EPERM indicates the current does not
            have permission to request the status.  errno.ESRCH indicates the agent is not running.
        """
        pass

    def register_for_termination(self, handler):
        """Register a method to be invoked if the agent service is requested to terminated.

        This should only be invoked by the agent service once it has begun to run.

        @param handler: The method to invoke when termination is requested.
        @type handler:  func
        """
        pass

    def register_for_status_requests(self, handler):
        """Register a method to be invoked if this process is requested to report its status.

        This is used to implement the 'scalyr-agent-2 status -v' feature.

        This should only be invoked by the agent service once it has begun to run.

        @param handler:  The method to invoke when status is requested.
        @type handler: func
        """
        pass

    def get_usage_info(self):
        """Returns CPU and memory usage information.

        It returns the results in a tuple, with the first element being the number of
        CPU seconds spent in user land, the second is the number of CPU seconds spent in system land,
        and the third is the current resident size of the process in bytes."""
        pass


class DefaultPaths(object):
    """Holds the values for the default paths for several key files and directories.

    The default values are platform specific so must be created by a PlatformController instance.
    """
    def __init__(self, agent_log_path, config_file_path, agent_data_path):
        self.agent_log_path = agent_log_path
        self.config_file_path = config_file_path
        self.agent_data_path = agent_data_path


class AgentAlreadyRunning(Exception):
    """Raised to signal the agent is already running.
    """
    pass


class AgentNotRunning(Exception):
    """Raised to signal the agent is not running.
    """
    pass


class CannotExecuteAsUser(Exception):
    """Raised to signal that the platform cannot change to the requested user.

    This usually means the current user is not privileged (root)."""
    def __init__(self, error_message):
        self.error_message = error_message


class ChangeUserNotSupported(Exception):
    """Raised to signal that this platform has not implemented the operation of changing its executing user.
    """
    pass
