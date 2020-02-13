import tempfile
from pathlib import Path
import shutil
import os


def get_env(name):
    try:
        os.environ[name]
    except KeyError:
        raise KeyError("Environment variable: '{}' not set.".format(name))


def create_temp_dir(prefix="scalyr_agent_testing"):
    return tempfile.TemporaryDirectory(prefix=prefix)


def create_temp_dir_with_constant_name(name=".scalyr_agent_testing"):
    # type: (str) -> Path
    """
    Create temporary directory but with constant name.
    :param name: tmp directory name.
    :return: path object to new tmp directory.
    """
    tmp_dir_path = Path(tempfile.gettempdir()) / name
    if tmp_dir_path.exists():
        shutil.rmtree(tmp_dir_path)
    tmp_dir_path.mkdir()

    return tmp_dir_path


def create_temp_named_file(mode, prefix="scalyr_test_"):
    return tempfile.NamedTemporaryFile(mode, prefix="scalyr_test_", suffix=".file")
