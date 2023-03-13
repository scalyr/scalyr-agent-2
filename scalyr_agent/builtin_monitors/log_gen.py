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
# An example ScalyrMonitor plugin to demonstrate how they can be written.
#
# Note, this can be run in standalone mode by:
#     python -m scalyr_agent.run_monitor -c "{ gauss_mean: 0.5 }" scalyr_agent.builtin_monitors.test_monitor
#
# author:  Steven Czerwinski <czerwin@scalyr.com>

from __future__ import absolute_import

__author__ = "czerwin@scalyr.com"
import requests
import subprocess
import random
import subprocess
import sys
import os
import re
import datetime
import glob
import json
from scalyr_agent.json_lib.objects import ArrayOfStrings
from scalyr_agent.json_lib import JsonObject
#from scalyr_agent.json_lib.objects import ArrayOfStrings
from scalyr_agent import ScalyrMonitor
#import scalyr_agent.third_party.tcollector.tcollector as tcollector
#
#from scalyr_agent import (
#    ScalyrMonitor,
#    BadMonitorConfiguration,
#    define_metric,
#    define_log_field,
#    define_config_option,
#)
#from scalyr_agent.third_party.tcollector.tcollector import ReaderThread
#from scalyr_agent.json_lib import JsonObject
#from scalyr_agent.json_lib.objects import ArrayOfStrings
#from scalyr_agent import StoppableThread
class LogGenerator(ScalyrMonitor):
    """A Scalyr agent monitor that records random numbers.
    """

    def _initialize(self):

# Disable SSL verification for requests made by OpenAI API
        #requests.packages.urllib3.disable_warnings()
        """Performs monitor-specific initialization."""
        self.__counter = 0
        # A required configuration field.
        self.__logs = self._config.get("logs", required_field=True, default = "/tmp/*")
        self.__openai_file_output = self._config.get("openai_file_output", required_field=False, default = "/tmp/openai.log")
        self.__openai_api_key = self._config.get("openai_api_key", required_field=False, default="")
        self.__mode = self._config.get("mode", required_field=False, default='static')
        self.__log_types = self._config.get("log_types", required_field=False, default='access logs')
        self.__log_system = self._config.get("log_system", required_field=False, default='cisco')
        self.__openai_special_requests = self._config.get("openai_special_requests", required_field=False, default= "none")
        self.__openai_call_limit = self._config.get("openai_call_limit",convert_to=int, required_field=False, default= "5")
        self.__openai_log_lines_per_request = self._config.get("openai_log_lines_per_request", required_field=False, default= "5")
        self.__openai_format = self._config.get("openai_format", required_field=False, default= "standard format")
        self.__sampling_rate = self._config.get("sampling_rate" ,convert_to=float, required_field=False, default= ".1")
        self.__schema = self._config.get("schema" , required_field=False, default= "{'key':'value'}")
        self.__type_array = self._config.get("type_array",convert_to=ArrayOfStrings, required_field=False, default= "['cisco', 'windows_dns']")
        self.__time_pattern = self._config.get("time_pattern", required_field=False, default= "(?P<date>(\d+ \w+ \d+|\d+\/\d+\/\d+)) (?P<time>(\d{2}:\d{2}:\d{2}\.\d{3}|\d+:\d+:\d+ \w+))")
        self.__parser = self._config.get("parser", required_field=False, default= "json")

        self.__time_pattern = r"%s" % self.__time_pattern
#        self.__time_pattern = r"(?P<date>\d{4} \w{3} \d{2}) (?P<time>\d{2}:\d{2}:\d{2}\.\d{3})"

        self.__files = self.find_matching_files()

        # Make a copy just to be safe.
        tags = self._config.get("tags", default=JsonObject())
        if type(tags) is not dict and type(tags) is not JsonObject:
            raise BadMonitorConfiguration(
                "The configuration field 'tags' is not a dict or JsonObject", "tags"
            )
        tags = JsonObject(content=tags)
        tags["parser"] = self.__parser
        self.log_config = {
            "attributes": tags,
            "parser": self.__parser,
            "path": "linux_system_metrics.log",
        }



    def install_dependencies(self, libs_to_install):
        try:
            # check if pip is up-to-date
            subprocess.check_call(["pip", "install", "--upgrade", "pip"])
        except subprocess.CalledProcessError as e:
            print("Error: ", e)

        # libraries to install
        #libs_to_install = ["glob2", "requests"]

        # loop through each library and check if it is installed
        for lib in libs_to_install:
            try:
                # check if library is already installed
                subprocess.check_call(["pip", "show", lib], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                # library not found, install it
                print(f"{lib} not found, installing...")
                subprocess.check_call(["pip", "install", "--quiet", lib])
        # create test file if it does not exist
    def generate_log(self):
        file_path = self.__openai_file_output
        if os.path.exists(file_path):
            try:
                with open(file_path) as f:
                    last_line = f.readlines()[-1]
                    # print the last line
                    print(last_line)
            except IndexError:
                last_line = ""
                # print a message indicating that the file is empty
                print(f"The file {file_path} is empty.")
        else:
            # print a message indicating that the file does not exist
            print(f"The file {file_path} does not exist.")
            last_line = ""
        # Make a request to the OpenAI API to generate log lines
        generated_prompt = """
        Act as a log generator. Your job is to generate log lines as output. You are an expert in information security, networks, observability, splunk and scalyr.
        Rules: If it is not a log, do not add it to the output. Only the log can be printed. If you produce paragraphs of text, you lose 5 points. If you give me multiline log lines, you lose 3 points. If you truncate a log you lose a point. If you don't return the requested format you lose a point.
        Rules: Make each log realistic. Consider the log line from previous conversation when generaating next log line.

        """
        log_types = "\nLog Type: " +  self.__log_types
        system = "\nsystem: " + self.__log_system
        quantity = "\nLines to produce: " + self.__openai_log_lines_per_request
        special = "\nSpecial requests for the log line: " + self.__openai_special_requests
        format = "\noutput format: " + self.__openai_format
        last_line = "\nLog line from previous conversation: " + last_line
        suffix = "\nGenerate logs based upon the Rules and Parameters provided"
        schema = "\nthe output look be like this please respect the start and end characters: " + self.__schema
        prompt = generated_prompt + schema + log_types + system + last_line + quantity + special + format + suffix
        log_lines = self.open_ai_call(prompt)

        mode = 'a' if os.path.exists(file_path) else 'w'
        with open(file_path, mode) as f:
            print(f"trying mode {mode}")
            f.write(log_lines)
#
    def open_ai_call(self, prompt):
        print("calling open ai")
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + self.__openai_api_key,
        }

        data = {
            'prompt': prompt,
            'max_tokens': 1900,
            'temperature': 0.6,
            'n': 1,
        }

        response = requests.post('https://api.openai.com/v1/engines/text-davinci-002/completions', headers=headers, json=data, verify=False)

#        print(response.text)
        response = response.json()["choices"][0]["text"]
        return response


    def find_matching_files(self):
        matching_files = []
        print("initializing find matching files")

        # Get a list of all files that match the glob pattern
        log_files = glob.glob(self.__logs)
        print(f"here are the logfiles {log_files}")

        # Check if each file matches the string to match
        for file in log_files:
            if os.path.isfile(file):
                basename = os.path.basename(file)
                name, ext = os.path.splitext(basename)
                for type in self.__type_array:
                    if type in name:
                        matching_files.append(basename)
                        print(f"here is a logfile {type} that matches {name}")
                        break
                    else:
                        print(f"here is a logfile {type} that does not match {name}")
        return matching_files



    def gather_sample(self):
        # set the time pattern to match
#        print(f"executing {self.__files}")
        files_to_sync = self.__files
        if (self.__counter <= self.__openai_call_limit) and (self.__mode == "ai" or self.__mode == "combined"):
            self.generate_log()
            self.__counter += 1
        time_pattern = self.__time_pattern

        # iterate through all files matching the glob pattern in self.__logs
        for logfile in glob.glob(self.__logs):
            filename = os.path.basename(logfile)
            for file in files_to_sync:
                if filename in file:
                #    print(f"Filename {filename} is within path {file}")
                    with open(logfile, 'r') as f:
                        # read each line in the file
                        for line in f:
                            # find all instances of the time pattern in the line
                            rand_num = random.random()
                            threshold = self.__sampling_rate
                            if rand_num <= threshold:
                                matches = re.findall(time_pattern, line)
                                for match in matches:
                                    # extract the date and time from the match
                                    date_str = match[0]
                                    time_str = match[1]
                                    # convert the date and time strings to datetime objects
                                    #date_obj = datetime.datetime.strptime(date_str, "%Y %b %d")
                                    #time_obj = datetime.datetime.strptime(time_str, "%H:%M:%S.%f")
                                    # combine the date and time into a single datetime object
                                    #timestamp_obj = datetime.datetime.combine(date_obj.date(), time_obj.time())
                                    # replace the matched date and time string with the current date and time
                                    now_date = datetime.datetime.now().strftime("%Y-%m-%d")
                                    now_time = datetime.datetime.now().strftime("%H:%M:%S")
                                    now_timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
                                    line = line.replace(date_str, now_date)
                                #    line = line.replace(time_str, now_time)
                                if len(line.strip()) > 5:
                                    self.log_config = {
                                        "path": filename,
                                    }
                                    self._logger.emit_value(filename, line.strip())
                                else:
                                    print("line too small")
