# Copyright 2014-2020 Scalyr Inc.
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

from __future__ import absolute_import

import hashlib

import six
import pytest
import orjson

from scalyr_agent.monitor_utils.k8s import PodInfo


MOCK_POD_INFO = PodInfo(
    name="loggen-58c5486566-fdmzf",
    namespace="default",
    uid="5ef12d19-d8e5-4280-9cdf-a80bae251c68",
    node_name="test-node",
    labels={
        "com.docker.compose.config-hash": "d90d71a3d6914cc78ee21692e36ee64f15a09481b13a312b0e04caac881b8b32",
        "com.docker.compose.container-number": "1",
        "com.docker.compose.oneoff": "False",
        "com.docker.compose.project": "stackstorm",
        "com.docker.compose.project.config_files": "docker-compose.yml",
        "com.docker.compose.project.working_dir": "/home/user/docker-compose/stackstorm",
        "com.docker.compose.service": "redis",
        "com.docker.compose.version": "1.25.0",
    },
    container_names=["random-logger"],
    annotations={
        "com.docker.compose.config-hash": "d90d71a3d6914cc78ee21692e36ee64f15a09481b13a312b0e04caac881b8b32",
        "com.docker.compose.container-number": "1",
        "com.docker.compose.oneoff": "False",
        "com.docker.compose.project": "stackstorm",
        "com.docker.compose.project.config_files": "docker-compose.yml",
        "com.docker.compose.project.working_dir": "/home/user/docker-compose/stackstorm",
        "com.docker.compose.service": "redis",
        "com.docker.compose.version": "1.25.0",
    },
    controller=None,
)


def _calculate_hash_digest_str_concat():
    md5 = hashlib.md5()
    md5.update(MOCK_POD_INFO.name.encode("utf-8"))
    md5.update(MOCK_POD_INFO.namespace.encode("utf-8"))
    md5.update(MOCK_POD_INFO.uid.encode("utf-8"))
    md5.update(MOCK_POD_INFO.node_name.encode("utf-8"))

    # flatten the labels dict in to a single string because update
    # expects a string arg.  To avoid cases where the 'str' of labels is
    # just the object id, we explicitly create a flattened string of
    # key/value pairs
    keys = sorted(MOCK_POD_INFO.labels.keys())
    flattened = []
    for key in keys:
        flattened.append(key)
        flattened.append(MOCK_POD_INFO.labels[key])
    md5.update("".join(flattened).encode("utf-8"))

    # flatten the container names
    # see previous comment for why flattening is necessary
    md5.update("".join(sorted(MOCK_POD_INFO.container_names)).encode("utf-8"))

    # flatten the annotations dict in to a single string
    # see previous comment for why flattening is necessary
    keys = sorted(MOCK_POD_INFO.annotations.keys())
    for key in keys:
        flattened.append(key)
        flattened.append(six.text_type(MOCK_POD_INFO.annotations[key]))

    md5.update("".join(flattened).encode("utf-8"))

    digest = md5.digest()
    return digest


def _calculate_hash_digest_orjson():
    md5 = hashlib.md5()
    md5.update(MOCK_POD_INFO.name.encode("utf-8"))
    md5.update(MOCK_POD_INFO.namespace.encode("utf-8"))
    md5.update(MOCK_POD_INFO.uid.encode("utf-8"))
    md5.update(MOCK_POD_INFO.node_name.encode("utf-8"))

    md5.update(orjson.dumps(MOCK_POD_INFO.labels, option=orjson.OPT_SORT_KEYS))

    # flatten the container names
    # see previous comment for why flattening is necessary
    md5.update(orjson.dumps(MOCK_POD_INFO.container_names, option=orjson.OPT_SORT_KEYS))

    md5.update(orjson.dumps(MOCK_POD_INFO.annotations, option=orjson.OPT_SORT_KEYS))

    digest = md5.digest()
    return digest


# fmt: off
@pytest.mark.parametrize(
    "approach",
    [
        "str_concat",
        "orjson",
    ],
    ids=[
        "str_concat",
        "orjson",
    ],
)
# fmt: on
def test_calculate_hash_digest(benchmark, approach):
    def run_benchmark():
        if approach == "str_concat":
            digest = _calculate_hash_digest_str_concat()
        else:
            digest = _calculate_hash_digest_orjson()
        return digest

    result = benchmark.pedantic(run_benchmark, iterations=100, rounds=500)
    assert isinstance(result, six.binary_type)
