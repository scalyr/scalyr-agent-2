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

from __future__ import unicode_literals
from __future__ import absolute_import

__author__ = "imron@scalyr.com"

from scalyr_agent.monitor_utils.annotation_config import process_annotations

from scalyr_agent.test_base import ScalyrTestCase

import re


class TestAnnotationConfig(ScalyrTestCase):
    def test_invalid_annotations(self):

        annotations = {
            "some.other.value": 10,
            "not.a.scalyr.annotation": "no it's not",
        }

        result = process_annotations(annotations)

        self.assertEquals(0, len(list(result.keys())))

    def test_annotation_object(self):
        annotations = {
            "log.config.scalyr.com/item1": "item1",
            "log.config.scalyr.com/item2": "item2",
            "log.config.scalyr.com/item3": "item3",
        }

        result = process_annotations(annotations)
        self.assertEquals(3, len(list(result.keys())))
        self.assertEquals("item1", result["item1"])
        self.assertEquals("item2", result["item2"])
        self.assertEquals("item3", result["item3"])

    def test_annotation_nested_object(self):
        annotations = {
            "log.config.scalyr.com/item1.nest1": "item1 nest1",
            "log.config.scalyr.com/item1.nest2": "item1 nest2",
            "log.config.scalyr.com/item1.nest3": "item1 nest3",
            "log.config.scalyr.com/item2.nest1": "item2 nest1",
            "log.config.scalyr.com/item2.nest2": "item2 nest2",
            "log.config.scalyr.com/item2.nest3": "item2 nest3",
            "log.config.scalyr.com/item2.nest4": "item2 nest4",
        }

        result = process_annotations(annotations)
        self.assertEquals(2, len(list(result.keys())))
        self.assertEquals(3, len(result["item1"]))
        self.assertEquals(4, len(result["item2"]))

        self.assertEquals("item1 nest1", result["item1"]["nest1"])
        self.assertEquals("item1 nest2", result["item1"]["nest2"])
        self.assertEquals("item1 nest3", result["item1"]["nest3"])

        self.assertEquals("item2 nest1", result["item2"]["nest1"])
        self.assertEquals("item2 nest2", result["item2"]["nest2"])
        self.assertEquals("item2 nest3", result["item2"]["nest3"])
        self.assertEquals("item2 nest4", result["item2"]["nest4"])

    def test_annotation_array(self):
        annotations = {
            "log.config.scalyr.com/item1.20": "item1 element 2",
            "log.config.scalyr.com/item1.0": "item1 element 0",
            "log.config.scalyr.com/item1.10": "item1 element 1",
            "log.config.scalyr.com/item2.0": "item2 element 0",
            "log.config.scalyr.com/item2.1": "item2 element 1",
            "log.config.scalyr.com/item2.2": "item2 element 2",
            "log.config.scalyr.com/item2.3": "item2 element 3",
        }

        result = process_annotations(annotations)
        self.assertEquals(2, len(list(result.keys())))
        self.assertEquals(3, len(result["item1"]))
        self.assertEquals(4, len(result["item2"]))

        self.assertEquals("item1 element 0", result["item1"][0])
        self.assertEquals("item1 element 1", result["item1"][1])
        self.assertEquals("item1 element 2", result["item1"][2])

        self.assertEquals("item2 element 0", result["item2"][0])
        self.assertEquals("item2 element 1", result["item2"][1])
        self.assertEquals("item2 element 2", result["item2"][2])
        self.assertEquals("item2 element 3", result["item2"][3])

    def test_annotation_keys_with_hyphens(self):
        annotations = {
            "com.scalyr.config.log.item1-1.element-1": "item1 element 1",
            "com.scalyr.config.log.item1-2.element-2": "item1 element 2",
            "com.scalyr.config.log.item1-3.element-3": "item1 element 3",
            "com.scalyr.config.log.item2-1.element-1": "item2 element 1",
            "com.scalyr.config.log.item2-2.element-2": "item2 element 2",
            "com.scalyr.config.log.item2-3.element-3": "item2 element 3",
        }

        result = process_annotations(
            annotations,
            annotation_prefix_re=re.compile("^(com\.scalyr\.config\.log\.)(.+)"),
            hyphens_as_underscores=True,
        )

        self.assertEquals("item1 element 1", result["item1_1"]["element_1"])
        self.assertEquals("item1 element 2", result["item1_2"]["element_2"])
        self.assertEquals("item1 element 3", result["item1_3"]["element_3"])
        self.assertEquals("item2 element 1", result["item2_1"]["element_1"])
        self.assertEquals("item2 element 2", result["item2_2"]["element_2"])
        self.assertEquals("item2 element 3", result["item2_3"]["element_3"])
