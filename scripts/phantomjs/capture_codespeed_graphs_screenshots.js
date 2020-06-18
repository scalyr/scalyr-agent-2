/**
#  Copyright 2014 Scalyr Inc.
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
**/

// Script which captures screenshot of the CodeSpeed timeline page for a specific set of benchmarks
// and stores it to disk.
var webpage = require('webpage');
var system = require('system');

var CODESPEED_AUTH = system.env['CODESPEED_AUTH'];

// How much time to wait for chart XHR data to load
var CHART_LOAD_TIMEOUT = 5000;

var BASE_TIMELINE_CHART_URL = 'https://' + CODESPEED_AUTH + '@scalyr-agent-codespeed.herokuapp.com/timeline/?exe=2%2C6%2C3%2C7%2C10%2C1%2C5%2C4%2C8&base=1%2B95&env=1&revs=30&equid=off&quarts=on&extr=on'

// A list of benchmark names we capture screenshots for
var BENCHMARK_NAMES = [
  'memory_usage_rss',
  'log_lines_error',
  'log_lines_info',
  'log_lines_debug',
]

var DESTINATION_PATH = "/tmp/codespeed-screenshots/";

function capture_screenshot(url, destination_filename) {
  console.log("Capturing screenshot for " + url.replace(CODESPEED_AUTH, "***"));

  var page = webpage.create();
  page.viewportSize = { width: 1680, height: 768 };
  page.clipRect = { top: 0, left: 0, width: 1680, height: 768 };
  page.open(url, function() {
    setTimeout(function() {
      var destination_path = DESTINATION_PATH + destination_filename;
      page.render(destination_path);
      console.log('Screenshot saved to ' + destination_path);
    }, CHART_LOAD_TIMEOUT);
  });
}

for (var i = 0; i < BENCHMARK_NAMES.length; i++) {
  var benchmark_name = BENCHMARK_NAMES[i];
  var url = BASE_TIMELINE_CHART_URL + '&ben=' + benchmark_name;
  var destination_filename = benchmark_name + ".png";

  capture_screenshot(url, destination_filename);
}

setTimeout(phantom.exit, 10 * 1000);
