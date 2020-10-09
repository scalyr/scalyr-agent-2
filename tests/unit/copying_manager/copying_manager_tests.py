from __future__ import absolute_import

import unittest


from tests.unit.copying_manager.cm import TestableCopyingManager
from tests.unit.copying_manager.config_builder import ConfigBuilder


class Test(unittest.TestCase):
    def test(self):
        config_builder = ConfigBuilder()

        config_builder.initialize()

        manager = TestableCopyingManager(config_builder.config, [])

        manager.start_manager()

        return
