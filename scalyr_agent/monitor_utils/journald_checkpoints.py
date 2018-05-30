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
# author:  Imron Alston <imron@scalyr.com>

__author__ = 'imron@scalyr.com'

import random
import threading
import scalyr_agent.util as scalyr_util
import scalyr_agent.scalyr_logging as scalyr_logging

global_log = scalyr_logging.getLogger(__name__)

_global_lock = threading.Lock()
_global_checkpoints = {}

def load_checkpoints( filename ):
    result = None
    _global_lock.acquire()
    try:
        if filename not in _global_checkpoints:
            checkpoints = {}
            try:
                checkpoints = scalyr_util.read_file_as_json( filename )
            except:
                global_log.log( scalyr_logging.DEBUG_LEVEL_1, "No checkpoint file '%s' exists.\n\tAll journald logs for '%s' will be read starting from their current end.", filename )
                checkpoints = {}

            result = Checkpoint( filename, checkpoints )
            _global_checkpoints[filename] = result
    finally:
        _global_lock.release()

    return result

class Checkpoint( object ):

    def __init__( self, filename, checkpoints ):
        self._lock = threading.Lock()
        self._filename = filename
        self._checkpoints = checkpoints

    def get_checkpoint( self, name ):

        result = None
        self._lock.acquire()
        try:
            result = self._checkpoints.get( name, None )
        finally:
            self._lock.release()

        return result

    def update_checkpoint( self, name, value ):
        self._lock.acquire()
        try:
            self._checkpoints[name] = value
            tmp_file = self._filename + '~'
            scalyr_util.atomic_write_dict_as_json_file( self._filename, tmp_file, self._checkpoints )
        finally:
            self._lock.release()

