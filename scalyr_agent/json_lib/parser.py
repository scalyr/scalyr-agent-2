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
# Contains abstractions for parsing Json.  These abstractions
# implement custom Scalyr extensions.
#
# author: Steven Czerwinski <czerwin@scalyr.com>
from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"

import six
from six import unichr
from six.moves import range

from scalyr_agent.json_lib import JsonArray, JsonObject, JsonParseException


class TextScanner(object):
    """Allows for iterating over a unicode input.

    TextScanner wraps an incoming unicode string of input and provides
    methods to iterate over the characters.  It also provides methods to
    perform typical conversions.
    """

    def __init__(self, string_input, start_pos=0, max_pos=None):
        """Construct a new instance of a TextScanner.

        @param string_input: The input to scan. This must be unicode.
        @param start_pos: The index within input to begin the scan.
        @param max_pos: The index to at which to consider the scan is finished. If none is given, then the length of
            input is used.

        @return: The new instance."""
        self.__buffer = list(string_input)
        self.__pos = start_pos
        self.__start_pos = start_pos
        self.__max_pos = len(string_input)
        if max_pos is not None:
            self.__max_pos = max_pos

    @property
    def at_end(self):
        """True if the scanner is at the end of the character input."""
        return self.__pos >= self.__max_pos

    @property
    def position(self):
        """The position of the scan relative to original string.

        Notes, if this object does not offset the position by any start_pos
        used in the construction.  It is relative to the underlying string
        not the subrange.
        TODO:  This is a bit of a strange contract, but maintaining it since
        that is how the Scalyr Java classes behave as well."""
        return self.__pos

    @property
    def line_number(self):
        """Return the line number for the current position of the scan."""
        return self.line_number_for_offset(0)

    def line_number_for_offset(self, offset):
        """The line number of a position relative to the current position.

        @param offset: Offset to the current position for which to determine the line position. It may be negative.

        @return: The line number for the specified position.

        @raise IndexError: If the offset places the position outside of the valid range for the underlying character
            range."""
        line_num = 1
        target_pos = self.__pos + offset
        x = self.__start_pos

        self.__check_index(target_pos)

        while x < target_pos:
            b = self.__buffer[x]
            x += 1
            if b == "\n":
                line_num += 1
            elif b == "\r":
                line_num += 1
                # If this CR is the first half of a CRLF sequence,
                # skip the LF; otherwise we'd double-count CRLF line breaks.
                if x < target_pos and self.__buffer[x] == "\n":
                    x += 1
        return line_num

    @property
    def characters_remaining(self):
        """The number of characters that may be read before the end is reached."""
        return self.__max_pos - self.__pos

    def read_uchar(self):
        """Returns the next character from the buffer.

        @raise IndexError: If the scanner is already at the end of the buffer."""
        self.__check_read_size(1)
        self.__pos += 1
        return self.__buffer[self.__pos - 1]

    def read_uchars(self, length):
        """Returns the next length characters from the buffer.

        @raise IndexError: If the end of the buffer would be reached before length characters are read. In this case, the
            buffer is not advanced."""
        self.__check_read_size(length)
        my_slice = self.__buffer[self.__pos : self.__pos + length]
        self.__pos += length
        return "".join(my_slice)

    def peek_next_uchar(self, offset=0, none_if_bad_index=False):
        """Returns the next character that will be returned when read_uchar is
        invoked.

        @param offset: Optional argument to allow peeking at not just the next character but characters beyond that as well. A
            value of 0 references the next character, while 1 is the one after that, etc. You may specify negative indexes,
            which access the previous characters returned by read_uchar, -1 for the last, etc.
        @param none_if_bad_index: If the index that will be read is outside of the range of the underlying buffer, None
            will be returned instead of raising an exception.

        @raise IndexError: If the position that will be examined is outside of the range for the underlying buffer."""
        index = self.__pos + offset
        if not none_if_bad_index:
            self.__check_index(index)
        elif index < self.__start_pos or index >= self.__max_pos:
            return None
        return self.__buffer[index]

    def advance_position(self, increment):
        """Advances the scanner to the specified position, as long it is in the current buffer's range or the end of
        the buffer.
        @param increment: The amount to advance the position by.
        @type increment: int
        """
        index = self.__pos + increment
        if index < self.__start_pos or index > self.__max_pos:
            raise IndexError(
                "Index out of range for buffer (index %i, limit %i to %i)"
                % (index, self.__start_pos, self.__max_pos)
            )
        self.__pos = index

    def __check_read_size(self, read_length):
        index = self.__pos + read_length - 1
        if index < self.__start_pos or index >= self.__max_pos:
            raise IndexError(
                "Ran off end of buffer (position %i, limit %i, reading %i characters)"
                % (self.__pos, self.__max_pos, read_length)
            )

    def __check_index(self, index):
        if index < self.__start_pos or index >= self.__max_pos:
            raise IndexError(
                "Index out of range for buffer (index %i, limit %i to %i)"
                % (index, self.__start_pos, self.__max_pos)
            )


class JsonParser(object):
    """Parses text input into JsonObjects and supports Scalyr's extensions.

    JsonParser is the main abstraction for parsing text input
    into JsonObject and other related objects.  It also supports Scalyr's
    extensions to the Json format, including comments and binary data.
    Specifically, the following are allowed:

     - // and /* comments
     - Concatenation of string literals using '+'
     - Unquoted identifiers can be used as field names in an object literal
     - Not requiring commas between array elements and object fields

     - TODO:  support `b (backtick-b) binary data format used by Scalyr
       servers.
    """

    def __init__(
        self, input_scanner, allow_missing_commas=True, check_duplicate_keys=False
    ):
        """Initializes JsonParser for the specified input."""
        self.__scanner = input_scanner
        self.allow_missing_commas = allow_missing_commas
        self.check_duplicate_keys = check_duplicate_keys

    @staticmethod
    def parse(input_text, check_duplicate_keys=False):
        """
        Parse json string (unicode or valid UTF-8 bytes)
        :param input_text:
        :param check_duplicate_keys:
        :type input_text: six.text_type | six.binary_type
        :type check_duplicate_keys: bool
        """
        input_text = six.ensure_text(input_text)
        return JsonParser(
            TextScanner(input_text), True, check_duplicate_keys
        ).parse_value()

    def parse_value(self):
        """Parses a Json value from the input."""
        start_pos = self.__scanner.position
        try:
            c = self.__peek_next_non_whitespace()
            if c == "{":
                return self.__parse_object()
            elif c == "[":
                return self.__parse_array()
            elif c == '"':
                if self.__check_repeated_chars('"', offset=1, count=2):
                    return self.__parse_triple_quoted_string()
                else:
                    return self.__parse_string_with_concatenation()
            elif c == "t":
                self.__match("true", "unknown identifier")
                return True
            elif c == "f":
                self.__match("false", "unknown identifier")
                return False
            elif c == "n":
                self.__match("null", "unknown identifier")
                return None
            # end of the text or empty input.
            elif c is None:
                if start_pos == 0:
                    return self.__error("Empty input")
                else:
                    return self.__error("Unexpected end-of-text")
            # this must be after None check because we can not compare with None in python3
            elif c == "-" or "0" <= c <= "9":
                return self.__parse_number()
            elif c == "}":
                return self.__error("'}' can only be used to end an object")
            elif c == "`":
                return self.__error(
                    "Json_lib parser does not support length prefixed strings any more."
                )
            else:
                return self.__error("Unexpected character '%s'" % c)
        except IndexError:
            raise JsonParseException(
                "Parser unexpectantly reached end of input probably due to "
                "an terminated string, object, or array",
                start_pos,
                self.__scanner.line_number_for_offset(start_pos),
            )

    def __parse_object(self):
        """Parse a JSON object. The scanner must be at the first '{'."""

        object_start = self.__scanner.position
        self.__scanner.read_uchar()

        result_object = JsonObject()

        while True:
            c = self.__peek_next_non_whitespace()

            if c is None:
                return self.__error("Need '}' for end of object", object_start)
            elif c == '"':
                key = self.__parse_string()
            elif c == "_" or "a" <= c <= "z" or "A" <= c <= "Z":
                key = self.__parse_identifier()

                next_char = self.__scanner.peek_next_uchar(none_if_bad_index=True)

                if next_char is None:
                    return self.__error("Need '}' for end of object", object_start)
                if next_char > " " and next_char != ":":
                    self.__error(
                        "To use character '%s' in an attribute name, "
                        "you must place the attribute name in "
                        "double-quotes" % next_char
                    )
            elif c == "}":
                # End-of-object.
                self.__scanner.read_uchar()
                return result_object
            else:
                return self.__error("Expected string literal for object attribute name")

            if key is not None:
                key = six.ensure_text(key)

            self.__peek_next_non_whitespace()
            c = self.__scanner.read_uchar()

            if c != ":":
                self.__error("Expected ':' delimiting object attribute value")

            # skip any whitespace after the colon
            self.__peek_next_non_whitespace()

            if self.check_duplicate_keys and result_object.__contains__(key):
                self.__error("Duplicate key [" + key + "]", object_start)

            result_object.put(key, self.parse_value())

            c = self.__peek_next_non_whitespace()

            if c is None:
                self.__error("Need '}' for end of object", object_start)
            elif c == "}":
                # do nothing we'll process the '}' back around at the top of
                # the loop.
                continue
            elif c == ",":
                self.__scanner.read_uchar()
            else:
                if self.__preceding_line_break() and self.allow_missing_commas:
                    # proceed, inferring a comma
                    continue
                else:
                    self.__error(
                        "After object field, expected ',' or '}' but "
                        "found '%s'... are you missing a comma?" % c
                    )

    def __parse_array(self):
        """Parse a JSON array. The scanner must be at the first '['."""
        array_start = self.__scanner.position
        self.__scanner.read_uchar()

        array = JsonArray()

        while True:
            # Check for end-of-array.
            if self.__peek_next_non_whitespace() == "]":
                self.__scanner.read_uchar()
                return array

            self.__peek_next_non_whitespace()  # skip any whitespace
            # TODO:  If we ever want to put in annotated supported, uncomment the pos lines.
            # value_start_pos = self.__scanner.position

            array.add(self.parse_value())
            # value_end_pos = self.__scanner.position
            # value_comma_pos = -1

            c = self.__peek_next_non_whitespace()
            if c is None:
                self.__error("Array has no terminating '['", array_start)
            elif c == "]":
                # do nothing we'll process the ']' back around at the top of
                # the loop.
                continue
            elif c == ",":
                self.__scanner.read_uchar()
                # value_comma_pos = self.__scanner.position
            else:
                if self.__preceding_line_break() and self.allow_missing_commas:
                    # proceed, inferring a comma
                    continue
                else:
                    self.__error(
                        "Unexpected character [%s] in array... are you "
                        "missing a comma?" % c
                    )

    def __parse_triple_quoted_string(self):
        """Parse a string literal that is triple quoted.  The scanner must be positioned at the first '"'.

        With a triple quote, all input up until the next triple quote is consumed, regardless of newlines, quotes,
        etc.

        @return:  The string
        @rtype: six.text_type
        """
        if not self.__consume_repeated_chars('"', count=3):
            self.__error("string literal not begun with triple quote")

        start_pos = self.__scanner.position
        length = 0
        while True:
            if length >= self.__scanner.characters_remaining:
                self.__error("string literal not terminated")

            c = self.__scanner.peek_next_uchar(offset=length)
            if c == '"' and self.__check_repeated_chars(
                '"', count=2, offset=length + 1
            ):
                break

            length += 1

            if c == "\\":
                if length >= self.__scanner.characters_remaining:
                    self.__error("incomplete backslash sequence")
                length += 1

        result = self.__scanner.read_uchars(length)

        self.__consume_repeated_chars('"', count=3)

        return self.__process_escapes(result, start_pos)

    def __parse_string_with_concatenation(self):
        """Parse a string literal. The scanner must be at the first '"'.

        If the string is followed by one or more "+", string literal sequences,
        consume those as well, and return the concatenation. E.g. for input:
        "abc" + "def" + "ghi", we return abcdefghi."""
        value = self.__parse_string()

        c = self.__peek_next_non_whitespace()
        if c != "+":
            return value

        all_strings = [value]

        while True:
            assert self.__scanner.read_uchar() == "+", "No plus found"
            c = self.__peek_next_non_whitespace()
            if c != '"':
                self.__error("Expected string literal after + operator")

            all_strings.append(self.__parse_string())
            if self.__peek_next_non_whitespace() != "+":
                break

        return "".join(all_strings)

    def __parse_identifier(self):
        """Parse an identifier."""
        length = 0

        while True:
            c = self.__scanner.peek_next_uchar(offset=length, none_if_bad_index=True)
            if c is None:
                break
            elif c == "_" or "a" <= c <= "z" or "A" <= c <= "Z" or "0" <= c <= "9":
                length += 1
            else:
                break

        return self.__scanner.read_uchars(length)

    def __parse_string(self):
        """Parse a string literal. The next character should be '\"'."""
        start_pos = self.__scanner.position

        # Have to consume the beginning quote mark
        c = self.__scanner.read_uchar()
        if c != '"':
            return self.__error(
                "string literal should start with double quotation mark."
            )

        length = 0
        while True:
            if length >= self.__scanner.characters_remaining:
                self.__error("string literal not terminated")

            c = self.__scanner.peek_next_uchar(offset=length)
            if c == '"':
                break

            length += 1

            if c == "\\":
                if length >= self.__scanner.characters_remaining:
                    self.__error("incomplete backslash sequence")
                length += 1
            elif c == "\r" or c == "\n":
                self.__error("string literal not terminated before end of line")

        result = self.__scanner.read_uchars(length)
        # Have to consume the quote mark
        self.__scanner.read_uchar()

        return self.__process_escapes(result, start_pos + 1)

    def __process_escapes(self, s, literal_start):
        """Convert backlash sequences in raw string literal.

        @param s: The raw contents of a raw string literal.

        @return: The string with all backlash sequences converted to their chars."""

        if s.find("\\") < 0:
            return s

        slen = len(s)
        sb = []
        i = 0
        while i < slen:
            c = s[i]
            if c != "\\":
                sb.append(c)
                i += 1
                continue
            if i + 1 >= slen:
                self.__error("No character after escape", literal_start + i)

            i += 1
            c = s[i]
            if c == "t":
                sb.append("\t")
            elif c == "n":
                sb.append("\n")
            elif c == "r":
                sb.append("\r")
            elif c == "b":
                sb.append("\b")
            elif c == "f":
                sb.append("\f")
            elif c == '"':
                sb.append('"')
            elif c == "\\":
                sb.append("\\")
            elif c == "/":
                sb.append("/")
            elif c == "u" and i + 5 <= slen:
                hex_string = s[i + 1 : i + 5]
                i += 4
                sb.append(unichr(int(hex_string, 16)))
            else:
                self.__error(
                    "Unexpected backslash escape [" + c + "]", literal_start + i
                )
            i += 1
        return "".join(sb)

    def __parse_number(self):
        """Parse a numeric literal."""
        literal_buffer = []
        all_digits = True
        sign = 1

        while not self.__scanner.at_end:
            peek = self.__scanner.peek_next_uchar()
            if (
                (peek != "+")
                and (peek != "-")
                and (peek != "e")
                and (peek != "E")
                and (peek != ".")
                and (not "0" <= peek <= "9")
            ):
                break

            if len(literal_buffer) >= 100:
                self.__error("numeric literal too long (limit 100 characters)")

            next_char = self.__scanner.read_uchar()

            # Never append a leading minus sign to literal_buffers, merely record the sign
            if next_char == "-" and len(literal_buffer) == 0:
                sign = -1
            else:
                all_digits = all_digits and "0" <= next_char <= "9"
                literal_buffer.append(next_char)

        if all_digits and len(literal_buffer) <= 18:
            value = 0
            for digit in literal_buffer:
                value = (value * 10) + ord(digit) - ord("0")
            return sign * value

        number_string = "".join(literal_buffer)
        if (
            number_string.find(".") < 0
            and number_string.find("e") < 0
            and number_string.find("E") < 0
        ):
            try:
                return sign * int(number_string)
            except ValueError:
                self.__error("Could not parse number as long '%s'" % number_string)
        else:
            try:
                return sign * float(number_string)
            except ValueError:
                self.__error("Could not parse number as float '%s'" % number_string)

    def __parse_comment(self):
        """Scan through a // or /* comment."""
        comment_start_pos = self.__scanner.position

        # Consume the /
        self.__scanner.read_uchar()

        if self.__scanner.at_end:
            self.__error("Unexpected character '/'")

        c = self.__scanner.read_uchar()
        if c == "/":
            # This is a "//" comment. Scan through EOL.
            while not self.__scanner.at_end:
                c = self.__scanner.read_uchar()
                if c == "\n" or c == "\r":
                    break

            # If this is a CRLF, scan through the LF.
            if (
                c == "\r"
                and self.__scanner.peek_next_uchar(none_if_bad_index=True) == "\n"
            ):
                self.__scanner.read_uchar()
        elif c == "*":
            # This is a "/*" comment. Scan through "*/".
            while not self.__scanner.at_end:
                c = self.__scanner.read_uchar()
                if (
                    c == "*"
                    and self.__scanner.peek_next_uchar(none_if_bad_index=True) == "/"
                ):
                    self.__scanner.read_uchar()
                    return
            self.__error("Unterminated comment", comment_start_pos)
        else:
            self.__error("Unexpected character '/%s'" % c)

    def __match(self, chars, error_message):
        """Verify that the next N characters match chars,
        and consume them.  In case of a mismatch, raise an exception.

        If error_message is None, we generate a default message.
        :type chars six.text_type
        """
        start_pos = self.__scanner.position

        for i in range(0, len(chars)):
            expected = chars[i]
            if self.__scanner.at_end:
                actual = -1
            else:
                actual = self.__scanner.read_uchar()
            if expected != actual:
                if error_message is not None:
                    self.__error(error_message, start_pos)
                else:
                    self.__error('Expected "%s"' % chars, start_pos)

    def __error(self, error_message, position=None):
        """Report an error at the character just consumed."""
        if position is None:
            position = max(0, self.__scanner.position - 1)

        raise JsonParseException(
            error_message,
            position,
            self.__scanner.line_number_for_offset(position - self.__scanner.position),
        )

    def __preceding_line_break(self):
        i = -1
        b = self.__scanner.peek_next_uchar(offset=i, none_if_bad_index=True)
        while b is not None:
            if b == "\r" or b == "\n":
                return True
            elif b == " " or b == "\t":
                i += -1
                b = self.__scanner.peek_next_uchar(offset=i, none_if_bad_index=True)
            else:
                return False
        return False

    def __check_repeated_chars(self, expected_character, count=2, offset=1):
        """Returns true if the next `count` characters are equal to `expected_character`.

        @param expected_character: The expected character.
        @param count: The expected number of occurrences.
        @param offset: The offset at which to begin looking for the repeated characters.

        @type expected_character: char
        @type count: int
        @type offset: int

        @return: True if characters from `offset` to `offset + count` are all equal to `expected_character`.  If there
            are not enough characters in the stream, False is returned.
        @rtype: bool
        """
        if offset + count > self.__scanner.characters_remaining:
            return False

        for i in range(offset, offset + count):
            if self.__scanner.peek_next_uchar(offset=i) != expected_character:
                return False
        return True

    def __consume_repeated_chars(self, expected_character, count=2):
        """Consumes the next `count` characters in the stream, as long as they are all equal to `expected_character`.

        @param expected_character: The expected character.
        @param count:   The expected number of occurrences.

        @type expected_character: char
        @type count:  int

        @return:  True if the characters are consumed.
        @rtype: bool
        """
        if self.__check_repeated_chars(expected_character, count=count, offset=0):
            self.__scanner.advance_position(count)
            return True
        else:
            return False

    def __peek_next_non_whitespace(self):
        """Scan up to the next non-whitespace and return it.

        This will consume all whitespace and comment character, searchg for
        the first meaningful parse character.

        @return: The first non-whitespace, non-comment character, or None if the end
            of the buffer is reached."""

        while True:
            # TODO: support any Unicode / UTF-8 whitespace sequence.
            c = self.__scanner.peek_next_uchar(none_if_bad_index=True)
            if c is None:
                return None

            if c == " " or c == "\t" or c == "\r" or c == "\n":
                self.__scanner.read_uchar()
                continue
            elif c == "/":
                self.__parse_comment()
                continue
            return c


def parse(input_text, check_duplicate_keys=False):
    """Parses the input as JSON and returns its contents.

    It supports Scalyr's extensions to the Json format, including comments and
    binary data. Specifically, the following are allowed:

     - // and /* comments
     - Concatenation of string literals using '+'
     - Unquoted identifiers can be used as field names in an object literal
     - Not requiring commas between array elements and object fields

     - TODO:  support `b (backtick-b) binary data format used by Scalyr
       servers.

    @param input_text: A string containing the unicode string to be parsed.
    @param check_duplicate_keys: If true, then we throw an exception if any JSON object contains two entries with the same name.

        JsonParseException if there is an error in the parsing.
    """
    return JsonParser.parse(input_text, check_duplicate_keys)
