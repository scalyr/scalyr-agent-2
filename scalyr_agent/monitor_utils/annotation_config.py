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

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "imron@scalyr.com"

import six

import re
import scalyr_agent.scalyr_logging as scalyr_logging
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonArray

global_log = scalyr_logging.getLogger(__name__)

SCALYR_ANNOTATION_PREFIX_RE = re.compile(r"^(log\.config\.scalyr\.com/)(.+)")
SCALYR_ANNOTATION_ELEMENT_RE = re.compile(r"([^.]+)\.(.+)")


class BadAnnotationConfig(Exception):
    pass


def process_annotations(
    annotations,
    annotation_prefix_re=SCALYR_ANNOTATION_PREFIX_RE,
    hyphens_as_underscores=False,
):
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

    # first split out any scalyr log-config annotations
    items = {}
    for annotation_key, annotation_value in six.iteritems(annotations):
        m = annotation_prefix_re.match(annotation_key)
        if m:
            key = m.group(2)
            if key in items:
                global_log.warn(
                    "Duplicate annotation key '%s' found in annotations.  Previous vaue was '%s'"
                    % (key, items[key]),
                    limit_once_per_x_secs=300,
                    limit_key="annotation_config_key-%s" % key,
                )
            else:
                items[key] = annotation_value

    return _process_annotation_items(items, hyphens_as_underscores)


def _is_int(string):
    """Returns true or false depending on whether or not the passed in string can be converted to an int"""
    try:
        int(string)
        result = True
    except ValueError:
        result = False

    return result


def _process_annotation_items(items, hyphens_as_underscores):
    """ Process annotation items after the scalyr config prefix has been stripped
    """

    def sort_annotation(pair):
        (key, value) = pair
        m = SCALYR_ANNOTATION_ELEMENT_RE.match(key)
        if m:
            root_key = m.group(1)
            # 2->TODO Python3 does not support mixed types sorting.
            #  One of the solutions is to keep all keys as strings, and sort them lexicographically.
            return root_key

        return key

    def sort_numeric(pair):
        (key, value) = pair
        if _is_int(key):
            return int(key)
        return key

    def normalize_key_name(key, convert_hyphens):
        """
        Normalizes the name of the key by converting any hyphens to underscores (or not)
        depending on the `convert_hyphens` parameter.
        Typically, `convert_hypens` will be false when converting k8s annotations because
        label and annotation keys in k8s can contain underscores.
        Keys for docker labels however cannot container underscores, therefore `convert_hyphens`
        can be used to convert any label keys to use underscores, which are expected by various
        log_config options.
        This function means the code that processes the labels/annotations doesn't need to care
        if it is running under docker or k8s, because the root caller decides whether or not hyphens
        need converting.
        @param key: string - a key for an annotation/label
        @param convert_hyphens: bool - if True, any hyphens in the `key` parameter will be
                converted to underscores
        """
        if convert_hyphens:
            key = key.replace("-", "_")
        return key

    result = {}

    # sort dict by the value of the first sub key (up to the first '.')
    # this ensures that all items of the same key are processed together
    sorted_items = sorted(six.iteritems(items), key=sort_annotation)

    current_object = None
    previous_key = None
    is_array = False
    is_object = False
    for (key, value) in sorted_items:

        # split out the sub key from the rest of the key
        m = SCALYR_ANNOTATION_ELEMENT_RE.match(key)
        if m:
            root_key = m.group(1)
            child_key = m.group(2)

            # check for mixed list and dict keys and raise an error if they exist
            if _is_int(root_key):
                is_array = True
            else:
                is_object = True

            if is_object == is_array:
                raise BadAnnotationConfig(
                    "Annotation cannot be both a dict and a list for '%s'.  Current key: %s, previous key: %s"
                    % (key, six.text_type(root_key), six.text_type(previous_key))
                )

            # create an empty object if None exists
            if current_object is None:
                current_object = {}

            # else if the keys are different which means we have a new key,
            # so add the current object to the list of results and create a new object
            elif previous_key is not None and root_key != previous_key:
                updated_key = normalize_key_name(previous_key, hyphens_as_underscores)
                result[updated_key] = _process_annotation_items(
                    current_object, hyphens_as_underscores
                )
                current_object = {}

            current_object[child_key] = value
            previous_key = root_key

        else:  # no more subkeys so just process as the full key

            # check for mixed list and dict keys and raise an error if they exist
            if _is_int(key):
                is_array = True
            else:
                is_object = True

            if is_object == is_array:
                raise BadAnnotationConfig(
                    "Annotation cannot be both a dict and a list.  Current key: %s, previous key: %s"
                    % (key, six.text_type(previous_key))
                )

            # if there was a previous key
            if previous_key is not None and current_object is not None:
                # stick it in the result
                updated_key = normalize_key_name(previous_key, hyphens_as_underscores)
                result[updated_key] = _process_annotation_items(
                    current_object, hyphens_as_underscores
                )

            # add the current value to the result
            updated_key = normalize_key_name(key, hyphens_as_underscores)
            result[updated_key] = value
            current_object = None
            previous_key = None

    # add the final object if there was one
    if previous_key is not None and current_object is not None:
        updated_key = normalize_key_name(previous_key, hyphens_as_underscores)
        result[updated_key] = _process_annotation_items(
            current_object, hyphens_as_underscores
        )

    # if the result should be an array, return values as a JsonArray, sorted by numeric order of keys
    if is_array:
        result = JsonArray(
            *[r[1] for r in sorted(six.iteritems(result), key=sort_numeric)]
        )
    else:
        # return values as a JsonObject
        result = JsonObject(content=result)

    return result
