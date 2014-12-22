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


import os

from __scalyr__ import get_install_root

# The constants for install_type used below in the initializer for a
# platform instance.
PACKAGE_INSTALL = 1    # Indicates source code was installed via a package manager such as RPM or Windows executable.
TARBALL_INSTALL = 2    # Indicates source code was installed via a tarball created by the build_package.py script.
DEV_INSTALL = 3        # Indicates source code is running out of the original source tree, usually during dev testing.


class PlatformController:
    def __init__(self, install_type):
        """Initializes a platform instance.

        @param install_type: One of the constants describing the install type, such as PACKAGE_INSTALL, TARBALL_INSTALL,
            or DEV_INSTALL.
        @type install_type: int
        """
        self._install_type = install_type

    # A list of PlatformController classes that have been registered for use.
    __platform_classes__ = []

    @staticmethod
    def register_platform(platform_class):
        """Register a new platform class that could be instantiated during the 'new_platform' method.

        The class must derive from PlatformController.

        @param platform_class:  The derived PlatformController class
        @type platform_class: class
        """
        PlatformController.__platform_classes__.append(platform_class)

    @staticmethod
    def new_platform():
        """Returns an instance of the first previously registered platform classes that can handle the server this
        process is running on.

        The platform class used is the first one that returns True when its 'can_handle_current_platform' method
        is invoked.  They are checked in order of registration.

        @return: The PlatformController instance to use
        @rtype: PlatformController
        """
        # Determine which type of install this is.  We do this based on
        # whether or not certain files exist in the root of the source tree.
        install_root = get_install_root()
        if os.path.exists(os.path.join(install_root, 'packageless')):
            install_type = TARBALL_INSTALL
        elif os.path.exists(os.path.join(install_root, 'run_tests.py')):
            install_type = DEV_INSTALL
        else:
            install_type = PACKAGE_INSTALL

        for platform_class in PlatformController.__platform_classes__:
            result = platform_class(install_type)
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

    def consume_config(self, config):
        """Invoked after 'consume_options' is called to set the Configuration object to be used.

        This will be invoked before the scalyr-agent-2 command performs any real work and while stdout and stderr
        are still be displayed to the screen.

        @param config: The configuration object to use.  It will be None if the configuration could not be parsed.
        @type config: configuration.Configuration
        """
        pass

    @property
    def default_paths(self):
        """Returns the default paths to use for various configuration options for this platform.

        @return: The default paths
        @rtype: DefaultPaths
        """
        return None

    @property
    def default_monitors(self):
        """Returns the default monitors to use for this platform.

        This is guaranteed to be invoked after consume_config is called to allow implementations to make what they
        return be dependent on configuration options.

        This method should return a list of dicts containing monitor configuration options just as you would specify
        them in the configuration file.  The list may be empty.

        @return: The default monitors
        @rtype: list<dict>
        """
        return []

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
        pass

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
