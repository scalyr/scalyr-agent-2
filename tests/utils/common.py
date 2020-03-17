from __future__ import unicode_literals
from __future__ import absolute_import

import tempfile

from scalyr_agent import compat
from tests.utils.compat import Path

import six

TEMP_PREFIX = "scalyr-test-"


def get_env(name):
    try:
        return compat.os_environ_unicode[name]
    except KeyError:
        raise KeyError("Environment variable: '{0}' not set.".format(name))


def create_tmp_directory(suffix=""):
    # type: (six.text_type) -> Path
    path = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX, suffix="-" + suffix))
    return path


def create_tmp_file(suffix=""):
    # type: (six.text_type) -> Path
    tmp_file = tempfile.NamedTemporaryFile(prefix=TEMP_PREFIX, suffix="-" + suffix)
    tmp_file.close()
    return Path(tmp_file.name)
