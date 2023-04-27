import json
import sys
import pathlib as pl

SCRIPT_PATH = pl.Path(__file__).absolute()
SOURCE_ROOT = SCRIPT_PATH.parent.parent.parent.parent
sys.path.append(str(SOURCE_ROOT))

from tools.cicd.cacheable_steps import all_used_steps


if __name__ == '__main__':
    print(json.dumps(list(sorted(all_used_steps.keys()))))