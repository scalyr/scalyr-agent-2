import importlib
import argparse
import pathlib as pl
import sys
import logging

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent
# This file can be executed as script. Add source root to the PYTHONPATH in order to be able to import
# local packages. All such imports also have to be done after that.
sys.path.append(str(SOURCE_ROOT))

from agent_build_refactored.tools.builder import Builder, BUILDER_CLASSES, main as builder_main
from agent_build_refactored.tools.builder.builder_step import ALL_BUILDER_STEPS

logging.basicConfig()


# def run_builder(argv=None):
#     builder_cls = BUILDER_CLASSES[builder_name]
#
#     parser = argparse.ArgumentParser()
#
#     builder_cls.add_command_line_arguments(parser=parser)
#     args = parser.parse_args(args=argv)
#
#     builder_cls.create_and_run_builder_from_command_line(args=args)

if __name__ == '__main__':
    base_parser = argparse.ArgumentParser()
    base_parser.add_argument("type", choices=["builder", "builder_step"])
    base_parser.add_argument("fqdn")
    base_args, other_argv = base_parser.parse_known_args()

    fqdn = base_args.fqdn
    module_name, builder_name = fqdn.rsplit(".", 1)
    module = importlib.import_module(module_name)

    if base_args.type == "builder_step":
        builder_step = ALL_BUILDER_STEPS[fqdn]
        builder_step.run()
        exit(0)

    elif base_args.type == "builder":
        builder_main(
            builder_fqdn=fqdn,
            argv=other_argv,
        )
        exit(0)
