import argparse
import sys
import logging
import pathlib as pl

logging.basicConfig(level=logging.INFO)


# Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.builder.builder_step import BuilderStep, CacheMissPolicy
from agent_build_refactored.scripts.cicd import all_dependencies

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("dependency_id", choices=all_dependencies.keys())

    args = parser.parse_args()

    dependency: BuilderStep = all_dependencies[args.dependency_id]

    dependency.run(
        on_cache_miss=CacheMissPolicy.FAIL,
        on_children_cache_miss=CacheMissPolicy.FAIL,
        enable_output=True,
        enable_children_output=False,
    )