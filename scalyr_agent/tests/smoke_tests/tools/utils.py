import tempfile
import shutil
import os

from .compat import Path

from scalyr_agent.__scalyr__ import get_package_root

import six

def get_env(name):
    try:
        return os.environ[name]
    except KeyError:
        raise KeyError("Environment variable: '{}' not set.".format(name))


def create_temp_dir(prefix="scalyr_agent_testing"):
    return tempfile.TemporaryDirectory(prefix=prefix)


def create_temp_dir_with_constant_name(name):
    # type: (six.text_type) -> Path
    """
    Create temporary directory but with constant name.
    :param name: tmp directory name.
    :return: path object to new tmp directory.
    """
    tmp_dir_path = Path(tempfile.gettempdir()) / name
    if tmp_dir_path.exists():
        shutil.rmtree(six.text_type(tmp_dir_path), ignore_errors=True)
    tmp_dir_path.mkdir(exist_ok=True)

    return tmp_dir_path


def create_temp_named_file(mode, prefix="scalyr_test_"):
    return tempfile.NamedTemporaryFile(mode, prefix="scalyr_test_", suffix=".file")


def copy_agent_source(dest_path):
    root_path = Path(get_package_root()).parent
    shutil.copytree(
        six.text_type(root_path),
        six.text_type(dest_path),
        ignore=shutil.ignore_patterns(
            "*.pyc",
            "__pycache__",
            "*.egg-info",
            ".tox",
            ".pytest*",
            ".mypy*",
            ".idea",
            ".git"
        ),
    )