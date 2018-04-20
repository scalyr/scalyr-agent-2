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
# The main function for the scalyr-agent-2-config command which can be used to update
# the configuration file.  Currently, this only works on configuration files that have
# not been previously modified by the user.
#
# author: Steven Czerwinski <czerwin@scalyr.com>

__author__ = 'czerwin@scalyr.com'

import cStringIO
import glob
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import traceback

from distutils import spawn
from optparse import OptionParser

# TODO: The following two imports have been modified to facilitate Windows platforms
if 'win32' != sys.platform:
    from pwd import getpwnam

import urllib

from __scalyr__ import scalyr_init, get_install_root, TARBALL_INSTALL, MSI_INSTALL, SCALYR_VERSION
scalyr_init()

from scalyr_agent.scalyr_logging import set_log_destination
set_log_destination(use_stdout=True)

from scalyr_agent.scalyr_client import ScalyrClientSession
from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import PlatformController

import scalyr_agent.json_lib as json_lib


def set_api_key(config, config_file_path, new_api_key):
    """Replaces the current api key in the file at 'config_file_path' with the value of 'new_api_key'.

    @param config: The Configuration object created by reading config_file_path.
    @param config_file_path: The full path to the configuration file. This file will be overwritten.
    @param new_api_key: The new value for the api key to write into the file.
    """
    # We essentially search through the current configuration file, looking for the current key's value
    # and rewrite it to be the new_api_key.
    current_key = config.api_key

    tmp_file = None
    original_file = None

    try:
        try:
            # Create a temporary file that we will write the new file into.  We will just rename it when we are done
            # to the original file name.
            tmp_file_path = '%s.tmp' % config_file_path
            tmp_file = open(tmp_file_path, 'w')

            # Open up the current file for reading.
            original_file = open(config_file_path)
            found = 0

            for s in original_file:
                # For a sanity check, make sure we only see the current key once in the file.  That guarantees that
                # we are replacing the correct thing.
                found += s.count(current_key)
                if found > 1:
                    print >>sys.stderr, 'The existing API key was found in more than one place.  Config file has been'
                    print >>sys.stderr, 'modified already.  Cannot safely update modified config file so failing.'
                    sys.exit(1)
                s = s.replace(current_key, new_api_key)
                print >>tmp_file, s,

            if found != 1:
                print >>sys.stderr, 'The existing API key could not be found in file, failing'
                sys.exit(1)

            # For Win32, we must make sure the files are closed before rename.
            tmp_file.close()
            tmp_file = None
            original_file.close()
            original_file = None

            if 'win32' == sys.platform:
                os.unlink(config_file_path)

            # Determine how to make the file have the same permissions as the original config file.  For now, it
            # does not matter since if this command is only run as part of the install process, the file should
            # be owned by root already.
            os.rename(tmp_file_path, config_file_path)
        except IOError, error:
                if error.errno == 13:
                    print >>sys.stderr, 'You do not have permission to write to the file and directory required '
                    print >>sys.stderr, 'to update the API key.  Ensure you can write to the file at path'
                    print >>sys.stderr, '\'%s\' and create files in its parent directory.' % config_file_path
                else:
                    print >>sys.stderr, 'Error attempting to update the key: %s' % str(error)
                    print >>sys.stderr, traceback.format_exc()
                sys.exit(1)
        except Exception, err:
            print >>sys.stderr, 'Error attempting to update the key: %s' % str(err)
            print >> sys.stderr, traceback.format_exc()
            sys.exit(1)
    finally:
        if tmp_file is not None:
            tmp_file.close()
        if original_file is not None:
            original_file.close()


def set_scalyr_server(config, new_scalyr_server):
    """Creates a new configuration file in the ``agent.d`` directory to set the `scalyr_server` field to
    the specified value.

    @param config: The Configuration object.
    @type config: Configuration
    @param new_scalyr_server: The new value
    @type new_scalyr_server: str
    """
    write_config_fragment(config, 'scalyr_server.json', 'scalyr_server field',
                          {"scalyr_server": new_scalyr_server})


def set_server_host(config, new_server_host):
    """Creates a new configuration file in the ``agent.d`` directory to set the ``serverHost`` server attribute
    to the specified value.

    @param config: The Configuration object.
    @param new_server_host: The value for the ``serverHost`` server attribute.
    """
    write_config_fragment(config, 'server_host.json', 'server host attribute',
                          {'server_attributes': {'serverHost': new_server_host}})


def write_config_fragment(config, file_name, field_description, config_json):
    """Writes a file called `file_name` to the ``agent.d`` directory with the specified configuration.

    @param config: The configuration for the agent, used to determine the location of the ``agent.d`` directory.
    @param file_name: The name of the file, not the full path.
    @param field_description: The description of what field is being set, used to emit errors and write comments in file.
    @param config_json: The configuration to write.
    @type config: Configuration
    @type file_name: str
    @type field_description: str
    @type config_json: dict
    """
    host_path = os.path.join(config.config_directory, file_name)
    tmp_host_path = '%s.tmp' % host_path

    try:
        try:
            if os.path.isfile(tmp_host_path):
                os.unlink(tmp_host_path)

            config_content = json_lib.serialize(config_json)

            tmp_file = open(tmp_host_path, 'w')
            print >>tmp_file, '// Sets the %s.' % field_description
            print >>tmp_file, config_content
            tmp_file.close()

            if 'win32' == sys.platform and os.path.isfile(host_path):
                os.unlink(host_path)

            os.rename(tmp_host_path, host_path)
        except IOError, error:
                if error.errno == 13:
                    print >>sys.stderr, 'You do not have permission to write to the file and directory required '
                    print >>sys.stderr, 'to set the %s.  Ensure you can write to the file at path' % field_description
                    print >>sys.stderr, '\'%s\' and create files in its parent directory.' % host_path
                else:
                    print >>sys.stderr, 'Error attempting to update the %s: %s' % (field_description, str(error))
                    print >>sys.stderr, traceback.format_exc()
                sys.exit(1)
        except Exception, err:
            print >>sys.stderr, 'Error attempting to update the %s: %s' % (field_description, str(err))
            print >> sys.stderr, traceback.format_exc()
            sys.exit(1)
    finally:
        if os.path.isfile(tmp_host_path):
            os.unlink(tmp_host_path)


def update_user_id(file_path, new_uid):
    """Change the owner of file_path to the new_uid.

    @param file_path: The full path to the file.
    @param new_uid: The id of the user to set as owner.
    """
    try:
        group_id = os.stat(file_path).st_gid
        os.chown(file_path, new_uid, group_id)
    except Exception, err:
        print >>sys.stderr, 'Error attempting to update permission on file "%s": %s' % (file_path, str(err))
        print >> sys.stderr, traceback.format_exc()
        sys.exit(1)


def update_user_id_recursively(path, new_uid):
    """Change the owner of the directory named 'path' to the new_uid and all of its files, recursively.

    @param path: The full path to the directory.
    @param new_uid: The id of the user to set as owner.
    """
    try:
        update_user_id(path, new_uid)
        for f in os.listdir(path):
            full_path = os.path.join(path, f)
            if os.path.isfile(full_path):
                update_user_id(full_path, new_uid)
            elif os.path.isdir(full_path):
                update_user_id_recursively(full_path, new_uid)
    except Exception, err:
        print >>sys.stderr, 'Error attempting to update permissions on files in dir "%s": %s' % (path, str(err))
        print >> sys.stderr, traceback.format_exc()
        sys.exit(1)


def set_executing_user(config, config_file_path, new_executing_user):
    """Update all the configuration files so that the agent can be run as new_executing_user.

    @param config: The Configuration object created by parsing config_file_path.
    @param config_file_path: The full path of the configuration file.
    @param new_executing_user: The new user (str) that the agent should be run as.
    """
    try:
        uid = getpwnam(new_executing_user).pw_uid
    except KeyError:
        print >>sys.stderr, 'User "%s" does not exist.  Failing.' % new_executing_user
        sys.exit(1)

    # The agent looks to the owner of the configuration file to determine what user to run as.  So, change that
    # first.
    update_user_id(config_file_path, uid)
    # Also change the config partial directory so the new user can edit them if necessary.
    update_user_id_recursively(config.config_directory, uid)

    # We have to update all files in the data and log directories to ensure the new user can read them all.
    update_user_id_recursively(config.agent_data_path, uid)
    update_user_id_recursively(config.agent_log_path, uid)


def upgrade_tarball_install(config, new_tarball, preserve_old_install):
    """Performs an upgrade for an existing Scalyr Agent 2 that was previously installed using the tarball method.

    @param config: The configuration for this agent.
    @param new_tarball: The path to file containing the new tarball to install.
    @param preserve_old_install: If True, will move the old install directory to a new location rather than deleting
        it.

    @return: The exit status code.
    """
    # Create a temporary directory hold the new install as we untar it and copy files into it.
    tmp_install_dir = tempfile.mkdtemp()

    # Some variables that capture some important state that we may need to unwind if we execute
    # out the installation along the way.
    #
    # If not None, then the directory we are currently holding the old installation directory in.
    preserve_dir = None
    # True if the agent was running when the install started.
    was_running = False
    # True if the agent was successfully restarted.
    was_restarted = False

    try:
        try:
            platform_controller = PlatformController.new_platform()
            my_default_paths = platform_controller.default_paths

            # Ensure that this is a tarball install
            if platform_controller.install_type != TARBALL_INSTALL:
                raise UpgradeFailure('The current agent was not installed using a tarball, so you may not use the '
                                     'upgrade tarball command.')

            # Ensure that the user has not changed the defaults for the config, data, and log directory.
            if my_default_paths.config_file_path != config.file_path:
                raise UpgradeFailure('The agent is not using the default configuration file so you may not use the '
                                     'upgrade tarball command.')
            if my_default_paths.agent_data_path != config.agent_data_path:
                raise UpgradeFailure('The agent is not using the default data directory so you may not use the upgrade '
                                     'tarball command.')
            if my_default_paths.agent_log_path != config.agent_log_path:
                raise UpgradeFailure('The agent is not using the default log directory so you may not use the upgrade '
                                     'tarball command.')

            # We rely on the current installation being included in the PATH variable.
            if spawn.find_executable('scalyr-agent-2-config') is None:
                raise UpgradeFailure('Could not locate the scalyr-agent-2-config command from the current '
                                     'installation. Please ensure that the agent\'s bin directory is in the system\'s '
                                     'PATH variable.')

            if not os.path.isfile(new_tarball):
                raise UpgradeFailure('The tarball file %s does not exist.' % new_tarball)

            file_name = os.path.basename(new_tarball)
            if re.match('^scalyr-agent-2\..*\.tar\.gz$', file_name) is None:
                raise UpgradeFailure('The supplied tarball file name does not match the expected format.')
            tarball_directory = file_name[0:-7]

            # We will be installing in the same directory where scalyr-agent-2 is currently installed.
            install_directory = os.path.dirname(get_install_root())

            if not os.path.isdir(os.path.join(install_directory, 'scalyr-agent-2')):
                raise UpgradeFailure('Could not determine the install directory.  Either the main directory is no '
                                     'longer called scalyr-agent-2, or the directory structure has changed.')

            # Compute the full paths to the scalyr-agent-2 directories for both the new install and old install.
            tmp_new_install_location = os.path.join(tmp_install_dir, tarball_directory)
            old_install_location = os.path.join(install_directory, 'scalyr-agent-2')

            # Untar the new package into the temp location.
            tar = tarfile.open(new_tarball, 'r:gz')
            for member in tar.getmembers():
                tar.extract(member, path=tmp_install_dir)

            # Check to see if the agent is running.  If so, stop it.
            was_running = run_command('scalyr-agent-2 stop', grep_for='Agent has stopped',
                                      command_name='scalyr-agent-2 stop')[0] == 0

            # Copy the config, data, and log directories.
            for dir_name in ['config', 'log', 'data']:
                copy_dir_to_new_agent(old_install_location, tmp_new_install_location, dir_name)

            # Allow the new agent code to perform any actions it deems necessary.  We do the special commandline
            # here where to pass in both directories to the --upgrade-tarball-command
            result = subprocess.call([os.path.join(tmp_new_install_location, 'bin', 'scalyr-agent-2-config'),
                                      '--upgrade-tarball', '%s%s%s' % (old_install_location, os.pathsep,
                                                                       tmp_new_install_location)])
            if result != 0:
                raise UpgradeFailure('New package failed to finish the upgrade process.')

            # Move the old install directory to a temporary location, so we can undo the next move if we need to.
            preserve_dir = tempfile.mkdtemp()
            shutil.move(old_install_location, preserve_dir)

            # Move the new install into place.
            success = False
            try:
                shutil.move(tmp_new_install_location, old_install_location)
                success = True
            finally:
                if not success:
                    # Move the old install back in place just to be safe.
                    shutil.move(os.path.join(preserve_dir, 'scalyr-agent-2'), old_install_location)
                if success and not preserve_old_install:
                    shutil.rmtree(preserve_dir)
                    preserve_dir = None

            print 'New agent installed.'

            # Start the agent if it was previously running.
            if was_running:
                if run_command('scalyr-agent-2 start', exit_on_fail=False, command_name='scalyr-agent-2 start')[0] == 0:
                    print 'Agent has successfully restarted.'
                    print '  You may execute the following command for status details:  scalyr-agent-2 status -v'
                    was_restarted = True
                else:
                    raise UpgradeFailure('Could not start the agent.  Execute the following command for more details: '
                                         'scalyr-agent-2 start')
            else:
                print 'Execute the following command to start the agent:  scalyr-agent-2 start'

            return 0

        except UpgradeFailure, error:
            print >>sys.stderr
            print >>sys.stderr, 'The upgrade failed due to the following reason: %s' % error.message
            return 1

    finally:
        # Delete the temporary directory.
        shutil.rmtree(tmp_install_dir)

        # Warn if we should have restarted the agent but did not.
        if was_running and not was_restarted:
            print ''
            print ('WARNING, due to failure, the agent may no longer be running.  Restart it with: scalyr-agent-2 '
                   'start')

        # If there is still a preserve_directory, there must be a reason for it, so tell the user where it is.
        if preserve_dir is not None:
            print ''
            print 'The previous agent installation was left in \'%s\'' % preserve_dir
            print 'You should be sure to delete this directory once you no longer need it.'


# noinspection PyUnusedLocal
def finish_upgrade_tarball_install(old_install_dir_path, new_install_dir_path):
    """Performs any actions the new agent package needs to perform before the tarball upgrade process will be
    considered a success.

    In the current system, when performing a tarball upgrade, the scripts from the old package are used to
    drive the upgrade process.  However, what happens if the new agent package wants to perform some task during
    the upgrade process that wasn't foreseen in the old package?  To solve this problem we have the old scripts
    execute the new script's scalyr-agent-2-config script with a specially formatted commandline to give it the
    change to perform whatever actions it desires.

    Any output emitted while be included stdout, stderr of the original upgrade command.  Additionally, if this
    method returns a non-zero status code, the overall upgrade will fail.

    @param old_install_dir_path: The full path to a directory containing the old agent installation.  Note, this
        may not be in the original directory where it resided, but a temporary directory to which the agent was
        moved during the upgrade.
    @param new_install_dir_path:  The full path to a directory containing the new agent installation.  Note, this
        may not be in the directory where it will finally rest when installed, but a temporary directory in which
        the agent was created during the upgrade.

    @type new_install_dir_path: str
    @type old_install_dir_path: str

    @return: A zero exit status if success, otherwise non-zero.  A non-zero result will cause the overall upgrade to
        fail
    @rtype: int
    """
    # For now, we do not do anything.
    return 0


def upgrade_windows_install(config, release_track="stable", preserve_msi=False, use_ui=True):
    """Performs an upgrade for an existing Scalyr Agent 2 that was previously installed using a Windows MSI install
    file.

    This will contact the Scalyr servers to see what the most up-to-date version of the agent is and, if necessary,
    download an MSI file.

    @param config: The configuration for this agent.
    @param release_track:  The release track to use when checking which version is the latest.
    @param preserve_msi:  Whether or not to delete the MSI file once the upgrade is finished.  Note, this
        argument is essentially ignored for now and we always leave the file because we cannot delete it with
        the current way we exec the msiexec process.
    @param use_ui:  Whether or not the msiexec upgrade command should be run with the UI.

    @rtype config: Configuration
    @rtype release_track: str
    @rtype preserve_msi: bool
    @rtype use_ui: bool

    @return: The exit status code.
    """
    # The URL path of the agent to upgrade to.
    url_path = None

    try:
        platform_controller = PlatformController.new_platform()
        my_default_paths = platform_controller.default_paths

        # Ensure agent was installed via MSI
        if MSI_INSTALL != platform_controller.install_type:
            raise UpgradeFailure('The current agent was not installed via MSI, so you may not use the upgrade windows '
                                 'command.')

        # Ensure that the user has not changed the defaults for the config, data, and log directory.
        if my_default_paths.config_file_path != config.file_path:
            raise UpgradeFailure('The agent is not using the default configuration file so you may not use the '
                                 'upgrade windows command.')
        if my_default_paths.agent_data_path != config.agent_data_path:
            raise UpgradeFailure('The agent is not using the default data directory so you may not use the upgrade '
                                 'windows command.')
        if my_default_paths.agent_log_path != config.agent_log_path:
            raise UpgradeFailure('The agent is not using the default log directory so you may not use the upgrade '
                                 'windows command.')

        # Determine if a newer version is available
        client = ScalyrClientSession(config.scalyr_server, config.api_key, SCALYR_VERSION, quiet=True,
                                     ca_file=config.ca_cert_path, proxies=config.network_proxies)

        status, size, response = client.perform_agent_version_check(release_track)

        if status.lower() != 'success':
            raise UpgradeFailure('Failed to contact the Scalyr servers to check for latest update.  Error code '
                                 'was "%s"' % status)

        # TODO:  We shouldn't have to reparse response on JSON, but for now that, that's what the client library
        # does.
        data_payload = json_lib.parse(response)['data']

        if not data_payload['update_required']:
            print 'The latest version is already installed.'
            return 0

        print 'Attempting to upgrade agent from version %s to version %s.' % (SCALYR_VERSION,
                                                                              data_payload['current_version'])
        url_path = data_payload['urls']['win32']

        file_portion = url_path[url_path.rfind('/')+1:]
        download_location = os.path.join(tempfile.gettempdir(), file_portion)

        try:
            try:
                print 'Downloading agent from %s.' % url_path
                urllib.urlretrieve(url_path, download_location)

                if not os.path.isfile(download_location):
                    raise UpgradeFailure('Failed to download installation package')

                if use_ui:
                    print ('Executing upgrade.  Please follow the instructions in the subsequent dialog boxes to '
                           'complete the upgrade process.')
                else:
                    print ('Executing upgrade.  It will finish in the background.')

                # Because this file, config_main.py, is part of the currently installed Scalyr Agent package, we have
                # to finish our use of it before the upgrade can proceed.  So, we just fork off the msiexec process
                # in detached mode and terminate this program.  This means we cannot report any errors that happen
                # here, but I don't see a way around this for now.
                # noinspection PyUnresolvedReferences
                from win32process import DETACHED_PROCESS
                upgrade_command = ['msiexec.exe', '/i', "{}".format(download_location)]
                if not use_ui:
                    upgrade_command.append('/qn')
                subprocess.Popen(upgrade_command,
                                 shell=False, stdin=None, stdout=None, stderr=None, close_fds=True,
                                 creationflags=DETACHED_PROCESS)

                return 0
            except IOError, error:
                raise UpgradeFailure('Could not download the installer, returned error %s' % str(error))

        finally:
            # TODO:  Actually delete the temporary file.  We cannot right now since our execution finishes
            # before the msiexec process runs, but maybe we can do something like have a small shell script
            # that runs the upgrader and then deletes the file.  Something to consider post-alpha release.
            if preserve_msi:
                print 'Downloaded installer file has been left at %s' % download_location

    except UpgradeFailure, error:
        print >>sys.stderr
        print >>sys.stderr, 'The upgrade failed due to the following reason: %s' % error.message
        if url_path is not None:
            print >>sys.stderr, 'You may try downloading and running the installer file yourself.'
            print >>sys.stderr, 'The installer can be downloaded from %s' % url_path
        print >>sys.stderr, 'Please e-mail contact@scalyr.com for help resolving this issue.'
        return 1


# TODO:  This code is shared with build_package.py.  We should move this into a common
# utility location both commands can import it from.
def run_command(command_str, exit_on_fail=True, command_name=None, grep_for=None):
    """Executes the specified command string returning the exit status.

    @param command_str: The command to execute.
    @param exit_on_fail: If True, will exit this process with a non-zero status if the command fails.
    @param command_name: The name to use to identify the command in error output.
    @param grep_for: If not None, will return zero if and only if the provided string appears in the output of the
        command. This search is only performed if the command itself returned a zero status.

    @return: The exist status of the command.
    """
    # We have to use a temporary file to hold the output to stdout and stderr.
    output_file = tempfile.mktemp()
    output_fp = open(output_file, 'w')

    try:
        return_code = subprocess.call(command_str, stdin=None, stderr=output_fp, stdout=output_fp, shell=True)
        output_fp.flush()

        # Read the output back into a string.  We cannot use a cStringIO.StringIO buffer directly above with
        # subprocess.call because that method expects fileno support which StringIO doesn't support.
        output_buffer = cStringIO.StringIO()
        input_fp = open(output_file, 'r')
        for line in input_fp:
            output_buffer.write(line)
        input_fp.close()

        output_str = output_buffer.getvalue()
        output_buffer.close()

        if return_code != 0:
            if command_name is not None:
                print >>sys.stderr, 'Executing %s failed and returned a non-zero result of %d' % (command_name,
                                                                                                  return_code)
            else:
                print >>sys.stderr, ('Executing the following command failed and returned a non-zero result of %d' %
                                     return_code)
                print >>sys.stderr, '  Command: "%s"' % command_str

            print >>sys.stderr, 'The output was:'
            print >>sys.stderr, output_str

            if exit_on_fail:
                print >>sys.stderr, 'Exiting due to failure.'
                sys.exit(1)
        elif grep_for is not None:
            if output_str.find(grep_for) < 0:
                return_code = -1

        return return_code, output_str

    finally:
        # Be sure to close the temporary file and delete it.
        output_fp.close()
        os.unlink(output_file)


def copy_dir_to_new_agent(old_install_dir, new_install_dir, directory):
    """Copies the specified directory from the original agent to the new agent's directory.

    This method is just used for tarball upgrades.  It will also delete the directory that
    currently exists in the new installation directory.

    @param old_install_dir: The path to the old agent installation.
    @param new_install_dir: The path to the new agent installation.
    @param directory: The subdirectory of the old agent to copy. Must be relative to old_install_dir.
    """
    # First, delete the directory that currently exists at that location in the new agent install.
    new_agent_directory = os.path.join(new_install_dir, directory)
    old_agent_directory = os.path.join(old_install_dir, directory)

    shutil.rmtree(new_agent_directory)

    # We do a move to preserve the file uid's.  We copy it back to the original agent just so we leave a complete
    # tree.
    shutil.move(old_agent_directory, new_agent_directory)
    shutil.copytree(new_agent_directory, old_agent_directory)


class UpgradeFailure(Exception):
    """Raised when a failure occurs in the tarball upgrade process.
    """
    pass


def conditional_marker_path(config):
    """Constructs the path to the conditional restart marker file and returns it.

    @param config:
    @type config: Configuration

    @return: The pat to the conditional restart marker file.
    @rtype: str
    """
    return os.path.join(config.agent_data_path, 'cond_restart')


def mark_conditional_restart(platform_controller, config):
    """If the agent is currently running, creates the conditional restart marker file.

    If it is not running, makes sure that file is deleted if it currently exists.

    @param platform_controller: The controller.
    @param config: The configuration file.

    @type platform_controller: PlatformController
    @type config: Configuration

    @return True if the agent was running and a file was created.
    @rtype bool
    """
    path = conditional_marker_path(config)

    if os.path.isfile(path):
        os.unlink(path)

    if platform_controller.is_agent_running():
        fp = open(path, 'w')
        try:
            fp.write('yes')
            return True
        finally:
            fp.close()
    else:
        return False


def restart_if_conditional_marker_exists(platform_controller, config):
    """Starts the agent if the conditional restart marker file exists.

    This also deletes that marker file so that the next call to this function will not start the
    agent unless another marker file was created.

    @param platform_controller: The controller.  This must be the WindowsPlatformController.
    @param config: The configuration file.

    @type platform_controller: PlatformController
    @type config: Configuration

    @return: True if the agent was started.
    @rtype: bool
    """
    path = conditional_marker_path(config)

    if os.path.isfile(path):
        os.unlink(path)
        # We rely on the WindowsPlatformController start_agent_service not needing a run method passed in to it.
        platform_controller.start_agent_service(None, True)
        return True
    else:
        return False


def real_absolute_path(path):
    """Returns the specified path with both `os.path.abspath` and `os.path.realpath` applied to it.
    @param path: The path
    @type path: str
    @return: The full path
    @rtype: str
    """
    return os.path.realpath(os.path.abspath(path))


def relative_path(base_directory, path):
    """Return a version of a path relative to base_directory

    This is based on `os.path.relpath`.  However, that method is not included in Python 2.4, so replicating
    it here.
    """

    start_list = [x for x in base_directory.split(os.path.sep) if x]
    path_list = [x for x in path.split(os.path.sep) if x]

    # Work out how much of the filepath is shared by start and path.
    i = len(os.path.commonprefix([start_list, path_list]))

    rel_list = [os.path.pardir] * (len(start_list)-i) + path_list[i:]
    if not rel_list:
        return os.curdir
    return os.path.join(*rel_list)


def get_canonical_name(path):
    """Returns the most canonical form of the path possible.

    This is useful to see if two files (possibly using different symlinks and multiple uses of the parent
    directory operator) are in fact the same file.

    @param path: The path
    @type path: str
    @return: The canonical path for the file.
    @rtype: str
    """
    return os.path.normcase(os.path.normpath(real_absolute_path(path)))


def export_config(config_dest, config_file_path, configuration):
    """Creates a tarball containing the configuration files for the agent (the `agent.json` file and all
    `.json` files in the `agent.d` directory).

    @param config_dest: The destination path to write the tarball containing the config.  This maybe `-` if
        it should be written to stdout.
    @param config_file_path: The path to the configuration file (`agent.json`).
    @param configuration: The current configuration as read from the file.

    @type config_dest: str
    @type config_file_path: str
    @type configuration: Configuration
    """
    original_dir = os.getcwd()

    # Change working directory to base of agent configuration directory (usually /etc/scalyr-agent-2 on Linux).
    config_dir = os.path.dirname(config_file_path)
    os.chdir(config_dir)

    try:
        # Get the path to the configuration directory relative to this directory (usually `agent.d`).  Use the
        # raw value for this configuration to avoid it making the path absolute when we want the relative.
        fragment_dir = configuration.config_directory_raw

        # If it was absolute, try to make it relative.
        if os.path.isabs(fragment_dir):
            fragment_dir = relative_path(real_absolute_path(config_dir), real_absolute_path(fragment_dir))

        if config_dest != '-':
            out_tar = tarfile.open(config_dest, mode='w:gz')
        else:
            out_tar = tarfile.open(fileobj=sys.stdout, mode='w|gz')
        out_tar.add(os.path.basename(config_file_path))

        for x in glob.glob(os.path.join(fragment_dir, "*.json")):
            out_tar.add(x)

        out_tar.close()
    finally:
        os.chdir(original_dir)


def get_tarinfo(path):
    """Gets the `TarInfo` object for the file at the specified path.

    This contains useful information such as the owner and the group.

    @param path: The path.
    @type path: str
    @return: The info for that path
    @rtype: tarfile.TarInfo
    """
    # The `tarfile` library does not let us get this directly.  We need to actually open a tarfile for writing
    # and have it look at the file path.  So, we create a temporary file to write it to.
    fd, fn = tempfile.mkstemp()
    file_obj = os.fdopen(fd, 'wb')

    try:
        tmp_tar = tarfile.open(fn, fileobj=file_obj, mode='w:gz')
        result = tmp_tar.gettarinfo(path)
        tmp_tar.close()

        return result
    finally:
        file_obj.close()


def import_config(config_src, config_file_path, configuration):
    """Extracts the agent configuration files from a gzipped tarball and copies them into the real
    configuration directory.

    Any files in the agent's configuration directory that are not in the tarball will be removed as well.

    All files in the tarball should be relative to the main configuration directory, such as `/etc/scalyr-agent-2`.

    Note, the extracted files user and group ownership are changed to match those on the current configuration
    file to avoid permission issues.

    @param config_src: The path to the gzipped tarball, or `-` if the tarball should be read from stdin.
    @param config_file_path: The path to the current configuration file (the `agent.json` file).
    @param configuration: The configuration object itself.
    @type config_src: str
    @type config_file_path: str
    @type configuration: Configuration
    """
    original_dir = os.getcwd()

    # Change to the directory the configuration file is in because all files in the tarball should be relative to it.
    config_dir = os.path.dirname(config_file_path)
    os.chdir(config_dir)

    # Get the owner/group information for the current configuration file.  We want this in TarInfo format so that it
    # can be more easily used below.. and it gets around cross-platform compatibility problems.
    existing_config_tarinfo = get_tarinfo(config_file_path)

    try:
        if config_src != '-':
            in_tar = tarfile.open(config_src, 'r:gz')
        else:
            in_tar = tarfile.open(fileobj=sys.stdin, mode='r|gz')

        # Track which files were in the tarball so that we can delete unused ones later.
        used_files = dict()

        # The order of operations is important here.  For streamed tarfiles, we need to extract the files first.
        in_tar.extractall()

        # Go back and mark the extract files as used and also chown the files to have the same owner/group as the
        # current config.
        for x in in_tar.getmembers():
            used_files[get_canonical_name(x.name)] = True
            in_tar.chown(existing_config_tarinfo, x.name)

        in_tar.close()

        # Delete any files in the config directory that are on disk but did not come from the tarball.
        for x in glob.glob(os.path.join(configuration.config_directory, "*.json")):
            cname = get_canonical_name(x)
            if cname not in used_files:
                os.unlink(cname)

    finally:
        os.chdir(original_dir)


def create_custom_dockerfile(tarball_path, config_file_path, configuration, label='-docker', docker_config_name='.custom_agent_config'):
    """Creates a gzipped tarball that, when unpacked, contains a Dockerfile that can be used to create a custom
    Docker image that includes whatever configuration files this agent install currently has.

    @param tarball_path: The path to write the gzipped tarball, or `-` if the tarball should written to stdout.
    @param config_file_path: The path to the current configuration file (the `agent.json` file).
    @param configuration: The configuration object itself.
    @param label: A label to apply between 'scalyr' and 'agent' of the image label.
    @param config_name: Which Dockerfile configuration to use as the base configuration
    @type tarball_path: str
    @type config_file_path: str
    @type configuration: Configuration
    """
    if tarball_path != '-':
        out_tar = tarfile.open(tarball_path, mode='w:gz')
    else:
        out_tar = tarfile.open(fileobj=sys.stdout, mode='w|gz')

    # Read the Dockerfile.custom_agent_config out of the misc directory and replace :latest with the version used
    # by this current agent install.  We want the version of this install in order to make sure the new docker image
    # is as close to what is currently running as possible.
    dockerfile_path = os.path.join(get_install_root(), 'misc', 'Dockerfile%s' % docker_config_name)
    fp = open(dockerfile_path)
    dockerfile_contents = fp.read().replace('/scalyr%s-agent:latest' % label, '/scalyr%s-agent:%s' % (label, SCALYR_VERSION))
    fp.close()

    dockerfile_fp = cStringIO.StringIO(dockerfile_contents)
    # Use the original Dockerfile's attributes (permissions, owner) as a template for the attributes in the archive.
    tarinfo = out_tar.gettarinfo(dockerfile_path)
    tarinfo.size = len(dockerfile_contents)
    tarinfo.name = 'Dockerfile'
    out_tar.addfile(tarinfo, fileobj=dockerfile_fp)
    dockerfile_fp.close()

    # Now, generate a tarball containing the exported config for this agent and save it in the tar.
    # Use a temporary file to save the config tarball in.
    config_tarball_fd, config_tarball_path = tempfile.mkstemp()
    config_tarball_fp = os.fdopen(config_tarball_fd, 'wb')

    export_config(config_tarball_path, config_file_path, configuration)

    out_tar.add(config_tarball_path, arcname='agent_config.tar.gz')
    config_tarball_fp.close()

    out_tar.close()


if __name__ == '__main__':
    parser = OptionParser(usage='Usage: scalyr-agent-2-config [options]')
    parser.add_option("-c", "--config-file", dest="config_filename",
                      help="Read configuration from FILE", metavar="FILE")
    parser.add_option("", "--set-key-from-stdin", action="store_true", dest="set_key_from_stdin", default=False,
                      help="Update the configuration file with a new API key read from standard input.  "
                           "The API key is used to authenticate requests to the Scalyr servers for the account.")
    parser.add_option("", "--set-key", dest="api_key",
                      help="Update the configuration file with the new API key."
                           "The API key is used to authenticate requests to the Scalyr servers for the account.")
    parser.add_option("", "--set-scalyr-server", dest="scalyr_server",
                      help="Updates the configuration to send all log uploads to the specified server.  This will "
                           "create a configuration file fragment `scalyr_server.json` in the config directory.  It "
                           "will overwrite any existing file at that path.")
    parser.add_option("", "--set-server-host", dest="server_host",
                      help="Adds a new configuration file in the ``agent.d`` directory to set the serverHost "
                           "server attribute.  Warning, if there are any other Scalyr configuration files that sets "
                           "a value for ``serverHost``, that value may override the one trying to be set here.  You "
                           "must be sure the ``agent.json`` file nor any file in ``agent.d`` sets a value for "
                           "``serverHost`` otherwise this might not work.")
    parser.add_option("", "--set-user", dest="executing_user",
                      help="Update which user account is used to run the agent.")
    parser.add_option("", "--upgrade-tarball", dest="upgrade_tarball",
                      help="Upgrade the agent to the new version contained in the specified tarball file."
                           "This agent must have been previously installed using the tarball method."
                           "The tarball must have been downloaded from Scalyr."
                           "You may only use this if you have not changed the locations for the config file, "
                           "log directory, and data directory from the default values."
                           "This will copy your existing config, log, and data directory and place them in the "
                           "new agent.  It will also restart the agent if it is currently running. "
                           "WARNING, this will delete the old install directory (excluding the log, data, config "
                           "which will be copied over to the new installation).  If you may have modified other files "
                           "then use the --preserve-old-install option to prevent it from being deleted.")
    parser.add_option("", "--preserve-old-install", action="store_true", dest="preserve_old_install", default=False,
                      help="When performing a tarball upgrade, move the old install to a temporary directory "
                           "instead of deleting it.")
    parser.add_option("", "--import-config", dest="import_config",
                      help="Extracts the agent configuration files from the provided gzipped tarball, overwriting the"
                           "current configuration files (stored in `agent.json` and the `agent.d` directory, and"
                           "removing any files not present in tarball.  Pass `-` to read the tarball from stdin.  Note,"
                           "it only affects files that end in `.json`.  Also, all the owner and group users for all "
                           "extracted files are reset to be the same owner/group of the current configuration file to "
                           "avoid permission problems.")
    parser.add_option("", "--export-config", dest="export_config",
                      help="Creates a new gzipped tarball using the current agent configuration files stored in the "
                           "`agent.json` file and the `agent.d` directory.  Pass `-` to write the tarball to stdout. "
                           "Note, this only copies files that end in `.json`.")
    parser.add_option("", "--docker-create-custom-dockerfile", dest="create_custom_dockerfile",
                      help="Creates a gzipped tarball that will extract to a Dockerfile that will build a custom "
                           "Docker image that includes the configuration from this agent installation and based off "
                           "of the same Scalyr Agent version as this agent.  Essentially, it is a snapshot of this "
                           "agent so that its configuration can be more easily used again for other Docker "
                           "containers.  The option value should either be a path to write the tarball or `-` to "
                           "write it to stdout.")
    parser.add_option("", "--k8s-create-custom-dockerfile", dest="create_custom_k8s_dockerfile",
                      help="Creates a gzipped tarball that will extract to a Dockerfile that will build a custom "
                           "Docker image that includes the configuration from this agent installation and based off "
                           "of the same Scalyr Agent version as this agent, and suitable for running on a Kubernetes "
                           "cluster.  Essentially, it is a snapshot of this agent so that its configuration can be "
                           "more easily used again when running as a Kubernetes Daemonset."
                           "The option value should either be a path to write the tarball or `-` to "
                           "write it to stdout.")

    # TODO: These options are only available on Windows platforms
    if 'win32' == sys.platform:
        parser.add_option("", "--upgrade-windows", dest="upgrade_windows", action="store_true", default=False,
                          help='Upgrade the agent if a new version is available')
        parser.add_option("", "--release-track", dest="release_track", default="stable",
                          help='The release track to use when upgrading using --upgrade-windows.  This defaults to '
                          '"stable" and is what consumers should use.')
        parser.add_option("", "--upgrade-without-ui", dest="upgrade_windows_no_ui", action="store_true", default=False,
                          help='If specified, will request the upgrade for the Windows agent will be run without the '
                          'UI.')
        # TODO: Once other packages (rpm, debian) include the 'templates' directory, we can make this available
        # beyond just Windows.
        parser.add_option("", "--init-config", dest="init_config", action="store_true", default=False,
                          help='Create an initial copy of the configuration file in the appropriate location.')
        parser.add_option("", "--no-error-if-config-exists", dest="init_config_ignore_exists", action="store_true",
                          default=False,
                          help='If using "--init-config", exit with success if the file already exists.')
        # These are a weird options we use to start the agent after the Windows install process finishes if there
        # was an agent running before.  If there was an agent, the write a special file
        # called the conditional restart marker.  So, if it exists, then we should start the agent.
        parser.add_option("", "--mark-conditional-restart", dest="mark_conditional_restart", action="store_true",
                          default=False,
                          help='Creates the marker file to restart the agent next time --conditional-restart is '
                               'specified if the agent is currently running.')
        parser.add_option("", "--conditional-restart", dest="conditional_restart", action="store_true",
                          default=False,
                          help='Starts the agent if the conditional restart file marker exists.')

    (options, args) = parser.parse_args()
    if len(args) > 1:
        print >> sys.stderr, 'Could not parse commandline arguments.'
        parser.print_help(sys.stderr)
        sys.exit(1)

    controller = PlatformController.new_platform()
    default_paths = controller.default_paths

    if options.config_filename is None:
        options.config_filename = default_paths.config_file_path

    if not os.path.isabs(options.config_filename):
        options.config_filename = os.path.abspath(options.config_filename)

    if 'win32' == sys.platform and options.init_config:
        # Create a copy of the configuration file and set the owner to be the current user.
        config_path = options.config_filename
        template_dir = os.path.join(os.path.dirname(config_path), 'templates')
        template = os.path.join(template_dir, 'agent_config.tmpl')

        if os.path.exists(config_path):
            if not options.init_config_ignore_exists:
                print >> sys.stderr, ('Cannot initialize configuration file at %s because file already exists.' %
                                      config_path)
                sys.exit(1)
            else:
                print >> sys.stderr, 'Configuration file already exists at %s, so doing nothing.' % config_path
        else:
            if not os.path.isdir(template_dir):
                print >> sys.stderr, ('Cannot initialize configuration file because template directory does not exist '
                                      'at %s' % template_dir)
                sys.exit(1)
            if not os.path.isfile(template):
                print >> sys.stderr, ('Cannot initialize configuration file because template file does not exist at'
                                      '%s' % template)
                sys.exit(1)

            # Copy the file.
            shutil.copy(template, config_path)
            controller.set_file_owner(config_path, controller.get_current_user())
            print 'Successfully initialized the configuration file.'

    if options.executing_user and controller.get_current_user() != 'root':
        print >> sys.stderr, 'You must be root to update the user account that is used to run the agent.'
        sys.exit(1)

    try:
        config_file = Configuration(options.config_filename, default_paths)
        config_file.parse()
    except Exception, e:
        print >> sys.stderr, 'Error reading configuration file: %s' % str(e)
        print >> sys.stderr, traceback.format_exc()
        print >> sys.stderr, 'Terminating, please fix the configuration file and restart agent.'
        sys.exit(1)

    controller.consume_config(config_file, options.config_filename)

    # See if we have to start the agent.  This is only used by Windows right now as part of its install process.
    if 'win32' == sys.platform and options.mark_conditional_restart:
        mark_conditional_restart(controller, config_file)

    if 'win32' == sys.platform and options.conditional_restart:
        restart_if_conditional_marker_exists(controller, config_file)

    if options.set_key_from_stdin:
        api_key = raw_input('Please enter key: ')
        set_api_key(config_file, options.config_filename, api_key)
    elif options.api_key is not None:
        set_api_key(config_file, options.config_filename, options.api_key)

    if options.scalyr_server is not None:
        set_scalyr_server(config_file, options.scalyr_server)

    if options.server_host is not None:
        set_server_host(config_file, options.server_host)

    if options.executing_user is not None:
        set_executing_user(config_file, options.config_filename, options.executing_user)

    if options.upgrade_tarball is not None:
        paths = options.upgrade_tarball.split(os.pathsep)
        if len(paths) == 1:
            sys.exit(upgrade_tarball_install(config_file, options.upgrade_tarball, options.preserve_old_install))
        else:
            # During the upgrade tarball process, the old agent code will execute the new agent's
            # scalyr-agent-2-config command with --upgrade-tarball set to two paths pointing to the old
            # agent install directory and the new install directory  to give the new package a chance to execute some
            # actions to perform the upgrade.  Currently, we do not do anything, but we need this here in case we ever
            # do find a need to take some action.
            sys.exit(finish_upgrade_tarball_install(paths[0], paths[1]))

    if 'win32' == sys.platform and options.upgrade_windows:
        sys.exit(upgrade_windows_install(config_file, options.release_track, use_ui=not options.upgrade_windows_no_ui))

    if options.export_config is not None:
        export_config(options.export_config, options.config_filename, config_file)

    if options.import_config is not None:
        import_config(options.import_config, options.config_filename, config_file)

    if options.create_custom_dockerfile is not None:
        create_custom_dockerfile(options.create_custom_dockerfile, options.config_filename, config_file)

    if options.create_custom_k8s_dockerfile is not None:
        create_custom_dockerfile(options.create_custom_k8s_dockerfile, options.config_filename, config_file, label="-k8s", docker_config_name=".custom_k8s_config")

    sys.exit(0)
