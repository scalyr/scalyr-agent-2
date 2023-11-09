from scalyr_agent import ScalyrMonitor, define_config_option

__monitor__ = __name__

import six

define_config_option(
    __monitor__,
    "module",
    "Always `tests.unit.test_monitor`",
    convert_to=six.text_type,
    required_option=True,
)

define_config_option(
    __monitor__,
    "secure_url",
    "Considered secure",
    convert_to=six.text_type,
    required_option=True,
)

define_config_option(
    __monitor__,
    "insecure_url",
    "Considered insecure",
    convert_to=six.text_type,
    required_option=True,
    insecure_http_url=True
)

class TestMonitor(ScalyrMonitor):
    pass