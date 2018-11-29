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
# author:  Imron Alston <imron@scalyr.com>

__author__ = 'imron@scalyr.com'

import re
import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonArray

global_log = scalyr_logging.getLogger(__name__)

SCALYR_LOG_ANNOTATION_RE = re.compile( '^(log\.config\.scalyr\.com/)(.+)' )
SCALYR_ANNOTATION_ELEMENT_RE = re.compile( '([^.]+)\.(.+)' )

class BadAnnotationConfig( Exception ):
    pass


def process_annotations( annotations ):
    """
    Process the annotations, extracting log.config.scalyr.com/* entries
    and mapping them to a dict corresponding to the same names as the log_config
    entries.
    Items separated by a period are mapped to dict keys e.g. if the annotation was
    specified as:

      log.config.scalyr.com/attributes.parser: accessLog

    it would be mapped to a dict

    result = {
        "attributes": {
            "parser": "accessLog"
        }
    }

    Arrays can be specified by using one or more digits as the key, e.g. if the annotation was

      log.config.scalyr.com/sampling_rules.0.match_expression: INFO
      log.config.scalyr.com/sampling_rules.0.sampling_rate: 0.1
      log.config.scalyr.com/sampling_rules.1.match_expression: FINE
      log.config.scalyr.com/sampling_rules.1.sampling_rate: 0

    This will be mapped to the following structure:

    result = {
        "sampling_rules": [
            {
                "match_expression": "INFO",
                "sampling_rate": 0.1
            },
            {
                "match_expression": "FINE",
                "sampling_rate": 0
            }
        ]
    }

    Array keys are sorted by numeric order before processing and unique objects need to have
    different digits as the array key. If a sub-key has an identical array key as a previously
    seen sub-key, then the previous value of the sub-key is overwritten, For example the
    annotations

      log.config.scalyr.com/sampling_rules.0.match_expression: INFO
      log.config.scalyr.com/sampling_rules.0.sampling_rate: 0.1
      log.config.scalyr.com/sampling_rules.0.match_expression: FINE
      log.config.scalyr.com/sampling_rules.0.sampling_rate: 0

    Would produce the following result

      {
        "match_expression": "FINE",
        "sampling_rate": 0
      }

    because the initial match_expression and sampling_rate are overwritten by the later one.

    There is no guarantee about the order of processing for items with the same numeric array
    key, so:

      log.config.scalyr.com/sampling_rules.0.match_expression: INFO
      log.config.scalyr.com/sampling_rules.0.sampling_rate: 0.1
      log.config.scalyr.com/sampling_rules.0.match_expression: FINE
      log.config.scalyr.com/sampling_rules.0.sampling_rate: 0

    might produce:

      {
        "match_expression": "FINE",
        "sampling_rate": 0
      }

    or it might produce:

      {
        "match_expression": "INFO",
        "sampling_rate": 0.1
      }

    or it might produce:

      {
        "match_expression": "FINE",
        "sampling_rate": 0.1
      }

    or it might produce:

      {
        "match_expression": "INFO",
        "sampling_rate": 0
      }

    """

    result = {}

    # first split out any scalyr log-config annotations
    items = {}
    for annotation_key, annotation_value in annotations.iteritems():
        m = SCALYR_LOG_ANNOTATION_RE.match( annotation_key )
        if m:
            key = m.group(2)
            if key in items:
                global_log.warn( "Duplicate annotation key '%s' found in annotations.  Previous vaue was '%s'" % (key, items[key]),
                                 limit_once_per_x_secs=300, limit_key='annotation_config_key-%s' % key )
            else:
                items[key] = annotation_value

    return _process_annotation_items( items )

def _is_int( string ):
    """Returns true or false depending on whether or not the passed in string can be converted to an int"""
    result = False
    try:
        value = int( string )
        result = True
    except ValueError:
        result = False
   
    return result

def _process_annotation_items( items ):
    """ Process annotation items after the scalyr config prefix has been stripped
    """
    result = {}
    def sort_annotation( pair ):
        (key, value) = pair
        m = SCALYR_ANNOTATION_ELEMENT_RE.match( key )
        if m:
            root_key = m.group(1)
            if _is_int( root_key ):
                return int( root_key )
            return root_key
        
        return key

    def sort_numeric( pair ):
        (key, value) = pair
        if _is_int( key ):
            return int( key )
        return key
            
    # sort dict by the value of the first sub key (up to the first '.')
    # this ensures that all items of the same key are processed together
    sorted_items = sorted( items.iteritems(), key=sort_annotation) 
    
    current_object = None
    previous_key = None
    is_array = False
    is_object = False
    for (key, value) in sorted_items:

        # split out the sub key from the rest of the key
        m = SCALYR_ANNOTATION_ELEMENT_RE.match( key )
        if m:
            root_key = m.group(1)
            child_key = m.group(2)

            # check for mixed list and dict keys and raise an error if they exist
            if _is_int( root_key ):
                is_array = True
            else:
                is_object = True

            if is_object == is_array:
                raise BadAnnotationConfig( "Annotation cannot be both a dict and a list for '%s'.  Current key: %s, previous key: %s" % (key, str(root_key), str(previous_key)) )

            # create an empty object if None exists
            if current_object is None:
                current_object = {}

            # else if the keys are different which means we have a new key,
            # so add the current object to the list of results and create a new object
            elif previous_key is not None and root_key != previous_key:
                result[previous_key] = _process_annotation_items( current_object )
                current_object = {}

            current_object[child_key] = value
            previous_key = root_key

        else: # no more subkeys so just process as the full key

            # check for mixed list and dict keys and raise an error if they exist
            if _is_int( key ):
                is_array = True
            else:
                is_object = True

            if is_object == is_array:
                raise BadAnnotationConfig( "Annotation cannot be both a dict and a list.  Current key: %s, previous key: %s" % (key, str(previous_key)) )

            # if there was a previous key 
            if previous_key is not None and current_object is not None:
                # stick it in the result
                result[previous_key] = _process_annotation_items( current_object )

            # add the current value to the result
            result[key] = value
            current_object = None
            previous_key = None

    # add the final object if there was one
    if previous_key is not None and current_object is not None:
        result[previous_key] = _process_annotation_items( current_object )

    # if the result should be an array, return values as a JsonArray, sorted by numeric order of keys
    if is_array:
        result = JsonArray( *[r[1] for r in sorted( result.iteritems(), key=sort_numeric )] )
    else:
    # return values as a JsonObject
        result = JsonObject( content=result )

    return result
