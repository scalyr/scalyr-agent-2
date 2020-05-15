#!/usr/bin/env python
#
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
# Script used to build the RPM, Debian, and tarball packages for releasing Scalyr Agent 2.
#
# To execute this script, you must have installed fpm: https://github.com/jordansissel/fpm
#
# Usage: python build_package.py [options] rpm|tarball|deb
#
# author: Steven Czerwinski <czerwin@scalyr.com>

from __future__ import absolute_import
from __future__ import print_function

__author__ = "czerwin@scalyr.com"

import errno
import glob
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

from io import StringIO
from io import BytesIO
from io import open

from optparse import OptionParser
from time import gmtime, strftime

from scalyr_agent.__scalyr__ import get_install_root, SCALYR_VERSION, scalyr_init

scalyr_init()

import scalyr_agent.util as scalyr_util

# [start of 2->TODO]
# Check for suitability.
# Important. Import six as any other dependency from "third_party" libraries after "__scalyr__.scalyr_init"
import six
from six.moves import range

# [end of 2->TOD0]

# The root of the Scalyr repository should just be the parent of this file.
__source_root__ = get_install_root()

# All the different packages that this script can build.
PACKAGE_TYPES = [
    "rpm",
    "tarball",
    "deb",
    "win32",
    "docker_syslog_builder",
    "docker_json_builder",
    "k8s_builder",
]


def build_package(package_type, variant, no_versioned_file_name, coverage_enabled):
    """Builds the scalyr-agent-2 package specified by the arguments.

    The package is left in the current working directory.  The file name of the
    package is returned by this function.

    @param package_type: One of `PACKAGE_TYPES`. Determines which package type is built.
    @param variant: Adds the specified string into the package's iteration name. This may be None if no additional
        tweak to the name is required. This is used to produce different packages even for the same package type (such
        as 'rpm').
    @param no_versioned_file_name:  If True, will not embed a version number in the resulting artifact's file name.
        This only has an affect if building one of the tarball formats.
    @param coverage_enabled: If True, enables coverage analysis. Patches Dockerfile to run agent with coverage.

    @return: The file name of the produced package.
    """
    original_cwd = os.getcwd()

    version = SCALYR_VERSION

    # Create a temporary directory to build the package in.
    tmp_dir = tempfile.mkdtemp(prefix="build-scalyr-agent-packages")

    try:
        # Change to that directory and delegate to another method for the specific type.
        os.chdir(tmp_dir)
        if package_type == "tarball":
            artifact_file_name = build_tarball_package(
                variant, version, no_versioned_file_name
            )
        elif package_type == "win32":
            artifact_file_name = build_win32_installer_package(variant, version)
        elif package_type == "docker_syslog_builder":
            # An image for running on Docker configured to receive logs from other containers via syslog.
            # This is the deprecated approach (but is still published under scalyr/scalyr-docker-agent for
            # backward compatibility.)  We also publish this under scalyr/scalyr-docker-agent-syslog to help
            # with the eventual migration.
            artifact_file_name = build_container_builder(
                variant,
                version,
                no_versioned_file_name,
                "scalyr-docker-agent.tar.gz",
                "docker/Dockerfile.syslog",
                "docker/docker-syslog-config",
                "scalyr-docker-agent-syslog",
                ["scalyr/scalyr-agent-docker-syslog", "scalyr/scalyr-agent-docker"],
                coverage_enabled=coverage_enabled,
            )
        elif package_type == "docker_json_builder":
            # An image for running on Docker configured to fetch logs via the file system (the container log
            # directory is mounted to the agent container.)  This is the preferred way of running on Docker.
            # This image is published to scalyr/scalyr-agent-docker-json.
            artifact_file_name = build_container_builder(
                variant,
                version,
                no_versioned_file_name,
                "scalyr-docker-agent.tar.gz",
                "docker/Dockerfile",
                "docker/docker-json-config",
                "scalyr-docker-agent-json",
                ["scalyr/scalyr-agent-docker-json"],
                coverage_enabled=coverage_enabled,
            )
        elif package_type == "k8s_builder":
            # An image for running the agent on Kubernetes.
            artifact_file_name = build_container_builder(
                variant,
                version,
                no_versioned_file_name,
                "scalyr-k8s-agent.tar.gz",
                "docker/Dockerfile.k8s",
                "docker/k8s-config",
                "scalyr-k8s-agent",
                ["scalyr/scalyr-k8s-agent"],
                coverage_enabled=coverage_enabled,
            )
        else:
            assert package_type in ("deb", "rpm")
            artifact_file_name = build_rpm_or_deb_package(
                package_type == "rpm", variant, version
            )

        os.chdir(original_cwd)

        # Move the artifact (built package) to the original current working dir.
        shutil.move(os.path.join(tmp_dir, artifact_file_name), artifact_file_name)
        return artifact_file_name
    finally:
        # Be sure to delete the temporary directory.
        os.chdir(original_cwd)
        shutil.rmtree(tmp_dir)


# A GUID representing Scalyr products, used to generate a per-version guid for each version of the Windows
# Scalyr Agent.  DO NOT MODIFY THIS VALUE, or already installed software on clients machines will not be able
# to be upgraded.
_scalyr_guid_ = uuid.UUID("{0b52b8a0-22c7-4d50-92c1-8ea3b258984e}")


def build_win32_installer_package(variant, version):
    """Builds an MSI that will install the agent on a win32 machine in the current working directory.

    Note, this can only be run on a Windows machine with the proper binaries and packages installed.

    @param variant: If not None, will add the specified string to the GUID used to identify the installed
        executables.  This can be used to avoid customer builds of the agent from colliding with the Scalyr-built
        ones.
    @param version: The agent version.

    @return: The file name of the built package.
    """
    if os.getenv("WIX") is None:
        print(
            "Error, the WIX toolset does not appear to be installed.", file=sys.stderr
        )
        print(
            "Please install it to build the Windows Scalyr Agent installer.",
            file=sys.stderr,
        )
        print("See http://wixtoolset.org.", file=sys.stderr)
        sys.exit(1)

    try:
        import psutil  # NOQA
    except ImportError:
        # noinspection PyUnusedLocal
        print(
            "Error, the psutil Python module is not installed.  This is required to build the",
            file=sys.stderr,
        )
        print(
            "Windows version of the Scalyr Agent.  Please download and install it.",
            file=sys.stderr,
        )
        print("See http://pythonhosted.org/psutil/", file=sys.stderr)
        print(
            'On many systems, executing "pip install psutil" will install the package.',
            file=sys.stderr,
        )
        sys.exit(1)

    make_directory("source_root")
    make_directory("data_files")

    agent_source_root = __source_root__

    # Populate source_root
    os.chdir("source_root")

    shutil.copytree(make_path(agent_source_root, "scalyr_agent"), "scalyr_agent")
    # We have to move __scalyr__.py up to the top of the source_root since, when running in the environment
    # generated by py2exe, an 'import __scalyr__.py' will not look in the current directory.. it will only look
    # for that module at the top of the sources_root.  Essentially, the PYTHONPATH variable only has a single
    # entry in it, and it does not have '.' in it.  We leave a copy of __scalyr__.py in the original scalyr_agent
    # directory because we need it there when we execute setup.py.  For the same reason, we put a copy of VERSION.txt.
    shutil.copy(convert_path("scalyr_agent/__scalyr__.py"), "__scalyr__.py")
    shutil.copy(make_path(agent_source_root, "VERSION.txt"), "VERSION.txt")
    shutil.copy(
        make_path(agent_source_root, "VERSION.txt"),
        convert_path("scalyr_agent/VERSION.txt"),
    )

    shutil.copytree(make_path(agent_source_root, "monitors"), "monitors")

    os.chdir("monitors")
    recursively_delete_files_by_name("README.md")
    os.chdir("..")

    # Exclude certain files.
    # TODO:  Should probably use MANIFEST.in to do this, but don't know the Python-fu to do this yet.
    #
    # Don't include the tests directories.  Also, don't include the .idea directory created by IDE.
    recursively_delete_dirs_by_name(r"\.idea", "tests")
    recursively_delete_files_by_name(
        r".*\.pyc", r".*\.pyo", r".*\.pyd", r"all_tests\.py", r".*~"
    )

    # exclude all the third_party_tls libs under windows
    # because windows python has tls built in.
    recursively_delete_dirs_by_name("third_party_tls")

    # Move back up to the root directory and populate the data_files.
    os.chdir("..")
    os.chdir("data_files")

    # Copy the version file.  We copy it both to the root and the package root.  The package copy is done down below.
    shutil.copy(make_path(agent_source_root, "VERSION.txt"), "VERSION.txt")
    shutil.copy(make_path(agent_source_root, "LICENSE.txt"), "LICENSE.txt")

    # Copy the third party licenses
    shutil.copytree(
        make_path(agent_source_root, "scalyr_agent/third_party/licenses"), "licenses"
    )

    # Copy the config file.
    cat_files(
        [make_path(agent_source_root, "config/agent.json")],
        "agent_config.tmpl",
        convert_newlines=True,
    )

    os.chdir("..")
    # We need to place a 'setup.py' here so that when we executed py2exe it finds it.
    shutil.copy(make_path(agent_source_root, "setup.py"), "setup.py")

    shutil.copy(
        make_path(agent_source_root, "DESCRIPTION.rst"),
        convert_path("source_root/DESCRIPTION.rst"),
    )
    pyinstaller_spec_path = os.path.join(
        agent_source_root, "win32", "scalyr-agent.spec"
    )

    shutil.copy(pyinstaller_spec_path, "scalyr-agent.spec")
    shutil.copy(
        os.path.join(agent_source_root, "win32", "wix-heat-bin-transform.xsl"),
        "wix-heat-bin-transform.xsl",
    )

    shutil.copy(
        os.path.join(agent_source_root, "win32", "scalyr_agent.wxs"), "scalyr_agent.wxs"
    )

    run_command(
        "{0} pyinstaller scalyr-agent.spec".format(sys.executable),
        exit_on_fail=True,
        command_name="pyinstaller",
    )

    make_directory("Scalyr/certs")
    make_directory("Scalyr/logs")
    make_directory("Scalyr/data")
    make_directory("Scalyr/config/agent.d")
    os.rename(os.path.join("dist", "scalyr-agent-2"), convert_path("Scalyr/bin"))
    shutil.copy(
        make_path(agent_source_root, "win32/ScalyrShell.cmd"),
        "Scalyr/bin/ScalyrShell.cmd",
    )

    # Copy the cert files.
    # AGENT-283: Certificate validation on windows seems to fail when the intermediate certs are present, skipping them
    cat_files(
        glob_files(make_path(agent_source_root, "certs/*_root.pem")),
        "Scalyr/certs/ca_certs.crt",
        convert_newlines=True,
    )

    # Generate the file used by WIX's candle program.
    # create_wxs_file(
    #     make_path(agent_source_root, "win32/scalyr_agent.wxs"),
    #     convert_path("Scalyr/bin"),
    #     "scalyr_agent.wxs",
    # )

    # Get ready to run wix.  Add in WIX to the PATH variable.
    os.environ["PATH"] = "%s;%s\\bin" % (os.getenv("PATH"), os.getenv("WIX"))

    if variant is None:
        variant = "main"

    # Generate a unique identifier used to identify this version of the Scalyr Agent to windows.
    product_code = create_scalyr_uuid3("ProductID:%s:%s" % (variant, version))
    # The upgrade code identifies all families of versions that can be upgraded from one to the other.  So, this
    # should be a single number for all Scalyr produced ones.
    upgrade_code = create_scalyr_uuid3("UpgradeCode:%s" % variant)

    # For prereleases, we use weird version numbers like 4.0.4.pre5.1 .  That does not work for Windows which
    # requires X.X.X.X.  So, we convert if necessary.
    if len(version.split(".")) == 5:
        parts = version.split(".")
        del parts[3]
        version = ".".join(parts)

    run_command(
        "heat dir Scalyr/bin -sreg -ag -cg BIN -dr APPLICATIONROOTDIRECTORY -var var.BinFolderSource -t wix-heat-bin-transform.xsl -o bin.wxs",
        exit_on_fail=True,
        command_name="heat",
    )

    run_command(
        'candle -nologo -out bin.wixobj bin.wxs -dBinFolderSource="Scalyr/bin"',
        exit_on_fail=True,
        command_name="candle",
    )

    run_command(
        'candle -nologo -out ScalyrAgent.wixobj -dVERSION="%s" -dUPGRADECODE="%s" '
        '-dPRODUCTCODE="%s" scalyr_agent.wxs' % (version, upgrade_code, product_code),
        exit_on_fail=True,
        command_name="candle",
    )

    installer_name = "ScalyrAgentInstaller-%s.msi" % version
    run_command(
        "light -nologo -ext WixUtilExtension.dll -ext WixUIExtension -out %s ScalyrAgent.wixobj bin.wixobj -v"
        % installer_name,
        exit_on_fail=True,
        command_name="light",
    )
    return installer_name


def create_wxs_file(template_path, dist_path, destination_path):
    """Performs a rewrite of the Wix file to replace template-like poritions with information about the
    binaries/files in `dist_path`.

    This is required so that our Windows installer includes all of the DLLs, Python compiled files, etc that py2exe
    produced.  This list can change over time and is dependent on the build machine, so we cannot hard code this
    list.  It must be determined dynamically.

    The file is rewrite by expanding the 'templates' found between the '<!-- EXPAND_FROM_BIN' markers.  This will
    make a copy of the included template, once for each file in the `dist_path`, replacing such variables as
    $COMPONENT_ID, $COMPONENT_GUID, $FILE_ID, and $FILE_SOURCE with values calculated on the file's information.

    You may also specify a list of files to exclude in `dist_path` from the template expansion.  This is used for
    well-known files that are already in the Wix file.

    Here is an example:
      <!-- EXPAND_FROM_BIN EXCLUDE:scalyr-agent-2.exe,scalyr-agent-2-config.exe,ScalyrAgentService.exe -->
        <Component Id='$COMPONENT_ID' Guid='$COMPONENT_GUID' >
          <File Id='$FILE_ID' DiskId='1' KeyPath='yes' Checksum='yes'  Source='$FILE_SOURCE' />
         </Component>
      <!-- EXPAND_FROM_BIN -->

    @param template_path: The file path storing the Wix file to copy/rewrite.
    @param dist_path: The path to the directory containing the files that should be included in the template
        expansion.
    @param destination_path: The file path to write the result

    @type template_path: str
    @type dist_path: str
    @type destination_path: str
    """
    # First, calculate all of the per-file information for each file in the distribution directory.
    dist_files = []
    for dist_file_path in glob.glob("%s/*" % dist_path):
        base_file = os.path.basename(dist_file_path)
        file_id = base_file.replace(".", "_").replace("-", "_")
        entry = {
            "BASE": base_file,
            "FILE_ID": file_id,
            "COMPONENT_GUID": str(create_scalyr_uuid3("DistComp%s" % base_file)),
            "COMPONENT_ID": "%s_comp" % file_id,
            "FILE_SOURCE": dist_file_path,
        }

        dist_files.append(entry)

    # For the sake of easier coding, we read all of the lines of the input file into an array.
    f = open(template_path)
    try:
        template_lines = f.readlines()
    finally:
        f.close()

    # Now go through, looking for the markers, and when we find them, do the replacement.
    result = []
    while len(template_lines) > 0:
        if "<!-- EXPAND_FROM_BIN" in template_lines[0]:
            result.extend(expand_template(template_lines, dist_files))
        else:
            line = template_lines[0]
            del template_lines[0]
            result.append(line)

    # Write the resulting lines out.
    f = open(destination_path, "w")
    try:
        for line in result:
            f.write(line)
    finally:
        f.close()


def create_scalyr_uuid3(name):
    """
    Create a UUID based on the Scalyr UUID namespace and a hash of `name`.

    :param name: The name
    :type name: six.text
    :return: The UUID
    :rtype: uuid.UUID
    """
    return scalyr_util.create_uuid3(_scalyr_guid_, name)


def expand_template(input_lines, dist_files):
    """Reads the template starting at the first entry in `input_lines` and generates a copy of it for each
    item in `dist_files` that is not excluded.

    Used by `create_wxs_file`.

    This consumes the lines from the `input_lines` list.

    @param input_lines: The list of input lines from the file, with the first beginning a template expansion
        (should have the <!-- EXPAND_FROM_BIN pragma in it).
    @param dist_files: The list of file entries from the distribution directory.  The template should be expanded
        once for each entry (unless it was specifically excluded).

    @type input_lines: [str]
    @type dist_files:  [{}]

    @return: The list of lines produced by the expansion.
    @rtype: [str]
    """
    # First, see if there were any files that should be excluded.  This will be in the first line, prefaced by
    # EXCLUDED and a comma separated list.
    match = re.search(r"EXCLUDE:(\S*)", input_lines[0])
    del input_lines[0]

    if match is not None:
        excluded_files = match.group(1).split(",")
    else:
        excluded_files = []

    # Create a list of just the template.  We need to find where it ends in the input lines.
    template_lines = []
    found_end = False
    while len(input_lines) > 0:
        line = input_lines[0]
        del input_lines[0]
        if "<!-- EXPAND_FROM_BIN" in line:
            found_end = True
            break
        else:
            template_lines.append(line)

    if not found_end:
        raise Exception("Did not find termination for EXPAND_FROM_BIN")

    result = []
    # Do the expansion.
    for dist_entry in dist_files:
        if dist_entry["BASE"] in excluded_files:
            continue

        for template_line in template_lines:
            line = template_line.replace("$FILE_ID", dist_entry["FILE_ID"])
            line = line.replace("$COMPONENT_GUID", dist_entry["COMPONENT_GUID"])
            line = line.replace("$COMPONENT_ID", dist_entry["COMPONENT_ID"])
            line = line.replace("$FILE_SOURCE", dist_entry["FILE_SOURCE"])

            result.append(line)

    return result


def build_common_docker_and_package_files(create_initd_link, base_configs=None):
    """Builds the common `root` system used by Debian, RPM, and container source tarballs in the current working
    directory.

    @param create_initd_link: Whether or not to create the link from initd to the scalyr agent binary.
    @param base_configs:  The directory (relative to the top of the source tree) that contains the configuration
        files to copy (such as the agent.json and agent.d directory).  If None, then will use `config`.
    @type create_initd_link: bool
    @type base_configs: str
    """
    original_dir = os.getcwd()

    # Create the directory structure for where the RPM/Debian package will place files on the system.
    make_directory("root/etc/init.d")
    make_directory("root/var/log/scalyr-agent-2")
    make_directory("root/var/lib/scalyr-agent-2")
    make_directory("root/usr/share")
    make_directory("root/usr/sbin")

    # Place all of the import source in /usr/share/scalyr-agent-2.
    os.chdir("root/usr/share")

    build_base_files(base_configs=base_configs)

    os.chdir("scalyr-agent-2")
    # The build_base_files leaves the config directory in config, but we have to move it to its etc
    # location.  We just rename it to the right directory.
    shutil.move(
        convert_path("config"), make_path(original_dir, "root/etc/scalyr-agent-2")
    )
    os.chdir(original_dir)

    # Make sure there is an agent.d directory regardless of the config directory we used.
    make_directory("root/etc/scalyr-agent-2/agent.d")

    # Create the links to the appropriate commands in /usr/sbin and /etc/init.d/
    if create_initd_link:
        make_soft_link(
            "/usr/share/scalyr-agent-2/bin/scalyr-agent-2",
            "root/etc/init.d/scalyr-agent-2",
        )
    make_soft_link(
        "/usr/share/scalyr-agent-2/bin/scalyr-agent-2", "root/usr/sbin/scalyr-agent-2"
    )
    make_soft_link(
        "/usr/share/scalyr-agent-2/bin/scalyr-agent-2-config",
        "root/usr/sbin/scalyr-agent-2-config",
    )
    make_soft_link(
        "/usr/share/scalyr-agent-2/bin/scalyr-switch-python",
        "root/usr/sbin/scalyr-switch-python",
    )


def build_container_builder(
    variant,
    version,
    no_versioned_file_name,
    source_tarball,
    dockerfile,
    base_configs,
    image_name,
    image_repos,
    coverage_enabled=False,
):
    """Builds an executable script in the current working directory that will build the container image for the various
    Docker and Kubernetes targets.  This script embeds all assets it needs in it so it can be a standalone artifact.
    The script is based on `docker/scripts/container_builder_base.sh`.  See that script for information on it can
    be used.

    @param variant: If not None, will add the specified string into the final script name. This allows for different
        scripts to be built for the same type and same version.
    @param version: The agent version.
    @param no_versioned_file_name:  True if the version number should not be embedded in the script's file name.
    @param source_tarball:  The filename for the source tarball (including the `.tar.gz` extension) that will
        be built and then embedded in the artifact.  The contents of the Dockerfile will determine what this
        name should be.
    @param dockerfile:  The file path for the Dockerfile to embed in the script, relative to the top of the
        agent source directory.
    @param base_configs:  The file path for the configuration to use when building the container image, relative
        to the top of the agent source directory.  This allows for different `agent.json` and `agent.d` directories
        to be used for Kubernetes, docker, etc.
    @param image_name:  The name for the image that is being built.  Will be used for the artifact's name.
    @param image_repos:  A list of repositories that should be added as tags to the image once it is built.
        Each repository will have two tags added -- one for the specific agent version and one for `latest`.
    @param coverage_enabled: Path Dockerfile to run agent with enabled coverage.

    @return: The file name of the built artifact.
    """
    build_container_tarball(source_tarball, base_configs=base_configs)

    agent_source_root = __source_root__
    # Make a copy of the right Dockerfile to embed in the script.
    shutil.copy(make_path(agent_source_root, dockerfile), "Dockerfile")
    # copy requirements file with dependencies for docker builds.
    shutil.copy(
        make_path(agent_source_root, os.path.join("docker", "requirements.txt")),
        "requirements.txt",
    )

    if variant is None:
        version_string = version
    else:
        version_string = "%s.%s" % (version, variant)

    # Read the base builder script into memory
    base_fp = open(
        make_path(agent_source_root, "docker/scripts/container_builder_base.sh"), "r"
    )
    base_script = base_fp.read()
    base_fp.close()

    # The script has two lines defining environment variables (REPOSITORIES and TAGS) that we need to overwrite to
    # set them to what we want.  We'll just do some regex replace to do that.
    base_script = re.sub(
        r"\n.*OVERRIDE_REPOSITORIES.*\n",
        '\nREPOSITORIES="%s"\n' % ",".join(image_repos),
        base_script,
    )
    base_script = re.sub(
        r"\n.*OVERRIDE_TAGS.*\n",
        '\nTAGS="%s"\n' % "%s,latest" % version_string,
        base_script,
    )

    if no_versioned_file_name:
        output_name = image_name
    else:
        output_name = "%s-%s" % (image_name, version_string)

    # Tar it up but hold the tarfile in memory.  Note, if the source tarball really becomes massive, might have to
    # rethink this.
    tar_out = BytesIO()
    tar = tarfile.open("assets.tar.gz", "w|gz", tar_out)

    # if coverage enabled patch Dockerfile to install coverage package with pip.
    if coverage_enabled:
        with open("Dockerfile", "r") as file:
            data = file.read()
        new_dockerfile_source = re.sub(r"(RUN\spip\s.*)", r"\1 coverage==4.5.4", data)
        new_dockerfile_source = re.sub(
            r"CMD .*\n",
            'CMD ["coverage", "run", "--branch", "/usr/share/scalyr-agent-2/py/scalyr_agent/agent_main.py", '
            '"--no-fork", "--no-change-user", "start"]',
            new_dockerfile_source,
        )

        with open("Dockerfile", "w") as file:
            file.write(new_dockerfile_source)

    tar.add("Dockerfile")
    tar.add("requirements.txt")
    tar.add(source_tarball)
    tar.close()

    # Write one file that has the contents of the script followed by the contents of the tarfile.
    builder_fp = open(output_name, "wb")
    builder_fp.write(base_script.encode("utf-8"))
    builder_fp.write(tar_out.getvalue())
    builder_fp.close()

    # Make the script executable.
    st = os.stat(output_name)
    os.chmod(output_name, st.st_mode | stat.S_IEXEC | stat.S_IXGRP)

    return output_name


def build_container_tarball(tarball_name, base_configs=None):
    """Builds the scalyr-agent-2 tarball for either Docker or Kubernetes in the current working directory.

    @param tarball_name:  The name for the output tarball (including the `.tar.gz` extension)
    @param base_configs: The directory (relative to the top of the source tree) that contains the configuration
        files to copy (such as the agent.json and agent.d directory).  If None, then will use `config`.
    @type tarball_name: str
    @type base_configs: str

    @return: The file name of the built tarball.
    """
    build_common_docker_and_package_files(False, base_configs=base_configs)

    # Need to create some docker specific files
    make_directory("root/var/log/scalyr-agent-2/containers")

    # Tar it up.
    tar = tarfile.open(tarball_name, "w:gz")
    original_dir = os.getcwd()

    os.chdir("root")

    # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
    # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is mainly
    # Posix.
    for root, dirs, files in os.walk("."):
        to_copy = []
        for name in dirs:
            to_copy.append(os.path.join(root, name))
        for name in files:
            to_copy.append(os.path.join(root, name))

        for x in to_copy:
            file_entry = tar.gettarinfo(x)
            file_entry.uname = "root"
            file_entry.gname = "root"
            file_entry.uid = 0
            file_entry.gid = 0

            if file_entry.isreg():
                fp = open(file_entry.name, "rb")
                tar.addfile(file_entry, fp)
                fp.close()
            else:
                tar.addfile(file_entry)

    os.chdir(original_dir)

    tar.close()

    return tarball_name


def build_rpm_or_deb_package(is_rpm, variant, version):
    """Builds either an RPM or Debian package in the current working directory.

    @param is_rpm: True if an RPM should be built. Otherwise a Debian package will be built.
    @param variant: If not None, will add the specified string into the iteration identifier for the package. This
        allows for different packages to be built for the same type and same version.
    @param version: The agent version.

    @return: The file name of the built package.
    """
    build_common_docker_and_package_files(True)

    # Create the scriplets the RPM/Debian package invokes when uninstalling or upgrading.
    create_scriptlets()
    # Produce the change logs that we will embed in the package, based on the CHANGELOG.md in this directory.
    create_change_logs()

    if is_rpm:
        package_type = "rpm"
    else:
        package_type = "deb"

    # Only change the iteration label if we need to embed a variant.
    if variant is not None:
        iteration_arg = "--iteration 1.%s" % variant
    else:
        iteration_arg = ""

    description = (
        "Scalyr Agent 2 is the daemon process Scalyr customers run on their servers to collect metrics and "
        "log files and transmit them to Scalyr."
    )

    run_command(
        'fpm -s dir -a all -t %s -n "scalyr-agent-2" -v %s '
        '  --license "Apache 2.0" '
        "  --vendor Scalyr %s "
        "  --maintainer czerwin@scalyr.com "
        "  --provides scalyr-agent-2 "
        '  --description "%s" '
        '  --depends "bash >= 3.2" '
        "  --url https://www.scalyr.com "
        "  --deb-user root "
        "  --deb-group root "
        "  --deb-changelog changelog-deb "
        "  --rpm-user root "
        "  --rpm-group root "
        "  --rpm-changelog changelog-rpm"
        "  --before-install preinstall.sh "
        "  --after-install postinstall.sh "
        "  --before-remove preuninstall.sh "
        "  --deb-no-default-config-files "
        "  --no-deb-auto-config-files "
        "  --config-files /etc/scalyr-agent-2/agent.json "
        # NOTE: We leave those two files in place since they are symlinks which might have been
        # updated by scalyr-switch-python and we want to leave this in place - aka make sure
        # selected Python version is preserved on upgrade
        "  --config-files /usr/share/scalyr-agent-2/bin/scalyr-agent-2 "
        "  --config-files /usr/share/scalyr-agent-2/bin/scalyr-agent-2-config "
        "  --directories /usr/share/scalyr-agent-2 "
        "  --directories /var/lib/scalyr-agent-2 "
        "  --directories /var/log/scalyr-agent-2 "
        "  -C root usr etc var" % (package_type, version, iteration_arg, description),
        exit_on_fail=True,
        command_name="fpm",
    )

    # We determine the artifact name in a little bit of loose fashion.. we just glob over the current
    # directory looking for something either ending in .rpm or .deb.  There should only be one package,
    # so that is fine.
    if is_rpm:
        files = glob.glob("*.rpm")
    else:
        files = glob.glob("*.deb")

    if len(files) != 1:
        raise Exception(
            "Could not find resulting rpm or debian package in the build directory."
        )

    return files[0]


def build_tarball_package(variant, version, no_versioned_file_name):
    """Builds the scalyr-agent-2 tarball in the current working directory.

    @param variant: If not None, will add the specified string into the final tarball name. This allows for different
        tarballs to be built for the same type and same version.
    @param version: The agent version.
    @param no_versioned_file_name:  True if the version number should not be embedded in the artifact's file name.

    @return: The file name of the built tarball.
    """
    # Use build_base_files to build all of the important stuff in ./scalyr-agent-2
    build_base_files()

    # Build the rest of the directories required for the tarball install.  Mainly, the log and data directories
    # in the tarball itself where the running process will store its state.
    make_directory("scalyr-agent-2/data")
    make_directory("scalyr-agent-2/log")
    make_directory("scalyr-agent-2/config/agent.d")

    # Create a file named packageless.  This signals to the agent that
    # this a tarball install instead of an RPM/Debian install, which changes
    # the default paths for th econfig, logs, data, etc directories.  See
    # configuration.py.
    write_to_file("1", "scalyr-agent-2/packageless")

    if variant is None:
        base_archive_name = "scalyr-agent-%s" % version
    else:
        base_archive_name = "scalyr-agent-%s.%s" % (version, variant)

    shutil.move("scalyr-agent-2", base_archive_name)

    output_name = (
        "%s.tar.gz" % base_archive_name
        if not no_versioned_file_name
        else "scalyr-agent.tar.gz"
    )
    # Tar it up.
    tar = tarfile.open(output_name, "w:gz")
    tar.add(base_archive_name)
    tar.close()

    return output_name


def replace_shebang(path, new_path, new_shebang):
    # type: (six.text_type, six.text_type, six.text_type) ->None
    with open(path, "r") as f:
        with open(new_path, "w") as newf:
            # skip shebang
            f.readline()
            newf.write(new_shebang)
            newf.write("\n")
            newf.write(f.read())


def build_base_files(base_configs="config"):
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

    @param base_configs:  The directory (relative to the top of the source tree) that contains the configuration
        files to copy (such as the agent.json and agent.d directory).  If None, then will use `config`.
    """
    original_dir = os.getcwd()
    # This will return the parent directory of this file.  We will use that to determine the path
    # to files like scalyr_agent/ to copy the source files
    agent_source_root = __source_root__

    make_directory("scalyr-agent-2/py")
    os.chdir("scalyr-agent-2")

    make_directory("certs")
    make_directory("bin")
    make_directory("misc")

    # Copy the version file.  We copy it both to the root and the package root.  The package copy is done down below.
    shutil.copy(make_path(agent_source_root, "VERSION.txt"), "VERSION.txt")

    # Copy the source files.
    os.chdir("py")

    shutil.copytree(make_path(agent_source_root, "scalyr_agent"), "scalyr_agent")
    shutil.copytree(make_path(agent_source_root, "monitors"), "monitors")
    os.chdir("monitors")
    recursively_delete_files_by_name("README.md")
    os.chdir("..")
    shutil.copy(
        make_path(agent_source_root, "VERSION.txt"),
        os.path.join("scalyr_agent", "VERSION.txt"),
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

    # create copies of the config_main.py with python2 and python3 shebang.
    config_main_path = os.path.join(agent_source_root, "scalyr_agent", "config_main.py")
    config_main_py2_path = os.path.join("scalyr_agent", "config_main_py2.py")
    config_main_py3_path = os.path.join("scalyr_agent", "config_main_py3.py")
    replace_shebang(config_main_path, config_main_py2_path, "#!/usr/bin/env python2")
    replace_shebang(config_main_path, config_main_py3_path, "#!/usr/bin/env python3")
    config_permissions = os.stat(config_main_path).st_mode
    os.chmod(config_main_py2_path, config_permissions)
    os.chmod(config_main_py3_path, config_permissions)

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

    # Create symlinks for the two commands
    os.chdir("bin")

    make_soft_link("../py/scalyr_agent/agent_main.py", "scalyr-agent-2")
    make_soft_link("../py/scalyr_agent/config_main.py", "scalyr-agent-2-config")

    # add switch python version script.
    shutil.copy(
        os.path.join(
            agent_source_root, "installer", "scripts", "scalyr-switch-python.sh"
        ),
        "scalyr-switch-python",
    )

    os.chdir("..")

    write_to_file(get_build_info(), "build_info")

    os.chdir(original_dir)


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
    dest_fp = open(file_path, "w")
    dest_fp.write(string_value.rstrip())
    dest_fp.write(os.linesep)
    dest_fp.close()


def parse_date(date_str):
    """Parses a date time string of the format MMM DD, YYYY HH:MM +ZZZZ and returns seconds past epoch.

    Example of the format is: Oct 10, 2014 17:00 -0700

    @param date_str: A string containing the date and time in the format described above.

    @return: The number of seconds past epoch.

    @raise ValueError: if there is a parsing problem.
    """
    # For some reason, it was hard to parse this particular format with the existing Python libraries,
    # especially when the timezone was not the same as the local time zone.  So, we have to do this the
    # sort of hard way.
    #
    # It is a little annoying that strptime only takes Sep for September and not Sep which is more common
    # in US-eng, so we cheat here and just swap it out.
    adjusted = date_str.replace("Sept", "Sep")

    # Find the timezone string at the end of the string.
    if re.search(r"[\-+]\d\d\d\d$", adjusted) is None:
        raise ValueError(
            "Value '%s' does not meet required time format of 'MMM DD, YYYY HH:MM +ZZZZ' (or "
            "as an example, ' 'Oct 10, 2014 17:00 -0700'" % date_str
        )

    # Use the existing Python string parsing calls to just parse the time and date.  We will handle the timezone
    # separately.
    try:
        base_time = time.mktime(time.strptime(adjusted[0:-6], "%b %d, %Y %H:%M"))
    except ValueError:
        raise ValueError(
            "Value '%s' does not meet required time format of 'MMM DD, YYYY HH:MM +ZZZZ' (or "
            "as an example, ' 'Oct 10, 2014 17:00 -0700'" % date_str
        )

    # Since mktime assumes the time is in localtime, we might have a different time zone
    # in tz_str, we must manually added in the difference.
    # First, convert -0700 to seconds.. the second two digits are the number of hours
    # and the last two are the minute of minutes.
    tz_str = adjusted[-5:]
    tz_offset_secs = int(tz_str[1:3]) * 3600 + int(tz_str[3:5]) * 60

    if tz_str.startswith("-"):
        tz_offset_secs *= -1

    # Determine the offset for the local timezone.
    if time.daylight:
        local_offset_secs = -1 * time.altzone
    else:
        local_offset_secs = -1 * time.timezone

    base_time += local_offset_secs - tz_offset_secs
    return base_time


# TODO:  This code is shared with config_main.py.  We should move this into a common
# utility location both commands can import it from.
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
    output_file = tempfile.mktemp()
    output_fp = open(output_file, "w")

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
                    % (command_name, return_code,),
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

        if isinstance(output_str, six.binary_type):
            # Ensure we return unicode type
            output_str = output_str.decode("utf-8")

        return return_code, output_str

    finally:
        # Be sure to close the temporary file and delete it.
        output_fp.close()
        os.unlink(output_file)


def create_scriptlets():
    """Copy three scriptlets required by the RPM and Debian package to the current working directory.

    These are the preinstall.sh, preuninstall.sh, and postuninstall.sh scripts.
    """

    scripts_path = os.path.join(__source_root__, "installer", "scripts")

    shutil.copy(os.path.join(scripts_path, "preinstall.sh"), "preinstall.sh")
    shutil.copy(os.path.join(scripts_path, "preuninstall.sh"), "preuninstall.sh")
    shutil.copy(os.path.join(scripts_path, "postinstall.sh"), "postinstall.sh")


def create_change_logs():
    """Creates the necessary change logs for both RPM and Debian based on CHANGELOG.md.

    Creates two files in the current working directory named 'changelog-rpm' and 'changelog-deb'.  They
    will have the same content as CHANGELOG.md but formatted by the respective standards for the different
    packaging systems.
    """
    # We define a helper function named print_release_notes that is used down below.
    def print_release_notes(output_fp, notes, level_prefixes, level=0):
        """Emits the notes for a single release to output_fp.

        @param output_fp: The file to write the notes to
        @param notes: An array of strings containing the notes for the release. Some elements may be lists of strings
            themselves to represent sublists. Only three levels of nested lists are allowed. This is the same format
            returned by parse_change_log() method.
        @param level_prefixes: The prefix to use for each of the three levels of notes.
        @param level: The current level in the notes.
        """
        prefix = level_prefixes[level]
        for note in notes:
            if isinstance(note, list):
                # If a sublist, then recursively call this function, increasing the level.
                print_release_notes(output_fp, note, level_prefixes, level + 1)
                if level == 0:
                    print(file=output_fp)
            else:
                # Otherwise emit the note with the prefix for this level.
                print("%s%s" % (prefix, note), file=output_fp)

    # Handle the RPM log first.  We parse CHANGELOG.md and then emit the notes in the expected format.
    fp = open("changelog-rpm", "w")
    try:
        for release in parse_change_log():
            date_str = time.strftime("%a %b %d %Y", time.localtime(release["time"]))

            # RPM expects the leading line for a relesae to start with an asterisk, then have
            # the name of the person doing the release, their e-mail and then the version.
            print(
                "* %s %s <%s> %s"
                % (
                    date_str,
                    release["packager"],
                    release["packager_email"],
                    release["version"],
                ),
                file=fp,
            )
            print(file=fp)
            print("Release: %s (%s)" % (release["version"], release["name"]), file=fp)
            print(file=fp)
            # Include the release notes, with the first level with no indent, an asterisk for the second level
            # and a dash for the third.
            print_release_notes(fp, release["notes"], ["", " * ", "   - "])
            print(file=fp)
    finally:
        fp.close()

    # Next, create the Debian change log.
    fp = open("changelog-deb", "w")
    try:
        for release in parse_change_log():
            # Debian expects a leading line that starts with the package, including the version, the distribution
            # urgency.  Then, anything goes until the last line for the release, which begins with two dashes.
            date_str = time.strftime(
                "%a, %d %b %Y %H:%M:%S %z", time.localtime(release["time"])
            )
            print(
                "scalyr-agent-2 (%s) stable; urgency=low" % release["version"], file=fp
            )
            # Include release notes with an indented first level (using asterisk, then a dash for the next level,
            # finally a plus sign.
            print_release_notes(fp, release["notes"], [" * ", "   - ", "     + "])
            print(
                "-- %s <%s>  %s"
                % (release["packager"], release["packager_email"], date_str,),
                file=fp,
            )
    finally:
        fp.close()


def parse_change_log():
    """Parses the contents of CHANGELOG.md and returns the content in a structured way.

    @return: A list of dicts, one for each release in CHANGELOG.md.  Each release dict will have with several fields:
            name:  The name of the release
            version:  The version of the release
            packager:  The name of the packager, such as 'Steven Czerwinski'
            packager_email:  The email for the packager
            time:  The seconds past epoch when the package was created
            notes:  A list of strings or lists representing the notes for the release.  The list may
                have elements that are strings (for a single line of notes) or lists (for a nested list under
                the last string element).  Only three levels of nesting are allowed.
    """
    # Some regular expressions matching what we expect to see in CHANGELOG.md.
    # Each release section should start with a '##' line for major header.
    release_matcher = re.compile(r'## ([\d\._]+) "(.*)"')
    # The expected pattern we will include in a HTML comment to give information on the packager.
    packaged_matcher = re.compile(
        r"Packaged by (.*) <(.*)> on (\w+ \d+, \d+ \d+:\d\d [+-]\d\d\d\d)"
    )

    # Listed below are the deliminators we use to extract the structure from the changelog release
    # sections.  We fix our markdown syntax to make it easier for us.
    #
    # Our change log will look something like this:
    #
    # ## 2.0.1 "Aggravated Aardvark"
    #
    # New core features:
    # * Blah blah
    # * Blah Blah
    #   - sub point
    #
    # Bug fixes:
    # * Blah Blah

    # The deliminators, each level is marked by what pattern we should see in the next line to either
    # go up a level, go down a level, or confirm it is at the same level.
    section_delims = [
        # First level does not have any prefix.. just plain text.
        # So, the level up is the release header, which begins with '##'
        # The level down is ' *'.
        {
            "up": re.compile("## "),
            "down": re.compile(r"\* "),
            "same": re.compile(r"[^\s\*\-#]"),
            "prefix": "",
        },
        # Second level always begins with an asterisk.
        {
            "up": re.compile(r"[^\s\*\-#]"),
            "down": re.compile("    - "),
            "same": re.compile(r"\* "),
            "prefix": "* ",
        },
        # Third level always begins with '  -'
        {
            "up": re.compile(r"\* "),
            "down": None,
            "same": re.compile("    - "),
            "prefix": "    - ",
        },
    ]

    # Helper function.
    def read_section(lines, level=0):
        """Transforms the lines representing the notes for a single release into the desired nested representation.

        @param lines: The lines for the notes for a release including markup. NOTE, this list must be in reverse order,
            where the next line to be scanned is the last line in the list.
        @param level: The nesting level that these lines are at.

        @return: A list containing the notes, with nested lists as appropriate.
        """
        result = []

        if len(lines) == 0:
            return result

        while len(lines) > 0:
            # Go over each line, seeing based on its content, if we should go up a nesting level, down a level,
            # or just stay at the same level.
            my_line = lines.pop()

            # If the next line is at our same level, then just add it to our current list and continue.
            if section_delims[level]["same"].match(my_line) is not None:
                result.append(my_line[len(section_delims[level]["prefix"]) :])
                continue

            # For all other cases, someone else is going to have to look at this line, so add it back to the list.
            lines.append(my_line)

            # If the next line looks like it belongs any previous nesting levels, then we must have exited out of
            # our current nesting level, so just return what we have gathered for this sublist.
            for i in range(level + 1):
                if section_delims[i]["up"].match(my_line) is not None:
                    return result
            if (
                section_delims[level]["down"] is not None
                and section_delims[level]["down"].match(my_line) is not None
            ):
                # Otherwise, it looks like the next line belongs to a sublist.  Recursively call ourselves, going
                # down a level in nesting.
                result.append(read_section(lines, level + 1))
            else:
                raise BadChangeLogFormat(
                    "Release not line did not match expect format at level %d: %s"
                    % (level, my_line)
                )
        return result

    # Begin the real work here.  Read the change log.
    change_log_fp = open(os.path.join(__source_root__, "CHANGELOG.md"), "r")

    try:
        # Skip over the first two lines since it should be header.
        change_log_fp.readline()
        change_log_fp.readline()

        # Read over all the lines, eliminating the comment lines and other useless things.  Also strip out all newlines.
        content = []
        in_comment = False
        for line in change_log_fp:
            line = line.rstrip()
            if len(line) == 0:
                continue

            # Check for a comment.. either beginning or closing.
            if line == "<!---":
                in_comment = True
            elif line == "--->":
                in_comment = False
            elif packaged_matcher.match(line) is not None:
                # The only thing we will pay attention to while in a comment is our packaged line.  If we see it,
                # grab it.
                content.append(line)
            elif not in_comment:
                # Keep any non-comments.
                content.append(line)

        change_log_fp.close()
        change_log_fp = None
    finally:
        if change_log_fp is not None:
            change_log_fp.close()

    # We reverse the content list so the first lines to be read are at the end.  This way we can use pop down below.
    content.reverse()

    # The list of release objects
    releases = []

    # The rest of the log should just contain release notes for each release.  Iterate over the content,
    # reading out the release notes for each release.
    while len(content) > 0:
        # Each release must begin with at least two lines -- one for the release name and then one for the
        # 'Packaged by Steven Czerwinski on... ' line that we pulled out of the HTML comment.
        if len(content) < 2:
            raise BadChangeLogFormat(
                "New release section does not contain at least two lines."
            )

        # Extract the information from each of those two lines.
        current_line = content.pop()
        release_version_name = release_matcher.match(current_line)
        if release_version_name is None:
            raise BadChangeLogFormat(
                "Header line for release did not match expected format: %s"
                % current_line
            )

        current_line = content.pop()
        packager_info = packaged_matcher.match(current_line)
        if packager_info is None:
            raise BadChangeLogFormat(
                "Packager line for release did not match expected format: %s"
                % current_line
            )

        # Read the section notes until we hit a '##' line.
        release_notes = read_section(content)

        try:
            time_value = parse_date(packager_info.group(3))
        except ValueError as err:
            message = getattr(err, "message", str(err))
            raise BadChangeLogFormat(message)

        releases.append(
            {
                "name": release_version_name.group(2),
                "version": release_version_name.group(1),
                "packager": packager_info.group(1),
                "packager_email": packager_info.group(2),
                "time": time_value,
                "notes": release_notes,
            }
        )

    return releases


# A string containing the build info for this build, to be placed in the 'build_info' file.
__build_info__ = None


def get_build_info():
    """Returns a string containing the build info."""
    global __build_info__
    if __build_info__ is not None:
        return __build_info__

    build_info_buffer = StringIO()
    original_dir = os.getcwd()

    try:
        # We need to execute the git command in the source root.
        os.chdir(__source_root__)
        # Add in the e-mail address of the user building it.
        (rc, packager_email) = run_command(
            "git config user.email", fail_quietly=True, command_name="git"
        )
        if rc != 0:
            packager_email = u"unknown"

        print("Packaged by: %s" % packager_email.strip(), file=build_info_buffer)

        # Determine the last commit from the log.
        (_, commit_id) = run_command(
            "git log --summary -1 | head -n 1 | cut -d ' ' -f 2",
            exit_on_fail=True,
            command_name="git",
        )
        print("Latest commit: %s" % commit_id.strip(), file=build_info_buffer)

        # Include the branch just for safety sake.
        (_, branch) = run_command(
            "git branch | cut -d ' ' -f 2", exit_on_fail=True, command_name="git"
        )
        print("From branch: %s" % branch.strip(), file=build_info_buffer)

        # Add a timestamp.
        print(
            "Build time: %s"
            % six.text_type(strftime("%Y-%m-%d %H:%M:%S UTC", gmtime())),
            file=build_info_buffer,
        )

        __build_info__ = build_info_buffer.getvalue()
        return __build_info__
    finally:
        os.chdir(original_dir)

        if build_info_buffer is not None:
            build_info_buffer.close()


def set_build_info(build_info_file_path):
    """Sets the file to use as the build_info file to include in the package.

    If this is called, then future calls to get_build_info will return the contents of this file
    and will not use other commands such as 'git' to try to create it on its own.

    This is useful when you are running trying create a package on a system that does not have full access
    to git.

    @param build_info_file_path: The path to the build_info file to use.
    """
    global __build_info__
    fp = open(build_info_file_path, "r")
    __build_info__ = fp.read()
    fp.close()

    return __build_info__


class BadChangeLogFormat(Exception):
    pass


if __name__ == "__main__":
    parser = OptionParser(
        usage="Usage: python build_package.py [options] %s" % "|".join(PACKAGE_TYPES)
    )
    parser.add_option(
        "-v",
        "--variant",
        dest="variant",
        default=None,
        help="An optional string that is included in the package name to identify a variant "
        "of the main release created by a different packager.  "
        "Most users do not need to use this option.",
    )
    parser.add_option(
        "",
        "--only-create-build-info",
        action="store_true",
        dest="build_info_only",
        default=False,
        help="If true, will only create the build_info file and exit.  This can be used in conjunction "
        "with the --set-build-info option to create the build_info file on one host and then build the "
        "rest of the package on another.  This is useful when the final host does not have full access "
        "to git",
    )

    parser.add_option(
        "",
        "--no-versioned-file-name",
        action="store_true",
        dest="no_versioned_file_name",
        default=False,
        help="If true, will not embed the version number in the artifact's file name.  This only "
        "applies to the `tarball` and container builders artifacts.",
    )

    parser.add_option(
        "",
        "--set-build-info",
        dest="build_info",
        default=None,
        help="The path to the build_info file to include in the final package.  If this is used, "
        "this process will not invoke commands such as git in order to compute the build information "
        "itself.  The file should be one built by a previous run of this script.",
    )

    parser.add_option(
        "",
        "--coverage",
        dest="coverage",
        action="store_true",
        default=False,
        help="Enable coverage analysis. Can be used in smoketests. Only works with docker/k8s.",
    )

    (options, args) = parser.parse_args()
    # If we are just suppose to create the build_info, then do it and exit.  We do not bother to check to see
    # if they specified a package.
    if options.build_info_only:
        write_to_file(get_build_info(), "build_info")
        print("Built build_info")
        sys.exit(0)

    if len(args) < 1:
        print(
            "You must specify the package you wish to build, one of the following: %s."
            % ", ".join(PACKAGE_TYPES),
            file=sys.stderr,
        )
        parser.print_help(sys.stderr)
        sys.exit(1)
    elif len(args) > 1:
        print("You may only specify one package to build.", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(1)
    elif args[0] not in PACKAGE_TYPES:
        print('Unknown package type given: "%s"' % args[0], file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(1)

    if options.build_info is not None:
        set_build_info(options.build_info)

    artifact = build_package(
        args[0], options.variant, options.no_versioned_file_name, options.coverage,
    )
    print("Built %s" % artifact)
    sys.exit(0)
