import sys
import os

import pytest
import requests  # NOQA

from agent_build_refactored.tools.constants import SOURCE_ROOT

if __name__ == "__main__":
    # We use this file as an entry point for the pytest runner.
    sys.path.append(str(SOURCE_ROOT))

    os.chdir(SOURCE_ROOT)
    sys.exit(pytest.main())
