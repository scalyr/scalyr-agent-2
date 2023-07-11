import logging
import sys
import pathlib as pl

# Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.scripts.cicd import grouped_dependencies
from agent_build_refactored.tools.builder.builder_step import BuilderCacheMissError

logging.basicConfig(level=logging.INFO)


def main():
    for group in grouped_dependencies:
        for dep in group.values():
            dep.run_and_output_in_oci_tarball(
                fail_on_cache_miss=False,
                fail_on_children_cache_miss=False,
                verbose=False,
                verbose_children=False,
            )


if __name__ == '__main__':
    try:
        main()
    except BuilderCacheMissError:
        print("cache_miss")