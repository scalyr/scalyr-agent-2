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

__author__ = 'czerwin@scalyr.com'

import struct

from scalyr_agent.json_lib import JsonArray, JsonObject, JsonParseException


class ByteScanner(object):
    """Allows for iterating over a byte input.

    ByteScanner wraps an incoming byte array of input and provides
    methods to iterate over the bytes.  It also provides methods to
    perform typical conversions.
    """

    def __init__(self, string_input, start_pos=0, max_pos=None):
        """Construct a new instance of a ByteScanner.

        @param string_input: The input to scan. This should be a byte string.
        @param start_pos: The index within innput to begin the scan.
        @param max_pos: The index to at which to consider the scan is finished. If none is given, then the length of
            input is used.

        @return: The new instance."""
        self.__buffer = []
        self.__pos = start_pos
        self.__start_pos = start_pos
        self.__max_pos = len(string_input)
        if not max_pos is None:
            self.__max_pos = max_pos

        # Go through and make sure the bytes are all less than 255.  I
        # am not sure if the b'' is really need to force a binary string,
        # especially since python 2.X, all strings are binary by default.
        for i in range(len(string_input)):
            self.__buffer.append("" + chr(ord(string_input[i]) & 255))

    @property
    def at_end(self):
        """True if the scanner is at the end of the byte input."""
        return self.__pos >= self.__max_pos

    @property
    def position(self):
        """The position of the scan relative to original byte array.

        Notes, if this object does not offset the position by any start_pos
        used in the construction.  It is relative to the underlying byte array
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

        @raise IndexError: If the offset places the position outside of the valid range for the underlying byte
            range."""
        line_num = 1
        target_pos = self.__pos + offset
        x = self.__start_pos

        self.__check_index(target_pos)
 
        while x < target_pos:
            b = self.__buffer[x]
            x += 1
            if b == '\n':
                line_num += 1
            elif b == '\r':
                line_num += 1
                # If this CR is the first half of a CRLF sequence, 
                # skip the LF; otherwise we'd double-count CRLF line breaks.
                if x < target_pos and self.__buffer[x] == '\n':
                    x += 1
        return line_num

    @property
    def bytes_remaining(self):
        """The number of bytes that may be read before the end is reached."""
        return self.__max_pos - self.__pos

    def read_ubyte(self):
        """Returns the next byte from the buffer.

        @raise IndexError: If the scanner is already at the end of the buffer."""
        self.__check_read_size(1)
        self.__pos += 1
        return self.__buffer[self.__pos - 1]

    def read_ubytes(self, length):
        """Returns the next length bytes from the buffer.

        @raise IndexError: If the end of the buffer would be reached before length bytes are read. In this case, the
            buffer is not advanced."""
        self.__check_read_size(length)
        my_slice = self.__buffer[self.__pos:self.__pos + length]
        self.__pos += length
        return "".join(my_slice)

    def peek_next_ubyte(self, offset=0, none_if_bad_index=False):
        """Returns the next byte that will be returned when read_ubyte is 
        invoked.

        @param offset: Optional argument to allow peeking at not just the next byte but bytes beyond that as well. A
            value of 0 references the next byte, while 1 is the one after that, etc. You may specify negative indexes,
            which access the previous bytes returned by read_ubyte, -1 for the last, etc.
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
                "Index out of range for buffer (index %i, limit %i to %i)" %
                (index, self.__start_pos, self.__max_pos))
        self.__pos = index

    def __check_read_size(self, read_length):
        index = self.__pos + read_length - 1
        if index < self.__start_pos or index >= self.__max_pos:
            raise IndexError(
                "Ran off end of buffer (position %i, limit %i, reading %i bytes"
                % (self.__pos, self.__max_pos, read_length))

    def __check_index(self, index):
        if index < self.__start_pos or index >= self.__max_pos:
            raise IndexError(
                "Index out of range for buffer (index %i, limit %i to %i)" %
                (index, self.__start_pos, self.__max_pos))


class JsonParser(object):
    """Parses raw byte input into JsonObjects and supports Scalyr's extensions.

    JsonParser is the main abstraction for parsing raw byte input
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

    def __init__(self, input_scanner, allow_missing_commas=True, check_duplicate_keys=False):
        """Initializes JsonParser for the specified input."""
        self.__scanner = input_scanner
        self.allow_missing_commas = allow_missing_commas
        self.check_duplicate_keys = check_duplicate_keys

    @staticmethod
    def parse(input_bytes, check_duplicate_keys=False):
        return JsonParser(ByteScanner(input_bytes), True, check_duplicate_keys).parse_value()

    def parse_value(self):
        """Parses a Json value from the input."""
        start_pos = self.__scanner.position
        try:
            c = self.__peek_next_non_whitespace()
            if c == '{':
                return self.__parse_object()
            elif c == '[':
                return self.__parse_array()
            elif c == '"':
                if self.__check_repeated_chars('"', offset=1, count=2):
                    return self.__parse_triple_quoted_string()
                else:
                    return self.__parse_string_with_concatenation()
            elif c == 't':
                self.__match("true", "unknown identifier")
                return True
            elif c == 'f':
                self.__match("false", "unknown identifier")
                return False
            elif c == 'n':
                self.__match("null", "unknown identifier")
                return None
            elif c == '-' or '0' <= c <= '9':
                return self.__parse_number()
            elif c == '}':
                return self.__error("'}' can only be used to end an object")
            elif c == '`':
                return self.__parse_length_prefixed_string()
            else:
                if c is None:
                    if start_pos == 0:
                        return self.__error("Empty input")
                    else:
                        return self.__error("Unexpected end-of-text")
                else:
                    return self.__error("Unexpected character '%s'" % c)
        except IndexError:
            raise JsonParseException(
                "Parser unexpectantly reached end of input probably due to "
                "an terminated string, object, or array", start_pos,
                self.__scanner.line_number_for_offset(start_pos))
    
    def __parse_object(self):
        """Parse a JSON object. The scanner must be at the first '{'."""

        object_start = self.__scanner.position
        self.__scanner.read_ubyte()

        result_object = JsonObject()

        while True:
            c = self.__peek_next_non_whitespace()
      
            if c is None:
                return self.__error("Need '}' for end of object", object_start)
            elif c == '"':
                key = self.__parse_string()
            elif c == '_' or 'a' <= c <= 'z' or 'A' <= c <= 'Z':
                key = self.__parse_identifier()
    
                next_char = self.__scanner.peek_next_ubyte(
                    none_if_bad_index=True)

                if next_char is None:
                    return self.__error("Need '}' for end of object",
                                        object_start)
                if ord(next_char) > 32 and next_char != ':':
                    self.__error("To use character '%s' in an attribute name, "
                                 "you must place the attribute name in "
                                 "double-quotes" % next_char)
            elif c == '}':
                # End-of-object.
                self.__scanner.read_ubyte()
                return result_object
            else:
                return self.__error(
                    "Expected string literal for object attribute name")

            self.__peek_next_non_whitespace()
            c = self.__scanner.read_ubyte()

            if c != ':':
                self.__error("Expected ':' delimiting object attribute value")

            # skip any whitespace after the colon
            self.__peek_next_non_whitespace()
            if self.check_duplicate_keys and result_object.__contains__(key):
                self.__error("Duplicate key [" + key + "]", object_start)

            result_object.put(key, self.parse_value())
      
            c = self.__peek_next_non_whitespace()
      
            if c is None:
                self.__error("Need '}' for end of object", object_start)
            elif c == '}':
                # do nothing we'll process the '}' back around at the top of 
                # the loop.
                continue
            elif c == ',':
                self.__scanner.read_ubyte()
            else:
                if self.__preceding_line_break() and self.allow_missing_commas:
                    # proceed, inferring a comma
                    continue
                else:
                    self.__error("After object field, expected ',' or '}' but "
                                 "found '%s'... are you missing a comma?" % c)

    def __parse_array(self):
        """Parse a JSON array. The scanner must be at the first '['."""
        array_start = self.__scanner.position
        self.__scanner.read_ubyte()

        array = JsonArray()

        while True:
            # Check for end-of-array.
            if self.__peek_next_non_whitespace() == ']':
                self.__scanner.read_ubyte()
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
            elif c == ']':
                # do nothing we'll process the ']' back around at the top of 
                # the loop.
                continue
            elif c == ',':
                self.__scanner.read_ubyte()
                # value_comma_pos = self.__scanner.position
            else:
                if self.__preceding_line_break() and self.allow_missing_commas:
                    # proceed, inferring a comma
                    continue
                else:
                    self.__error("Unexpected character [%s] in array... are you "
                                 "missing a comma?" % c)

    def __parse_length_prefixed_string(self):
        """Parses the string literal from the Scalyr-specific format using length prefixed strings.  The scanner must
        be at the backtick (`).

        @return: The string literal
        @rtype: str
        """
        # The format is `s[x]YYYY   where [x] is a 4 byte big endian signed int containing the number of bytes
        # to read as the string, and YYYY is those number of bytes.  It is encoded as UTF-8
        self.__scanner.read_ubyte()
        if self.__scanner.peek_next_ubyte(none_if_bad_index=True) != 's':
            self.__error("unsupported back-tick format.  Only supports length prefixed string (`s)")
        self.__scanner.read_ubyte()
        # Next four bytes will be the length of the string to read, in big-endian order.  The length is a signed int.
        encoded_num_bytes = self.__scanner.read_ubytes(4)
        num_bytes = struct.unpack('>i', encoded_num_bytes)[0]
        return self.__scanner.read_ubytes(num_bytes)

    def __parse_triple_quoted_string(self):
        """Parse a string literal that is triple quoted.  The scanner must be positioned at the first '"'.

        With a triple quote, all input up until the next triple quote is consumed, regardless of newlines, quotes,
        etc.

        @return:  The string
        @rtype: str
        """
        if not self.__consume_repeated_chars('"', count=3):
            self.__error("string literal not begun with triple quote")

        start_pos = self.__scanner.position
        length = 0
        while True:
            if length >= self.__scanner.bytes_remaining:
                self.__error("string literal not terminated")

            c = self.__scanner.peek_next_ubyte(offset=length)
            if c == '"' and self.__check_repeated_chars('"', count=2, offset=length+1):
                break

            length += 1

            if c == '\\':
                if length >= self.__scanner.bytes_remaining:
                    self.__error("incomplete backslash sequence")
                length += 1

        result = self.__scanner.read_ubytes(length)

        self.__consume_repeated_chars('"', count=3)

        return self.__process_escapes(result.decode("utf8", 'replace'), start_pos)

    def __parse_string_with_concatenation(self):
        """Parse a string literal. The scanner must be at the first '"'.

        If the string is followed by one or more "+", string literal sequences, 
        consume those as well, and return the concatenation. E.g. for input:
        "abc" + "def" + "ghi", we return abcdefghi."""
        value = self.__parse_string()
    
        c = self.__peek_next_non_whitespace()
        if c != '+':
            return value
    
        all_strings = [value]

        while True:
            assert (self.__scanner.read_ubyte() == '+'), "No plus found"
            c = self.__peek_next_non_whitespace()
            if c != '"':
                self.__error("Expected string literal after + operator")

            all_strings.append(self.__parse_string())
            if self.__peek_next_non_whitespace() != '+':
                break

        return ''.join(all_strings)
  
    def __parse_identifier(self):
        """Parse an identifier."""
        length = 0

        while True:
            c = self.__scanner.peek_next_ubyte(offset=length, none_if_bad_index=True)
            if c == '_' or 'a' <= c <= 'z' or 'A' <= c <= 'Z' or '0' <= c <= '9':
                length += 1
            else:
                break

        return self.__scanner.read_ubytes(length)

    def __parse_string(self):
        """Parse a string literal. The next character should be '\"'."""
        start_pos = self.__scanner.position

        c = self.__scanner.read_ubyte()
        if c != '"':
            return None

        length = 0
        while True:
            if length >= self.__scanner.bytes_remaining:
                self.__error("string literal not terminated")
      
            c = self.__scanner.peek_next_ubyte(offset=length)
            if c == '"':
                break
            
            length += 1
            
            if c == '\\':
                if length >= self.__scanner.bytes_remaining:
                    self.__error("incomplete backslash sequence")
                length += 1
            elif c == '\r' or c == '\n':
                self.__error("string literal not terminated before end of line")

        result = self.__scanner.read_ubytes(length)
        # Have to consume the quote mark
        self.__scanner.read_ubyte()

        return self.__process_escapes(result.decode("utf8", 'replace'), start_pos + 1)
  
    def __process_escapes(self, s, literal_start):
        """Convert backlash sequences in raw string literal.

        @param s: The raw contents of a raw string literal.

        @return: The string with all backlash sequences converted to their chars."""

        if s.find('\\') < 0:
            return s

        slen = len(s)
        sb = []
        i = 0
        while i < slen:
            c = s[i]
            if c != '\\':
                sb.append(c)
                i += 1
                continue
            if i + 1 >= slen:
                self.__error("No character after escape", literal_start + i)

            i += 1
            c = s[i]
            if c == 't':
                sb.append('\t')
            elif c == 'n':
                sb.append('\n')
            elif c == 'r':
                sb.append('\r')
            elif c == 'b':
                sb.append('\b')
            elif c == 'f':
                sb.append('\f')
            elif c == '"':
                sb.append('"')
            elif c == '\\':
                sb.append('\\')
            elif c == '/':
                sb.append('/')
            elif c == 'u' and i+5 <= slen:
                hex_string = s[i+1:i+5]
                i += 4
                sb.append(unichr(int(hex_string, 16)))
            else:
                self.__error("Unexpected backslash escape [" + c + "]",
                             literal_start + i)
            i += 1
        return "".join(sb)

    def __parse_number(self):
        """Parse a numeric literal."""
        literal_buffer = []
        all_digits = True
    
        while not self.__scanner.at_end:
            peek = self.__scanner.peek_next_ubyte()
            if ((peek != '+') and (peek != '-') and (peek != 'e') and
                    (peek != 'E') and (peek != '.') and
                    (not '0' <= peek <= '9')):
                break
      
            if len(literal_buffer) >= 100:
                self.__error("numeric literal too long (limit 100 characters)")
      
            next_char = self.__scanner.read_ubyte()
            all_digits = all_digits and '0' <= next_char <= '9'
            literal_buffer.append(next_char)
    
        if all_digits and len(literal_buffer) <= 18:
            value = 0
            for digit in literal_buffer:
                value = (value * 10) + ord(digit) - ord('0')
            return value

        number_string = ''.join(literal_buffer)
        if (number_string.find('.') < 0 and
                number_string.find('e') < 0 and
                number_string.find('E') < 0):
            try:
                return long(number_string)
            except ValueError:
                self.__error(
                    "Could not parse number as long '%s'" % number_string)
        else:
            try:
                return float(number_string)
            except ValueError:
                self.__error(
                    "Could not parse number as float '%s'" % number_string)

    def __parse_comment(self):
        """Scan through a // or /* comment."""
        comment_start_pos = self.__scanner.position

        # Consume the /
        self.__scanner.read_ubyte()

        if self.__scanner.at_end:
            self.__error("Unexpected character '/'")
    
        c = self.__scanner.read_ubyte()
        if c == '/':
            # This is a "//" comment. Scan through EOL.
            while not self.__scanner.at_end:
                c = self.__scanner.read_ubyte()
                if c == '\n' or c == '\r':
                    break
      
            # If this is a CRLF, scan through the LF.
            if c == '\r' and self.__scanner.peek_next_ubyte(none_if_bad_index=True) == '\n':
                self.__scanner.read_ubyte()
        elif c == '*':
            # This is a "/*" comment. Scan through "*/".
            while not self.__scanner.at_end:
                c = self.__scanner.read_ubyte()
                if (c == '*' and 
                    self.__scanner.peek_next_ubyte(
                        none_if_bad_index=True) == '/'):
                    self.__scanner.read_ubyte()
                    return
            self.__error("Unterminated comment", comment_start_pos)
        else:
            self.__error("Unexpected character '/%s'" % c)
  
    def __match(self, chars, error_message):
        """Verify that the next N characters match chars,
        and consume them.  In case of a mismatch, raise an exception.
        Only supports low-ASCII characters.

        If error_message is None, we generate a default message."""
        start_pos = self.__scanner.position
      
        for i in range(0, len(chars)):
            expected = chars[i]
            if self.__scanner.at_end:
                actual = -1
            else:
                actual = self.__scanner.read_ubyte()
            if expected != actual:
                if error_message is not None:
                    self.__error(error_message, start_pos)
                else:
                    self.__error("Expected \"%s\"" % chars, start_pos)

    def __error(self, error_message, position=None):
        """Report an error at the character just consumed."""
        if position is None:
            position = max(0, self.__scanner.position - 1)

        raise JsonParseException(
            error_message, position,
            self.__scanner.line_number_for_offset(
                position - self.__scanner.position))

    def __preceding_line_break(self):
        i = -1
        b = self.__scanner.peek_next_ubyte(offset=i, none_if_bad_index=True)
        while not b is None:
            if b == '\r' or b == '\n':
                return True
            elif b == ' ' or b == '\t':
                i += -1
                b = self.__scanner.peek_next_ubyte(offset=i, none_if_bad_index=True)
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
        if offset + count > self.__scanner.bytes_remaining:
            return False

        for i in range(offset, offset + count):
            if self.__scanner.peek_next_ubyte(offset=i) != expected_character:
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

        This will consume all whitespace and comment bytes, searchg for
        the first meaningful parse character.

        @return: The first non-whitespace, non-comment byte, or None if the end
            of the buffer is reached."""

        while True:
            # TODO: support any Unicode / UTF-8 whitespace sequence.
            raw_c = self.__scanner.peek_next_ubyte(none_if_bad_index=True)
            if raw_c is None:
                return raw_c
            c = ord(raw_c)
            if c == 32 or c == 9 or c == 13 or c == 10:
                self.__scanner.read_ubyte()
                continue
            elif raw_c == '/':
                self.__parse_comment()
                continue
            return raw_c


def parse(input_bytes, check_duplicate_keys=False):
    """Parses the input as JSON and returns its contents.

    It supports Scalyr's extensions to the Json format, including comments and
    binary data. Specifically, the following are allowed:

     - // and /* comments
     - Concatenation of string literals using '+'
     - Unquoted identifiers can be used as field names in an object literal
     - Not requiring commas between array elements and object fields

     - TODO:  support `b (backtick-b) binary data format used by Scalyr
       servers.

    @param input_bytes: A string containing the bytes to be parsed.
    @param check_duplicate_keys: If true, then we throw an exception if any JSON object contains two entries with the same name.

        JsonParseException if there is an error in the parsing.
    """
    return JsonParser.parse(input_bytes, check_duplicate_keys)