# Copyright 2018 Scalyr Inc.
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

from scalyr_agent.monitor_utils.annotation_config import process_annotations
from scalyr_agent import json_lib
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonArray

from scalyr_agent.test_base import ScalyrTestCase

class TestAnnotationConfig(ScalyrTestCase):

    def test_invalid_annotations( self ):

        annotations = {
            "some.other.value": 10,
            "not.a.scalyr.annotation": "no it's not",
        }

        result = process_annotations( annotations )

        self.assertEquals( 0, len( result.keys() ) )
                
    def test_annotation_object( self ):
        annotations = {
            "log.config.scalyr.com/item1" : "item1",
            "log.config.scalyr.com/item2" : "item2",
            "log.config.scalyr.com/item3" : "item3"
        }

        result = process_annotations( annotations )
        self.assertEquals( 3, len( result.keys() ) )
        self.assertEquals( 'item1', result['item1'] )
        self.assertEquals( 'item2', result['item2'] )
        self.assertEquals( 'item3', result['item3'] )

    def test_annotation_nested_object( self ):
        annotations = {
            "log.config.scalyr.com/item1.nest1" : "item1 nest1",
            "log.config.scalyr.com/item1.nest2" : "item1 nest2",
            "log.config.scalyr.com/item1.nest3" : "item1 nest3",
            "log.config.scalyr.com/item2.nest1" : "item2 nest1",
            "log.config.scalyr.com/item2.nest2" : "item2 nest2",
            "log.config.scalyr.com/item2.nest3" : "item2 nest3",
            "log.config.scalyr.com/item2.nest4" : "item2 nest4"
        }

        result = process_annotations( annotations )
        self.assertEquals( 2, len( result.keys() ) )
        self.assertEquals( 3, len( result['item1'] ) )
        self.assertEquals( 4, len( result['item2'] ) )

        self.assertEquals( 'item1 nest1', result['item1']['nest1'] )
        self.assertEquals( 'item1 nest2', result['item1']['nest2'] )
        self.assertEquals( 'item1 nest3', result['item1']['nest3'] )

        self.assertEquals( 'item2 nest1', result['item2']['nest1'] )
        self.assertEquals( 'item2 nest2', result['item2']['nest2'] )
        self.assertEquals( 'item2 nest3', result['item2']['nest3'] )
        self.assertEquals( 'item2 nest4', result['item2']['nest4'] )
        
    def test_annotation_array( self ):
        annotations = {
            "log.config.scalyr.com/item1.20" : "item1 element 2",
            "log.config.scalyr.com/item1.0" : "item1 element 0",
            "log.config.scalyr.com/item1.10" : "item1 element 1",
            "log.config.scalyr.com/item2.0" : "item2 element 0",
            "log.config.scalyr.com/item2.1" : "item2 element 1",
            "log.config.scalyr.com/item2.2" : "item2 element 2",
            "log.config.scalyr.com/item2.3" : "item2 element 3",
        }

        result = process_annotations( annotations )
        self.assertEquals( 2, len( result.keys() ) )
        self.assertEquals( 3, len( result['item1'] ) )
        self.assertEquals( 4, len( result['item2'] ) )

        self.assertEquals( 'item1 element 0', result['item1'][0] )
        self.assertEquals( 'item1 element 1', result['item1'][1] )
        self.assertEquals( 'item1 element 2', result['item1'][2] )

        self.assertEquals( 'item2 element 0', result['item2'][0] )
        self.assertEquals( 'item2 element 1', result['item2'][1] )
        self.assertEquals( 'item2 element 2', result['item2'][2] )
        self.assertEquals( 'item2 element 3', result['item2'][3] )

