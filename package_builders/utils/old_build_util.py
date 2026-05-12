# Copyright 2026 Scalyr Inc.
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

# TODO: Eliminate this file by updating any builder referencing it to the "new" building
# utilities.
#
# This file contains definitions for the functions previously used by the
# original `build_packages.py` script. Any builder referencing these functions have
# not been fully migrated over to the "new" building approach. When we have time, we should
# move them over.

import errno
import glob
import json
import os
import pathlib as pl
import shutil
import re
import subprocess
import sys
import tempfile
import uuid
from io import StringIO
from time import strftime, gmtime


_source_root_ = pl.Path(__file__).parent.parent.parent.absolute()

# A GUID representing Scalyr products in Windows, used to generate a per-version guid for each version of the Windows
# Scalyr Agent.  DO NOT MODIFY THIS VALUE, or already installed software on customer machines will not be able
# to be upgraded.
_scalyr_guid_ = uuid.UUID("{0b52b8a0-22c7-4d50-92c1-8ea3b258984e}")

# A string containing the build info for this build, to be placed in the 'build_info' file.
__build_info__ = None

def get_source_root():
    return _source_root_

def get_build_info():
    global __build_info__

def get_agent_version() -> str:
    return (get_source_root() / "VERSION").read_text().strip()

def ensure_binary(s, encoding='utf-8', errors='strict'):
    if isinstance(s, str):
        return s.encode(encoding, errors)
    elif isinstance(s, bytes):
        return s
    raise TypeError(f"Expected str or bytes, got {type(s).__name__}")

def run_command(command_str, exit_on_fail=True, fail_quietly=False, command_name=None):
    """Executes the specified command string returning the exit status.

    @param command_str: The command to execute.
    @param exit_on_fail: If True, will exit this process with a non-zero status if the command fails.
    @param fail_quietly:  If True, nothing will be emitted to stderr/stdout on failure.  If this is true,
        exit_on_fail will be ignored.
    @param command_name: The name to use to identify the command in error output.

    @return: The exist status and output string of the command.
    """
    # We have to use a temporary file to hold the output to stdout and stderr.
    output_file_fd, output_file = tempfile.mkstemp()

    output_fp = os.fdopen(output_file_fd, "w")

    try:
        return_code = subprocess.call(
            command_str, stdin=None, stderr=output_fp, stdout=output_fp, shell=True
        )
        output_fp.flush()

        # Read the output back into a string.  We cannot use a cStringIO.StringIO buffer directly above with
        # subprocess.call because that method expects fileno support which StringIO doesn't support.
        output_buffer = StringIO()
        input_fp = open(output_file, "rb")
        for line in input_fp:
            output_buffer.write(line.decode("utf-8"))
        input_fp.close()

        output_str = output_buffer.getvalue()
        output_buffer.close()

        if return_code != 0 and not fail_quietly:
            if command_name is not None:
                print(
                    "Executing %s failed and returned a non-zero result of %d"
                    % (
                        command_name,
                        return_code,
                    ),
                    file=sys.stderr,
                    )
            else:
                print(
                    "Executing the following command failed and returned a non-zero result of %d"
                    % return_code,
                    file=sys.stderr,
                    )
                print('  Command: "%s"' % command_str, file=sys.stderr)

            print("The output was:", file=sys.stderr)
            print(output_str, file=sys.stderr)

            if exit_on_fail:
                print("Exiting due to failure.", file=sys.stderr)
                sys.exit(1)

        if isinstance(output_str, bytes):
            # Ensure we return string type
            output_str = output_str.decode("utf-8")

        return return_code, output_str

    finally:
        # Be sure to close the temporary file and delete it.
        output_fp.close()
        os.unlink(output_file)

def get_build_info():
    """Returns a dictionary containing the build info."""

    global __build_info__

    if __build_info__:
        return __build_info__

    original_dir = os.getcwd()

    __build_info__ = {}

    try:
        # We need to execute the git command in the source root.
        os.chdir(get_source_root())
        # Add in the e-mail address of the user building it.
        (rc, packager_email) = run_command(
            "git config user.email", fail_quietly=True, command_name="git"
        )
        if rc != 0:
            packager_email = "unknown"

        __build_info__["packaged_by"] = packager_email.strip()

        # Determine the last commit from the log.
        (_, commit_id) = run_command(
            "git log --summary -1 | head -n 1 | cut -d ' ' -f 2",
            exit_on_fail=True,
            command_name="git",
        )

        __build_info__["latest_commit"] = commit_id.strip()

        # Include the branch just for safety sake.
        (_, branch) = run_command(
            "git branch | cut -d ' ' -f 2", exit_on_fail=True, command_name="git"
        )
        __build_info__["from_branch"] = branch.strip()

        # Add a timestamp.

        __build_info__["build_time"] = str(
            strftime("%Y-%m-%d %H:%M:%S UTC", gmtime())
        )

        return __build_info__
    finally:
        os.chdir(original_dir)


def get_install_info(install_type):
    """
    Get json serialized string with installation info.
    """
    return json.dumps(
        {"build_info": get_build_info(), "install_type": install_type},
        indent=4,
        sort_keys=True,
    )

def make_directory(path):
    """Creates the specified directory including any parents that do not yet exist.

    @param path: The path of the directory to create. This string can use a forward slash to separate path
           components regardless of the separator character for this platform.  This method will perform the necessary
           conversion.
    """
    converted_path = convert_path(path)
    try:
        os.makedirs(converted_path)
    except OSError as error:
        if error.errno == errno.EEXIST and os.path.isdir(converted_path):
            pass
        else:
            raise


def make_path(parent_directory, path):
    """Returns the full path created by joining path to parent_directory.

    This method is a convenience function because it allows path to use forward slashes
    to separate path components rather than the platform's separator character.

    @param parent_directory: The parent directory. This argument must use the system's separator character. This may be
        None if path is relative to the current working directory.
    @param path: The path to add to parent_directory. This should use forward slashes as the separator character,
        regardless of the platform's character.

    @return:  The path created by joining the two with using the system's separator character.
    """
    if parent_directory is None and os.path.sep == "/":
        return path

    if parent_directory is None:
        result = ""
    elif path.startswith("/"):
        result = ""
    else:
        result = parent_directory

    for path_part in path.split("/"):
        if len(path_part) > 0:
            result = os.path.join(result, path_part)

    return result


def convert_path(path):
    """Converts the forward slashes in path to the platform's separator and returns the value.

    @param path: The path to convert. This should use forward slashes as the separator character, regardless of the
        platform's character.

    @return: The path created by converting the forward slashes to the platform's separator.
    """
    return make_path(None, path)


def make_soft_link(source, link_path):
    """Creates a soft link at link_path to source.

    @param source: The path that the link will point to. This should use a forward slash as the separator, regardless
        of the platform's separator.
    @param link_path: The path where the link will be created. This should use a forward slash as the separator,
        regardless of the platform's separator.
    """
    os.symlink(convert_path(source), convert_path(link_path))


def glob_files(path):
    """Returns the paths that match the specified path glob (based on current working directory).

    @param path: The path with glob wildcard characters to match. This should use a forward slash as the separator,
        regardless of the platform's separator.

    @return: The list of matched paths.
    """
    return glob.glob(convert_path(path))


def recursively_delete_dirs_by_name(*dir_names):
    """Deletes any directories that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    If a directory is found that needs to be deleted, all of it and its children are deleted.

    @param dir_names: A variable number of strings containing regular expressions that should match the file names of
        the directories that should be deleted.
    """
    # Compile the strings into actual regular expression match objects.
    matchers = []
    for dir_name in dir_names:
        matchers.append(re.compile(dir_name))

    # Walk down the file tree, top down, allowing us to prune directories as we go.
    for root, dirs, files in os.walk("."):
        # The list of directories at the current level to delete.
        to_remove = []

        # Examine all directories at this level, see if any get a match
        for dir_path in dirs:
            remove_it = False
            for matcher in matchers:
                if matcher.match(dir_path):
                    remove_it = True
            if remove_it:
                to_remove.append(dir_path)

        # Go back and delete it.  Also, remove it from dirs so that we don't try to walk down it.
        for remove_dir_path in to_remove:
            shutil.rmtree(os.path.join(root, remove_dir_path))
            dirs.remove(remove_dir_path)


def recursively_delete_files_by_name(*file_names):
    """Deletes any files that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    @param file_names: A variable number of strings containing regular expressions that should match the file names of
        the files that should be deleted.
    """
    # Compile the strings into actual regular expression match objects.
    matchers = []
    for file_name in file_names:
        matchers.append(re.compile(file_name))

    # Walk down the current directory.
    for root, dirs, files in os.walk("."):
        # See if any of the files at this level match any of the matchers.
        for file_path in files:
            remove_it = False
            for matcher in matchers:
                if matcher.match(file_path):
                    remove_it = True
            # Delete it if it did match.
            if remove_it:
                os.unlink(os.path.join(root, file_path))


def cat_files(file_paths, destination, convert_newlines=False):
    """Concatenates the contents of the specified files and writes it to a new file at destination.

    @param file_paths: A list of paths for the files that should be read. The concatenating will be done in the same
        order as the list.
    @param destination: The path of the file to write the contents to.
    @param convert_newlines: If True, the final file will use Windows newlines (i.e., CR LF).
    """
    dest_fp = open(destination, "w")
    for file_path in file_paths:
        in_fp = open(file_path, "r")
        for line in in_fp:
            if convert_newlines:
                line.replace("\n", "\r\n")
            dest_fp.write(line)
        in_fp.close()
    dest_fp.close()


def write_to_file(string_value, file_path):
    """Writes the specified string to a new file.

    This removes trailing newlines, etc, to avoid adding an extra blank line.

    @param string_value: The value to write to the file.
    @param file_path: The path of the file to write to.
    """
    with open(file_path, "wb") as dest_fp:
        dest_fp.write(ensure_binary(string_value.rstrip()))
        dest_fp.write(ensure_binary(os.linesep))


def create_scalyr_uuid3(name):
    """
    Create a UUID based on the Scalyr UUID namespace and a hash of `name`.

    :param name: The name
    :type name: str
    :return: The UUID
    :rtype: uuid.UUID
    """
    return uuid.uuid3(_scalyr_guid_, name)

def replace_shebang(path, new_path, new_shebang):
    # type: (str, str, str) ->None
    with open(path, "r") as f:
        with open(new_path, "w") as newf:
            # skip shebang
            f.readline()
            newf.write(new_shebang)
            newf.write("\n")
            newf.write(f.read())

def build_base_files(install_type, base_configs="config"):
    """Build the basic structure for a package in a new directory scalyr-agent-2 in the current working directory.

    This creates scalyr-agent-2 in the current working directory and then populates it with the basic structure
    required by most of the packages.

    It copies the source files, the certs, the configuration directories, etc.  This will make sure to exclude
    files like .pyc, .pyo, etc.

    In the end, the structure will look like:
      scalyr-agent-2:
        py/scalyr_agent/           -- All the scalyr_agent source files
        certs/ca_certs.pem         -- The trusted SSL CA root list.
        config/agent.json          -- The configuration file.
        bin/scalyr-agent-2         -- Symlink to the agent_main.py file to run the agent.
        bin/scalyr-agent-2-config  -- Symlink to config_main.py to run the configuration tool
        build_info                 -- A file containing the commit id of the latest commit included in this package,
                                      the time it was built, and other information.

    @param install_type: String with type of the installation. For now it can be 'package' or 'tar'
    @param base_configs:  The directory (relative to the top of the source tree) that contains the configuration
        files to copy (such as the agent.json and agent.d directory).  If None, then will use `config`.
    """
    original_dir = os.getcwd()
    # This will return the parent directory of this file.  We will use that to determine the path
    # to files like scalyr_agent/ to copy the source files
    agent_source_root = get_source_root()

    make_directory("scalyr-agent-2/py")
    os.chdir("scalyr-agent-2")

    make_directory("certs")
    make_directory("bin")
    make_directory("misc")

    # Copy the version file.  We copy it both to the root and the package root.  The package copy is done down below.
    shutil.copy(make_path(agent_source_root, "VERSION"), "VERSION")

    # Copy the source files.
    os.chdir("py")

    shutil.copytree(make_path(agent_source_root, "scalyr_agent"), "scalyr_agent")

    # Write install_info file inside the 'scalyr_agent' package.
    os.chdir("scalyr_agent")

    install_info = get_install_info(install_type)
    write_to_file(install_info, "install_info.json")
    os.chdir("..")

    shutil.copytree(make_path(agent_source_root, "monitors"), "monitors")
    os.chdir("monitors")
    recursively_delete_files_by_name("README.md")
    os.chdir("..")
    shutil.copy(
        make_path(agent_source_root, "VERSION"),
        os.path.join("scalyr_agent", "VERSION"),
    )

    # create copies of the agent_main.py with python2 and python3 shebang.
    agent_main_path = os.path.join(agent_source_root, "scalyr_agent", "agent_main.py")
    agent_main_py2_path = os.path.join("scalyr_agent", "agent_main_py2.py")
    agent_main_py3_path = os.path.join("scalyr_agent", "agent_main_py3.py")
    replace_shebang(agent_main_path, agent_main_py2_path, "#!/usr/bin/env python2")
    replace_shebang(agent_main_path, agent_main_py3_path, "#!/usr/bin/env python3")
    main_permissions = os.stat(agent_main_path).st_mode
    os.chmod(agent_main_py2_path, main_permissions)
    os.chmod(agent_main_py3_path, main_permissions)

    # Exclude certain files.
    # TODO:  Should probably use MANIFEST.in to do this, but don't know the Python-fu to do this yet.
    #
    # Don't include the tests directories.  Also, don't include the .idea directory created by IDE.
    recursively_delete_dirs_by_name(r"\.idea", "tests")
    recursively_delete_files_by_name(
        r".*\.pyc", r".*\.pyo", r".*\.pyd", r"all_tests\.py", r".*~"
    )

    os.chdir("..")

    # Copy the config
    if base_configs is not None:
        config_path = base_configs
    else:
        config_path = "config"

    shutil.copytree(make_path(agent_source_root, config_path), "config")

    # Make sure config file has 640 permissions
    os.chmod("config/agent.json", int("640", 8))

    # Create the trusted CA root list.
    os.chdir("certs")
    cat_files(
        glob_files(make_path(agent_source_root, "certs/*_root.pem")), "ca_certs.crt"
    )
    cat_files(
        glob_files(make_path(agent_source_root, "certs/*_intermediate.pem")),
        "intermediate_certs.pem",
    )
    for cert_file in glob_files(make_path(agent_source_root, "certs/*.pem")):
        shutil.copy(cert_file, cert_file.split("/")[-1])

    # TODO: Check certificate expiration same as we do as part of tox lint target
    # NOTE: This requires us to update Jenkins pipeline and other places where this script is called
    # to install cryptography library
    os.chdir("..")

    # Misc extra files needed for some features.
    os.chdir("misc")
    # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.  We
    # put it in all distributions (not just the docker_tarball) in case a customer creates an imagine using a package.
    shutil.copy(
        make_path(agent_source_root, "docker/Dockerfile.custom_agent_config"),
        "Dockerfile.custom_agent_config",
    )
    shutil.copy(
        make_path(agent_source_root, "docker/Dockerfile.custom_k8s_config"),
        "Dockerfile.custom_k8s_config",
    )
    os.chdir("..")

    # Create symlinks for the agent_main
    os.chdir("bin")

    make_soft_link("../py/scalyr_agent/agent_main.py", "scalyr-agent-2")

    shutil.copy(
        make_path(
            agent_source_root,
            "package_builders/files/linux/scalyr-agent-2-config",
        ),
        "scalyr-agent-2-config",
    )

    # add switch python version script.
    shutil.copy(
        os.path.join(
            agent_source_root,
            "package_builders/managed_packages/non-aio/files/bin/scalyr-switch-python.sh",
        ),
        "scalyr-switch-python",
    )

    os.chdir("..")

    os.chdir(original_dir)