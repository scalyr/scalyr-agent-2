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

import mock

from scalyr_agent.test_base import ScalyrTestCase

__all__ = ["AgentMainTestCase"]


class AgentMainTestCase(ScalyrTestCase):
    def test_create_client_ca_file_and_intermediate_certs_file_doesnt_exist(self):
        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        # 1. file doesn't exist but cer verification is disabled
        config = mock.Mock()
        config.scalyr_server = "foo.bar.com"

        config.verify_server_certificate = False
        config.ca_cert_path = "/tmp/doesnt.exist"

        agent = ScalyrAgent(PlatformController())
        agent._ScalyrAgent__config = config

        self.assertTrue(agent._ScalyrAgent__create_client())

        # ca_cert_path file doesn't exist
        config.verify_server_certificate = True
        config.ca_cert_path = "/tmp/doesnt.exist"

        agent = ScalyrAgent(PlatformController())
        agent._ScalyrAgent__config = config

        expected_msg = (
            r'Invalid path "/tmp/doesnt.exist" specified for the "ca_cert_path" config '
            "option: file does not exist"
        )
        self.assertRaisesRegexp(
            ValueError, expected_msg, agent._ScalyrAgent__create_client
        )

        # intermediate_certs_path file doesn't exist
        config.verify_server_certificate = True
        config.ca_cert_path = __file__
        config.intermediate_certs_path = "/tmp/doesnt.exist"

        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        agent = ScalyrAgent(PlatformController())
        agent._ScalyrAgent__config = config

        expected_msg = (
            r'Invalid path "/tmp/doesnt.exist" specified for the '
            '"intermediate_certs_path" config option: file does not exist'
        )
        self.assertRaisesRegexp(
            ValueError, expected_msg, agent._ScalyrAgent__create_client
        )
