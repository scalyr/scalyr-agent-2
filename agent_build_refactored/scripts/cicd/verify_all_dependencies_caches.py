import concurrent.futures
import logging
import sys
import pathlib as pl
import concurrent.futures

# Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(pl.Path(__file__).parent.parent.parent.parent))

from agent_build_refactored.tools.commin import init_logging
from agent_build_refactored.scripts.cicd import grouped_dependencies
from agent_build_refactored.tools.builder.builder_step import BuilderCacheMissError

init_logging()

def main():
    executor = concurrent.futures.ThreadPoolExecutor()
    for group in grouped_dependencies:
        futures = []
        for dep in group.values():

            future = executor.submit(
                dep.run_and_output_in_oci_tarball,
                fail_on_cache_miss=True,
                fail_on_children_cache_miss=True,
                verbose=False,
                verbose_children=False,
            )
            futures.append(future)

        for f in futures:
            f.result()


            # dep.run_and_output_in_oci_tarball(
            #     fail_on_cache_miss=True,
            #     fail_on_children_cache_miss=True,
            #     verbose=False,
            #     verbose_children=False,
            # )


if __name__ == '__main__':
    try:
        main()
    except BuilderCacheMissError:
        print("cache_miss")