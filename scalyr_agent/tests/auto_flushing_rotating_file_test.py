# Copyright 2017 Scalyr Inc.
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
# author: Imron Alston <imron@scalyr.com>

__author__ = 'imron@scalyr.com'

import unittest
import os
import shutil
import tempfile

from scalyr_agent.monitor_utils.auto_flushing_rotating_file import AutoFlushingRotatingFile

class AutoFlushingRotatingFileTestCase( unittest.TestCase ):

    def setUp(self):
        self._tempdir = tempfile.mkdtemp()
        self._path = os.path.join(self._tempdir, 'out.log')

    def tearDown(self):
        self._file.close()
        shutil.rmtree(self._tempdir)

    def dump_bytes( self, amount=100 ):
        for i in range( 0, amount, 1 ):
            self._file.write( "abcdefghi" )

    def test_no_rotation( self ):
        self._file = AutoFlushingRotatingFile( self._path )

        self.dump_bytes()

        file_size = os.path.getsize( self._path )
        self.assertEqual( 1000, file_size )

    def test_no_rotation_but_max_bytes( self ):
        self._file = AutoFlushingRotatingFile( self._path, max_bytes=500 )
        self.dump_bytes()
        file_size = os.path.getsize( self._path )
        self.assertEqual( 1000, file_size )

    def test_append_existing( self ):
        self._file = AutoFlushingRotatingFile( self._path )
        self.dump_bytes()
        self._file.close()

        self._file = AutoFlushingRotatingFile( self._path )
        self.dump_bytes()

        file_size = os.path.getsize( self._path )
        self.assertEqual( 2000, file_size )

    def test_single_rotation( self ):
        self._file = AutoFlushingRotatingFile( self._path, max_bytes=200, backup_count=1 )
        self.dump_bytes()
        file_size = os.path.getsize( self._path )
        self.assertEqual( 200, file_size )

        file_size = os.path.getsize( "%s.1" % self._path )
        self.assertEqual( 200, file_size )

        self.assertEqual( False, os.path.exists( "%s.2" % self._path ) )

    def test_multi_rotation( self ):
        self._file = AutoFlushingRotatingFile( self._path, max_bytes=200, backup_count=3 )
        self.dump_bytes()
        file_size = os.path.getsize( self._path )
        self.assertEqual( 200, file_size )

        for i in range( 1, 4, 1 ):
            file_size = os.path.getsize( "%s.%d" % (self._path, i) )
            self.assertEqual( 200, file_size )

        self.assertEqual( False, os.path.exists( "%s.4" % self._path ) )

