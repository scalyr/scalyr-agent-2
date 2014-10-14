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
import getpass
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import traceback

from distutils import spawn
from pwd import getpwnam
from optparse import OptionParser

from __scalyr__ import scalyr_init, determine_file_path

scalyr_init()

__file_path__ = determine_file_path()

from scalyr_agent.configuration import Configuration
from scalyr_agent.platform_controller import PlatformController, TARBALL_INSTALL

from scalyr_agent.platforms import register_supported_platforms
register_supported_platforms()


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

            # We will be installing in the same directory where scalyr-agent-2 is currently installed.  That directory
            # should be 4 levels back from this file.
            # The path to this file looks like: scalyr-agent-2/py/scalyr_agent/config_main.py

            install_directory = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file_path__))))

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

    (options, args) = parser.parse_args()
    if len(args) > 1:
        print >> sys.stderr, 'Could not parse commandline arguments.'
        parser.print_help(sys.stderr)
        sys.exit(1)

    if options.executing_user and getpass.getuser() != 'root':
        print >> sys.stderr, 'You must be root to update the user account that is used to run the agent.'
        sys.exit(1)

    controller = PlatformController.new_platform()
    default_paths = controller.default_paths

    if options.config_filename is None:
        options.config_filename = default_paths.config_file_path

    if not os.path.isabs(options.config_filename):
        options.config_filename = os.path.abspath(options.config_filename)

    try:
        config_file = Configuration(options.config_filename, default_paths, controller.default_monitors, None, None)
        config_file.parse()
    except Exception, e:
        print >> sys.stderr, 'Error reading configuration file: %s' % str(e)
        print >> sys.stderr, traceback.format_exc()
        print >> sys.stderr, 'Terminating, please fix the configuration file and restart agent.'
        sys.exit(1)

    if options.set_key_from_stdin:
        api_key = raw_input('Please enter key: ')
        set_api_key(config_file, options.config_filename, api_key)
    elif options.api_key is not None:
        set_api_key(config_file, options.config_filename, options.api_key)

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

    sys.exit(0)
