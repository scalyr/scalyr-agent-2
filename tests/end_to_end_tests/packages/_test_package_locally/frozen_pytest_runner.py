import os
import sys
import pytest

import tests

from agent_build.tools.constants import SOURCE_ROOT

def resource_path(relative):
    """
    pyinstaller unpacks data into a temporary folder,
    and stores this directory path in the _MEIPASS environment variable.

    relative - name of the resource
    """
    try:
        if getattr(sys, 'frozen') and hasattr(sys, '_MEIPASS'):
            return os.path.join(sys._MEIPASS, relative)
    except:
        return os.path.join(os.path.abspath("."), relative)



# #raise RuntimeError(SOURCE_ROOT)
#
# print(list(SOURCE_ROOT.iterdir()))


original_cwd = os.getcwd()
os.chdir(SOURCE_ROOT)
try:
    sys.exit(pytest.main())
finally:
    os.chdir(original_cwd)
