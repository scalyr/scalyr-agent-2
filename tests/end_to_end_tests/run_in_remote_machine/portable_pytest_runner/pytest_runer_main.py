import argparse
import sys
import os
import tarfile
import tempfile

import pytest
import requests  # NOQA
import six # NOQA
import logging
import logging.handlers

#from agent_build_refactored.tools.constants import SOURCE_ROOT

if __name__ == "__main__":
    # We use this file as an entry point for the pytest runner.
    parser = argparse.ArgumentParser()
    parser.add_argument("source_tarball_path")

    args, other_argv = parser.parse_known_args()

    source_tarball_path = args.source_tarball_path
    temp_dir = tempfile.TemporaryDirectory("agent_e2e_test_source")

    source_root = temp_dir.name
    with tarfile.open(source_tarball_path, ":gz") as tar:
        tar.extractall(path=source_root)

    sys.path.append(str(source_root))

    os.chdir(source_root)

    exit_code = pytest.main(args=other_argv)
    temp_dir.cleanup()
    sys.exit(exit_code)
