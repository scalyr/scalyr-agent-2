from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import

import pytest

from scalyr_agent.__scalyr__ import DEV_INSTALL
from tests.smoke_tests.common import _test_standalone_smoke


@pytest.mark.usefixtures("agent_environment")
@pytest.mark.timeout(300)
def test_standalone_smoke():
    _test_standalone_smoke(DEV_INSTALL)
