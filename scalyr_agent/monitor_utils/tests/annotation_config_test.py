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

import scalyr_agent.monitor_utils.annotation_config as annotation_config
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonArray
from scalyr_agent.test_base import ScalyrTestCase


class TestAnnotationConfig(ScalyrTestCase):
    def setUp(self):
        pass

    def test_plain_values(self):
        annotations = {
            "log.config.scalyr.com/someKey": "someValue",
            "log.config.scalyr.com/log_path": "/var/log/access.log",
            "log.config.scalyr.com/important_field": "important_value",
        }

        result = annotation_config.process_annotations( annotations )

        self.assertEquals( 3, len( result ) )

        self.assertTrue( 'someKey' in result )
        self.assertTrue( 'log_path' in result )
        self.assertTrue( 'important_field' in result )

        self.assertEquals( "someValue", result['someKey'] )
        self.assertEquals( "/var/log/access.log", result['log_path'] )
        self.assertEquals( "important_value", result['important_field'] )

    def test_dict_values(self):
        annotations = {
            "log.config.scalyr.com/attributes.parser": "accessLog",
            "log.config.scalyr.com/attributes.container": "my-container",
            "log.config.scalyr.com/attributes.amazing": "yes it is",
            "log.config.scalyr.com/rename_logfile.match": "/var/log/(.*).log",
            "log.config.scalyr.com/rename_logfile.replacement": "/scalyr/\\1.log",
        }

        result = annotation_config.process_annotations( annotations )

        self.assertEquals( 2, len( result ) )

        self.assertTrue( 'attributes' in result )
        self.assertTrue( 'rename_logfile' in result )

        attrs = result['attributes']
        self.assertEquals( 3, len( attrs ) )

        self.assertTrue( 'parser' in attrs )
        self.assertTrue( 'container' in attrs )
        self.assertTrue( 'amazing' in attrs )

        self.assertEquals( "accessLog", attrs['parser'] )
        self.assertEquals( "my-container", attrs['container'] )
        self.assertEquals( "yes it is", attrs['amazing'] )
    
    def test_list_value(self):
        annotations = {
            "log.config.scalyr.com/3": "three",
            "log.config.scalyr.com/2": "two",
            "log.config.scalyr.com/1": "one",
        }

        result = annotation_config.process_annotations( annotations )

        self.assertTrue( isinstance( result, JsonArray ) )
        self.assertEqual( 3, len( result ) )
        self.assertEqual( 'one', result[0] )
        self.assertEqual( 'two', result[1] )
        self.assertEqual( 'three', result[2] )
        

    def test_list_of_dicts(self):

        annotations = {
            "log.config.scalyr.com/10.match_expression": "fourth",
            "log.config.scalyr.com/10.sampling_rate": 4,
            "log.config.scalyr.com/2.match_expression": "third",
            "log.config.scalyr.com/2.sampling_rate": 3,
            "log.config.scalyr.com/0.match_expression": "first",
            "log.config.scalyr.com/0.sampling_rate": 1,
            "log.config.scalyr.com/1.match_expression": "second",
            "log.config.scalyr.com/1.sampling_rate": 2
        }

        result = annotation_config.process_annotations( annotations )

        self.assertEquals( 4, len( result ) )
        self.assertTrue( isinstance( result, JsonArray ) )

        self.assertEquals( "first", result[0]['match_expression'] )
        self.assertEquals( 1, result[0]['sampling_rate'] )
   
        self.assertEquals( "second", result[1]['match_expression'] )
        self.assertEquals( 2, result[1]['sampling_rate'] )
   
        self.assertEquals( "third", result[2]['match_expression'] )
        self.assertEquals( 3, result[2]['sampling_rate'] )
   
        self.assertEquals( "fourth", result[3]['match_expression'] )
        self.assertEquals( 4, result[3]['sampling_rate'] )

    def test_dict_with_list(self):

        annotations = {
            "log.config.scalyr.com/rules.10.match_expression": "fourth",
            "log.config.scalyr.com/rules.10.sampling_rate": 4,
            "log.config.scalyr.com/rules.2.match_expression": "third",
            "log.config.scalyr.com/rules.2.sampling_rate": 3,
            "log.config.scalyr.com/rules.0.match_expression": "first",
            "log.config.scalyr.com/rules.0.sampling_rate": 1,
            "log.config.scalyr.com/rules.1.match_expression": "second",
            "log.config.scalyr.com/rules.1.sampling_rate": 2
        }

        result = annotation_config.process_annotations( annotations )

        self.assertEquals( 1, len( result ) )
        result = result['rules']

        self.assertEquals( 4, len( result ) )
        self.assertTrue( isinstance( result, JsonArray ) )

        self.assertEquals( "first", result[0]['match_expression'] )
        self.assertEquals( 1, result[0]['sampling_rate'] )
   
        self.assertEquals( "second", result[1]['match_expression'] )
        self.assertEquals( 2, result[1]['sampling_rate'] )
   
        self.assertEquals( "third", result[2]['match_expression'] )
        self.assertEquals( 3, result[2]['sampling_rate'] )
   
        self.assertEquals( "fourth", result[3]['match_expression'] )
        self.assertEquals( 4, result[3]['sampling_rate'] )
        self.assertEquals( 4, result[3]['sampling_rate'] )

    def test_list_of_lists(self):

        annotations = {
            "log.config.scalyr.com/2.10.match_expression": "fourth",
            "log.config.scalyr.com/2.10.sampling_rate": 4,
            "log.config.scalyr.com/2.2.match_expression": "third",
            "log.config.scalyr.com/2.2.sampling_rate": 3,
            "log.config.scalyr.com/1.0.match_expression": "first",
            "log.config.scalyr.com/1.0.sampling_rate": 1,
            "log.config.scalyr.com/1.1.match_expression": "second",
            "log.config.scalyr.com/1.1.sampling_rate": 2
        }

        #import pdb; pdb.set_trace()
        result = annotation_config.process_annotations( annotations )

        self.assertEquals( 2, len( result ) )
        first = result[0]

        self.assertEquals( 2, len( first ) )
        self.assertTrue( isinstance( first, JsonArray ) )

        self.assertEquals( "first", first[0]['match_expression'] )
        self.assertEquals( 1, first[0]['sampling_rate'] )
   
        self.assertEquals( "second", first[1]['match_expression'] )
        self.assertEquals( 2, first[1]['sampling_rate'] )

        second = result[1]
        self.assertEquals( 2, len( second ) )
        self.assertTrue( isinstance( second, JsonArray ) )
   
        self.assertEquals( "third", second[0]['match_expression'] )
        self.assertEquals( 3, second[0]['sampling_rate'] )
   
        self.assertEquals( "fourth", second[1]['match_expression'] )
        self.assertEquals( 4, second[1]['sampling_rate'] )
   
    def test_mixed_list_and_dict_key(self):
        annotations = {
            "log.config.scalyr.com/test.2.match_expression": "third",
            "log.config.scalyr.com/test.2.sampling_rate": 3,
            "log.config.scalyr.com/test.bad.match_expression": "first",
            "log.config.scalyr.com/test.bad.sampling_rate": 1,
            "log.config.scalyr.com/test.1.match_expression": "second",
            "log.config.scalyr.com/test.1.sampling_rate": 2
        }

        self.assertRaises(annotation_config.BadAnnotationConfig, lambda: annotation_config.process_annotations( annotations ) )
        
    def test_full_config(self):
        annotations = {
            "log.config.scalyr.com/path": "/some/path.log",
            "log.config.scalyr.com/attributes.parser": "accessLog",
            "log.config.scalyr.com/attributes.service": "memcache",
            "log.config.scalyr.com/sampling_rules.10.match_expression": "10-INFO",
            "log.config.scalyr.com/sampling_rules.10.sampling_rate": 10,
            "log.config.scalyr.com/sampling_rules.2.match_expression": "2-INFO",
            "log.config.scalyr.com/sampling_rules.2.sampling_rate": 2,
            "log.config.scalyr.com/line_groupers.4.start": "start4",
            "log.config.scalyr.com/line_groupers.4.continueThrough": "continueThrough",
            "log.config.scalyr.com/line_groupers.3.start": "start3",
            "log.config.scalyr.com/line_groupers.3.continuePast": "continuePast",
            "log.config.scalyr.com/line_groupers.2.start": "start2",
            "log.config.scalyr.com/line_groupers.2.haltBefore": "haltBefore",
            "log.config.scalyr.com/line_groupers.1.start": "start1",
            "log.config.scalyr.com/line_groupers.1.haltWith": "haltWith",
            "log.config.scalyr.com/exclude.1": "exclude1",
            "log.config.scalyr.com/exclude.2": "exclude2",
            "log.config.scalyr.com/exclude.3": "exclude3",
            "log.config.scalyr.com/rename_logfile.match": "rename",
            "log.config.scalyr.com/rename_logfile.replacement": "renamed",
            "log.config.scalyr.com/redaction_rules.1.match_expression": "redacted1",
            "log.config.scalyr.com/redaction_rules.2.match_expression": "redacted2",
            "log.config.scalyr.com/redaction_rules.2.replacement": "replaced2",
            "log.config.scalyr.com/redaction_rules.3.match_expression": "redacted3",
            "log.config.scalyr.com/redaction_rules.3.replacement": "replaced3",
            "log.config.scalyr.com/redaction_rules.3.hash_salt": "salt3",

        }

        result = annotation_config.process_annotations( annotations )

        self.assertEquals( 7, len( result ) )

        self.assertTrue( 'path' in result )
        self.assertTrue( 'attributes' in result )
        self.assertTrue( 'sampling_rules' in result )
        self.assertTrue( 'line_groupers' in result )
        self.assertTrue( 'exclude' in result )
        self.assertTrue( 'rename_logfile' in result )
        self.assertTrue( 'redaction_rules' in result )

        attrs = result['attributes']
        self.assertTrue( isinstance( attrs, JsonObject ) )
        self.assertEquals( 2, len( attrs ) )
        self.assertTrue( 'parser' in attrs )
        self.assertTrue( 'service' in attrs )
        self.assertEquals( 'accessLog', attrs['parser'] )
        self.assertEquals( 'memcache', attrs['service'] )

        sampling = result['sampling_rules']
        self.assertTrue( isinstance( sampling, JsonArray ) )
        self.assertEqual( 2, len( sampling ) )

        self.assertEqual( '2-INFO', sampling[0]['match_expression'] )
        self.assertEqual( 2, sampling[0]['sampling_rate'] )
        self.assertEqual( '10-INFO', sampling[1]['match_expression'] )
        self.assertEqual( 10, sampling[1]['sampling_rate'] )

        groupers = result['line_groupers']
        self.assertTrue( isinstance( groupers, JsonArray ) )
        self.assertEqual( 4, len( groupers ) )

        self.assertEqual( 'start1', groupers[0]['start'] )
        self.assertEqual( 'haltWith', groupers[0]['haltWith'] )
        self.assertEqual( 'start2', groupers[1]['start'] )
        self.assertEqual( 'haltBefore', groupers[1]['haltBefore'] )
        self.assertEqual( 'start3', groupers[2]['start'] )
        self.assertEqual( 'continuePast', groupers[2]['continuePast'] )
        self.assertEqual( 'start4', groupers[3]['start'] )
        self.assertEqual( 'continueThrough', groupers[3]['continueThrough'] )

        exclude = result['exclude']
        self.assertTrue( isinstance( exclude, JsonArray ) )
        self.assertEqual( 3, len( exclude ) )

        self.assertEqual( 'exclude1', exclude[0] )
        self.assertEqual( 'exclude2', exclude[1] )
        self.assertEqual( 'exclude3', exclude[2] )

        rename = result['rename_logfile']
        self.assertTrue( isinstance( rename, JsonObject ) )

        self.assertEqual( 'rename', rename['match'] )
        self.assertEqual( 'renamed', rename['replacement'] )

        redaction = result['redaction_rules']
        self.assertTrue( isinstance( exclude, JsonArray ) )
        self.assertEqual( 3, len( exclude ) )

        self.assertEqual( 'redacted1', redaction[0]['match_expression'] )
        self.assertEqual( 'redacted2', redaction[1]['match_expression'] )
        self.assertEqual( 'replaced2', redaction[1]['replacement'] )
        self.assertEqual( 'redacted3', redaction[2]['match_expression'] )
        self.assertEqual( 'replaced3', redaction[2]['replacement'] )
        self.assertEqual( 'salt3', redaction[2]['hash_salt'] )




    def test_no_scalyr_annotations(self):
        
        annotations = {
            "config.agent.not-scalyr.com/attributes.parser": "accessLog",
            "config.agent.not-scalyr.com/log_path": "/var/log/access.log",
            "config.agent.not-scalyr.com/sampling_rules.0.match_expression": "INFO",
            "config.agent.not-scalyr.com/sampling_rules.0.sampling_rate": 0.1,
        }

        result = annotation_config.process_annotations( annotations )
        self.assertFalse( result )


