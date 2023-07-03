import argparse
import importlib.util

a=10
if __name__ == '__main__':
    base_parser = argparse.ArgumentParser()
    base_parser.add_argument("fqdn")
    base_args, other_argv = base_parser.parse_known_args()

    module_name, builder_name = base_args.fqdn.rsplit(".", 1)
    #spec = importlib.util.spec_from_file_location(module_name, file_path)
    # print("MODULE_NAME", module_name)
    # print("NAMEEEE", builder_name)
    module = importlib.import_module(module_name)

    from agent_build_refactored.tools.builder import Builder, BUILDER_CLASSES


    builder_cls = BUILDER_CLASSES[builder_name]

    parser = argparse.ArgumentParser()

    builder_cls.add_command_line_arguments(parser=parser)
    args = parser.parse_args(args=other_argv)

    builder = builder_cls.create_and_run_builder_from_command_line(args=args)






