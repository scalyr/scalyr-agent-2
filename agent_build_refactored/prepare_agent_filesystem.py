# Copyright 2014-2022 Scalyr Inc.
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

"""
This module contains function that responsible for building of the content of the packages.
"""

import json
import platform
import pathlib as pl
import shutil
import re
import os
import subprocess
import time
from typing import Union, List

from agent_build_refactored.tools.constants import SOURCE_ROOT, AGENT_BUILD_PATH


def recursively_delete_dirs_by_name(root_dir: Union[str, pl.Path], *dir_names: str):
    """
    Deletes any directories that are in the current working directory or any of its children whose file names
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
    for root, dirs, files in os.walk(root_dir):
        # Examine all directories at this level, see if any get a match
        for dir_path in dirs:
            for matcher in matchers:
                if matcher.match(dir_path):
                    shutil.rmtree(os.path.join(root, dir_path))
                    # Also, remove it from dirs so that we don't try to walk down it.
                    dirs.remove(dir_path)
                    break


def recursively_delete_files_by_name(
    dir_path: Union[str, pl.Path], *file_names: Union[str, pl.Path]
):
    """Deletes any files that are in the current working directory or any of its children whose file names
    match the specified regular expressions.

    This will recursively examine all children of the current working directory.

    @param file_names: A variable number of strings containing regular expressions that should match the file names of
        the files that should be deleted.
    """
    # Compile the strings into actual regular expression match objects.
    matchers = []
    for file_name in file_names:
        matchers.append(re.compile(str(file_name)))

    # Walk down the current directory.
    for root, dirs, files in os.walk(dir_path.absolute()):
        # See if any of the files at this level match any of the matchers.
        for file_path in files:
            for matcher in matchers:
                if matcher.match(file_path):
                    # Delete it if it did match.
                    os.unlink(os.path.join(root, file_path))
                    break


def cat_files(file_paths, destination, convert_newlines=False):
    """Concatenates the contents of the specified files and writes it to a new file at destination.

    @param file_paths: A list of paths for the files that should be read. The concatenating will be done in the same
        order as the list.
    @param destination: The path of the file to write the contents to.
    @param convert_newlines: If True, the final file will use Windows newlines (i.e., CR LF).
    """
    with pl.Path(destination).open("w") as dest_fp:
        for file_path in file_paths:
            with pl.Path(file_path).open("r") as in_fp:
                for line in in_fp:
                    if convert_newlines:
                        line.replace("\n", "\r\n")
                    dest_fp.write(line)


def _add_certs(
    path: Union[str, pl.Path], intermediate_certs=True, copy_other_certs=True
):
    """
    Create needed certificates files in the specified path.
    """

    path = pl.Path(path)
    path.mkdir(parents=True)
    source_certs_path = SOURCE_ROOT / "certs"

    cat_files(source_certs_path.glob("*_root.pem"), path / "ca_certs.crt")

    if intermediate_certs:
        cat_files(
            source_certs_path.glob("*_intermediate.pem"),
            path / "intermediate_certs.pem",
        )
    if copy_other_certs:
        for cert_file in source_certs_path.glob("*.pem"):
            shutil.copy(cert_file, path / cert_file.name)


def add_config(
    base_config_source_path: Union[str, pl.Path],
    output_path: Union[str, pl.Path],
    additional_config_paths: List[pl.Path] = None,
):
    """
    Copy config folder from the specified path to the target path.
    :param base_config_source_path: Path to the base config directory to copy.
    :param additional_config_paths: List of paths to config directories to copy to the result config directory.
        New files are places along with files from the 'base_config_source_path' or overwrite them.
    """
    base_config_source_path = pl.Path(base_config_source_path)
    output_path = pl.Path(output_path)
    # Copy config
    shutil.copytree(base_config_source_path, output_path)

    # Copy additional config files.
    for a_config_path in additional_config_paths or []:
        # pylint: disable=unexpected-keyword-arg
        shutil.copytree(
            a_config_path,
            output_path,
            dirs_exist_ok=True,
        )
        # pylint: enable=unexpected-keyword-arg

    # Make sure config file has 640 permissions
    config_file_path = output_path / "agent.json"
    config_file_path.chmod(int("640", 8))

    # Make sure there is an agent.d directory regardless of the config directory we used.
    agent_d_path = output_path / "agent.d"
    agent_d_path.mkdir(exist_ok=True)
    # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
    # readable by others.
    agent_d_path.chmod(int("751", 8))

    # Also iterate through all files in the agent.d and set appropriate permissions.
    for child_path in agent_d_path.iterdir():
        if child_path.is_file():
            child_path.chmod(int("640", 8))


def get_build_info():
    """Returns a dict containing the package build info."""

    build_info = {}

    original_dir = os.getcwd()

    try:
        # We need to execute the git command in the source root.
        os.chdir(SOURCE_ROOT)
        # Add in the e-mail address of the user building it.
        try:
            packager_email = (
                subprocess.check_output("git config user.email", shell=True)
                .decode()
                .strip()
            )
        except subprocess.CalledProcessError:
            packager_email = "unknown"

        build_info["packaged_by"] = packager_email

        # Determine the last commit from the log.
        commit_id = (
            subprocess.check_output(
                "git log --summary -1 | head -n 1 | cut -d ' ' -f 2", shell=True
            )
            .decode()
            .strip()
        )

        build_info["latest_commit"] = commit_id

        # Include the branch just for safety sake.
        branch = (
            subprocess.check_output("git branch | cut -d ' ' -f 2", shell=True)
            .decode()
            .strip()
        )
        build_info["from_branch"] = branch

        # Add a timestamp.
        build_info["build_time"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        return build_info
    finally:
        os.chdir(original_dir)


def get_install_info(install_type: str) -> dict:
    """
    Get dict with installation info.
    """
    return {"build_info": get_build_info(), "install_type": install_type}


def build_agent_base_files(
    output_path: pl.Path,
    install_type: str,
    version: str = None,
    frozen_binary_path: pl.Path = None,
    copy_agent_source: bool = False,
):
    """
    Create directory with agent's core files.
    :param output_path: Output path for the root of the agent's base files.
    :param install_type: String with install type of the future package.
        See 'install_info' in scalyr_agent/__scalyr__.py module.
    :param version: Version string to assign to the future package, uses version from the VERSION file if None.
    :param frozen_binary_path: Path to frozen binaries, if specified, then those binaries will be used in the
        'bin' folder. Excludes 'copy_agent_source'.
    :param copy_agent_source: If True, then agent's source code is also copied into the '<output_path>/py' directory.
        In opposite, it is expected that a frozen binaries will be placed instead of source code later.
    """
    if output_path.exists():
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True)

    # Copy the monitors directory.
    monitors_path = output_path / "monitors"
    shutil.copytree(SOURCE_ROOT / "monitors", monitors_path)
    recursively_delete_files_by_name(output_path / monitors_path, "README.md")

    # Add VERSION file.
    result_version_path = output_path / "VERSION"
    if version:
        result_version_path.write_text(version)
    else:
        shutil.copy2(SOURCE_ROOT / "VERSION", output_path / "VERSION")

    # Create bin directory with executables.
    bin_path = output_path / "bin"

    if frozen_binary_path:
        shutil.copytree(frozen_binary_path / ".", bin_path)

    elif copy_agent_source:
        bin_path.mkdir()
        source_code_path = output_path / "py"

        shutil.copytree(SOURCE_ROOT / "scalyr_agent", source_code_path / "scalyr_agent")

        agent_main_executable_path = bin_path / "scalyr-agent-2"
        agent_main_executable_path.symlink_to(
            pl.Path("..", "py", "scalyr_agent", "agent_main.py")
        )

        # Copy wrapper script for removed 'scalyr-agent-2-config' executable for backward compatibility.
        shutil.copy2(
            AGENT_BUILD_PATH / "linux/scalyr-agent-2-config",
            bin_path,
        )

        # Write install_info file inside the "scalyr_agent" package.
        install_info_path = source_code_path / "scalyr_agent" / "install_info.json"

        install_info = get_install_info(install_type=install_type)
        install_info_path.write_text(json.dumps(install_info))

        # Don't include the tests directories.  Also, don't include the .idea directory created by IDE.
        recursively_delete_dirs_by_name(
            source_code_path, r"\.idea", "tests", "__pycache__"
        )
        recursively_delete_files_by_name(
            source_code_path,
            r".*\.pyc",
            r".*\.pyo",
            r".*\.pyd",
            r"all_tests\.py",
            r".*~",
        )


def build_linux_agent_files(
    output_path: pl.Path,
    install_type: str,
    version: str = None,
    frozen_binary_path: pl.Path = None,
    copy_agent_source: bool = False,
):
    """
    Extend agent core files with files that are common for all Linux based distributions.
    :param output_path: Output path for the root of the agent's base files.
    :param install_type: String with install type of the future package.
        See 'install_info' in scalyr_agent/__scalyr__.py module.
    :param version: Version string to assign to the future package, uses version from the VERSION file if None.
    :param frozen_binary_path: Path to frozen binaries, if specified, then those binaries will be used in the
        'bin' folder. Excludes 'copy_agent_source'.
    :param copy_agent_source: If True, then agent's source code is also copied into the '<output_path>/py' directory.
        In opposite, it is expected that a frozen binaries will be placed instead of source code later.
    """

    build_agent_base_files(
        output_path=output_path,
        install_type=install_type,
        version=version,
        frozen_binary_path=frozen_binary_path,
        copy_agent_source=copy_agent_source,
    )

    # Add certificates.
    certs_path = output_path / "certs"
    _add_certs(certs_path)

    # Misc extra files needed for some features.
    # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.
    # We put it in all distributions (not just the docker_tarball) in case a customer creates an image
    # using a package.
    misc_path = output_path / "misc"
    misc_path.mkdir()
    for f in ["Dockerfile.custom_agent_config", "Dockerfile.custom_k8s_config"]:
        shutil.copy2(SOURCE_ROOT / "docker" / f, misc_path / f)


def build_linux_fhs_agent_files(
    output_path: pl.Path,
    version: str = None,
    frozen_binary_path: pl.Path = None,
    copy_agent_source: bool = False,
):
    """
    Adapt agent's Linux based files for FHS based packages such DEB,RPM or for the filesystems for our docker images.
        In opposite, it is expected that a frozen binaries will be placed instead of source code later.
    :param output_path: Output path for the root of the agent's base files.
    :param version: Version string to assign to the future package, uses version from the VERSION file if None.
    :param frozen_binary_path: Path to frozen binaries, if specified, then those binaries will be used in the
        'bin' folder. Excludes 'copy_agent_source'.
    :param copy_agent_source: If True, then agent's source code is also copied into the '<output_path>/py' directory.
    """
    agent_install_root = output_path / "usr/share/scalyr-agent-2"
    build_linux_agent_files(
        output_path=agent_install_root,
        install_type="package",
        version=version,
        frozen_binary_path=frozen_binary_path,
        copy_agent_source=copy_agent_source,
    )

    pl.Path(output_path, "var/log/scalyr-agent-2").mkdir(parents=True)
    pl.Path(output_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

    usr_sbin_path = output_path / "usr/sbin"
    usr_sbin_path.mkdir(parents=True)

    agent_frozen_binary_filename = "scalyr-agent-2"
    if platform.system().lower().startswith("win"):
        agent_frozen_binary_filename = f"{agent_frozen_binary_filename}.exe"

    agent_binary_symlink_path = output_path / "usr/sbin" / agent_frozen_binary_filename
    frozen_binary_symlink_target_path = pl.Path(
        "..", "share", "scalyr-agent-2", "bin", agent_frozen_binary_filename
    )
    agent_binary_symlink_path.symlink_to(frozen_binary_symlink_target_path)

    scalyr_agent_config_symlink_path = (
        output_path / "usr/sbin" / "scalyr-agent-2-config"
    )
    scalyr_agent_config_symlink_target_path = pl.Path(
        "..", "share", "scalyr-agent-2", "bin", "scalyr-agent-2-config"
    )
    scalyr_agent_config_symlink_path.symlink_to(scalyr_agent_config_symlink_target_path)


class BadChangeLogFormat(Exception):
    pass


def create_change_logs(output_dir: pl.Path):
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
                    print("", file=output_fp)
            else:
                # Otherwise emit the note with the prefix for this level.
                print("%s%s" % (prefix, note), file=output_fp)

    # Handle the RPM log first.  We parse CHANGELOG.md and then emit the notes in the expected format.
    fp = open(output_dir / "changelog-rpm", "w")
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
            print("", file=fp)
            print("Release: %s (%s)" % (release["version"], release["name"]), file=fp)
            print("", file=fp)
            # Include the release notes, with the first level with no indent, an asterisk for the second level
            # and a dash for the third.
            print_release_notes(fp, release["notes"], ["", " * ", "   - "])
            print("", file=fp)
    finally:
        fp.close()

    # Next, create the Debian change log.
    fp = open(output_dir / "changelog-deb", "w")
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
            print_release_notes(fp, release["notes"], ["  * ", "   - ", "     + "])
            print(
                " -- %s <%s>  %s"
                % (
                    release["packager"],
                    release["packager_email"],
                    date_str,
                ),
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
    change_log_fp = open(os.path.join(SOURCE_ROOT, "CHANGELOG.md"), "r")

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
