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

from io import open

import mock

from scalyr_agent.__scalyr__ import DEV_INSTALL
from scalyr_agent.__scalyr__ import MSI_INSTALL
from scalyr_agent.test_base import ScalyrTestCase
from scalyr_agent import agent_main

__all__ = ["AgentMainTestCase"]

CORRECT_INIT_PRAGMA = """
### BEGIN INIT INFO
# Provides: scalyr-agent-2
# Required-Start: $network
# Required-Stop: $network
# Default-Start: 2 3 4 5
# Default-Stop: 0 1 6
# Description: Manages the Scalyr Agent 2, which provides log copying
#     and back system metric collection.
### END INIT INFO
"""


class AgentMainTestCase(ScalyrTestCase):
    @mock.patch("scalyr_agent.agent_main.INSTALL_TYPE", 1)
    def test_create_client_ca_file_and_intermediate_certs_file_doesnt_exist(self):
        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        # 1. file doesn't exist but cert verification is disabled
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

        agent = ScalyrAgent(PlatformController())
        agent._ScalyrAgent__config = config

        expected_msg = (
            r'Invalid path "/tmp/doesnt.exist" specified for the '
            '"intermediate_certs_path" config option: file does not exist'
        )

        self.assertRaisesRegexp(
            ValueError, expected_msg, agent._ScalyrAgent__create_client
        )

    def test_ca_cert_files_checks_are_skipped_under_dev_and_msi_install(self):
        # Skip those checks under dev and msi install because those final generated certs files
        # are not present under dev install
        import scalyr_agent.agent_main

        from scalyr_agent.agent_main import ScalyrAgent
        from scalyr_agent.platform_controller import PlatformController

        # 1. Dev install (boths checks should be skipped)
        scalyr_agent.agent_main.INSTALL_TYPE = DEV_INSTALL

        # ca_cert_path file doesn't exist
        config = mock.Mock()
        config.scalyr_server = "foo.bar.com"

        config.verify_server_certificate = True
        config.ca_cert_path = "/tmp/doesnt.exist"

        agent = ScalyrAgent(PlatformController())
        agent._ScalyrAgent__config = config

        self.assertTrue(agent._ScalyrAgent__create_client())

        # intermediate_certs_path file doesn't exist
        config.verify_server_certificate = True
        config.ca_cert_path = __file__
        config.intermediate_certs_path = "/tmp/doesnt.exist"

        self.assertTrue(agent._ScalyrAgent__create_client())

        # 2. MSI install (only intermediate_certs_path check should be skipped)
        scalyr_agent.agent_main.INSTALL_TYPE = MSI_INSTALL

        config = mock.Mock()
        config.scalyr_server = "foo.bar.com"

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

        self.assertTrue(agent._ScalyrAgent__create_client())

    def test_agent_main_file_contains_correct_init_pragma(self):
        """
        Verify that agent_main.py contains correct init.d comment. It's important that
        "BEGIN INIT INFO" and "END" line contains 3 # (###).

        sys-v is more forgiving and works if there are only two comment marks, but newer versions
        of systemd are not forgiving and don't work with it which means rc.d targets can't be
        created.
        """
        with open(agent_main.__file__, "r") as fp:
            content = fp.read()

        msg = (
            "agent_main.py doesn't contain correct init pragma comment. Make sure the comment "
            " is correct and contains thre leading ### on BEGIN and END lines."
        )
        self.assertTrue(CORRECT_INIT_PRAGMA in content, msg)
