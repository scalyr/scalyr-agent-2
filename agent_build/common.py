# Copyright 2014-2021 Scalyr Inc.
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
import os
import pathlib as pl
import re
import shlex
import sys
import time
import shutil
from typing import Union

__SOURCE_ROOT__ = pl.Path(__file__).parent.parent


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


def recursively_delete_dirs_by_name(
        root_dir: Union[str, pl.Path], *dir_names: str
):
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


class BadChangeLogFormat(Exception):
    pass


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
    change_log_fp = open(os.path.join(__SOURCE_ROOT__, "CHANGELOG.md"), "r")

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


# Implement shlex.join for Python < 3.8
if sys.version_info < (3, 8):

    def shlex_join(split_command):
        return " ".join(shlex.quote(arg) for arg in split_command)


else:
    shlex_join = shlex.join
