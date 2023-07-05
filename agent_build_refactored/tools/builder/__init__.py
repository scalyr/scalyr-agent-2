import abc
import dataclasses
import importlib
import json
import logging
import pathlib as pl
import argparse
import re
import shlex
import shutil
import subprocess
import sys
from typing import Dict, List, Union, Type

from agent_build_refactored.tools.builder.builder_step import BuilderStep
from agent_build_refactored.tools.builder.builder_step import \
    RemoteBuildxBuilderWrapper, BuilderCacheMissError, BuilderStep, CachePolicy

from agent_build_refactored.tools.constants import SOURCE_ROOT, AGENT_BUILD_OUTPUT_PATH


def docker_build_or_stop_on_cache_miss(
        cmd_args: List[str],
        input: bytes,
):

    if input:
        stdin = subprocess.PIPE
    else:
        stdin = None

    process = subprocess.Popen(
        [
            *cmd_args,
        ],
        stderr=subprocess.PIPE,
        stdin=stdin
    )

    if input:
        process.stdin.write(input)

    all_lines = []

    def _real_line(decode_errors="strict"):
        raw_line = process.stderr.readline().decode(
            errors=decode_errors
        )

        if not raw_line:
            return None

        stripped_line = raw_line.strip()

        all_lines.append(stripped_line)

        return stripped_line

    def _check_if_run_command_is_missed_cache(line: str):
        if line == f"#{number} CACHED":
            return False

        if re.match(rf"#{number} sha256:[\da-fA-F]+ .*", line):
            return False

        if re.match(rf"#{number} extracting sha256:[\da-fA-F]+ .*", line):
            return False

        return True

    is_missed_cache = False

    while True:
        line = _real_line()

        if line is None:
            break

        print(line, file=sys.stderr)

        m = re.match(r"#(\d+) \[[^]]+] RUN .*", line)

        if not m:
            continue

        number = m.group(1)
        line = _real_line()

        is_missed_cache = _check_if_run_command_is_missed_cache(line=line)
        print(line, file=sys.stderr)

        if is_missed_cache:
            break

    def _print_rest_of_the_process_oupput():
        while True:
            line = _real_line(decode_errors="replace")
            if line is None:
                break
            print(line.strip(), file=sys.stderr)

    def _raise_process_error():
        output = "\n".join(all_lines)
        raise Exception(f"Command {cmd_args} ended with error {process.returncode}. Stderr: {output}")

    if process.poll() is not None:
        if process.returncode == 0:
            _print_rest_of_the_process_oupput()
            return False
        else:
            _raise_process_error()

    if is_missed_cache:

        import psutil
        pr = psutil.Process(process.pid)

        def _get_child_process(process: psutil.Process):
            result = []
            for child in process.children():
                result.append(child)
                result.extend(_get_child_process(process=child))

            return result

        all_children = _get_child_process(process=pr)

        process.terminate()
        for c in all_children:
            c.terminate()

        process.wait()
    else:
        process.wait()
        if process.returncode != 0:
            _raise_process_error()

    _print_rest_of_the_process_oupput()

    return is_missed_cache


#_existing_builders: Dict[CpuArch, Dict[str, RemoteBuildxBuilderWrapper]] = collections.defaultdict(dict)
_existing_builders: Dict[str, RemoteBuildxBuilderWrapper] = {}

_IN_DOCKER_SOURCE_ROOT = pl.Path("/tmp/source")

_DOCKERFILE_CONTENT_TEMPLATE = f"""
FROM {{base_image}} as main
{{copy_dependencies}}
{{copy_args_dirs}}
ADD . {_IN_DOCKER_SOURCE_ROOT}

ENV PYTHONPATH="{_IN_DOCKER_SOURCE_ROOT}"
WORKDIR {_IN_DOCKER_SOURCE_ROOT}
RUN python3 /tmp/source/agent_build_refactored/scripts/builder_helper.py {{module}}.{{builder_name}} {{builder_args}}

FROM scratch
COPY --from=main {{work_dir}}/. /work_dir
COPY --from=main {{output_dir}}/. /output_dir
"""

_BUILDERS_OUTPUT_DIR = AGENT_BUILD_OUTPUT_PATH / "builder_output"
_BUILDERS_WORK_DIR = AGENT_BUILD_OUTPUT_PATH / "builder_work_dir"

BUILDER_CLASSES: Dict[str, Type['Builder']] = {}


class BuilderMeta(type):
    def __new__(mcs, *args, **kwargs):
        global BUILDER_CLASSES

        builder_cls: Type[Builder] = super(BuilderMeta, mcs).__new__(mcs, *args, **kwargs)

        if builder_cls.NAME is None:
            return builder_cls

        module_name = args[2]["__module__"]
        module = importlib.import_module(module_name)
        module_path = pl.Path(module.__file__)
        rel_module_path = module_path.relative_to(SOURCE_ROOT)

        module_path_parts = [*rel_module_path.parent.parts, rel_module_path.stem]
        module_fqdn = ".".join(module_path_parts)

        if builder_cls.NAME is None:
            return builder_cls

        builder_fqdn = f"{module_fqdn}.{builder_cls.NAME}"

        if builder_fqdn in BUILDER_CLASSES:
            raise Exception(
                f"Builder class with fqdn '{builder_fqdn}' already exist"
            )

        builder_cls.FQDN = builder_fqdn
        BUILDER_CLASSES[builder_fqdn] = builder_cls
        return builder_cls

        # if builder_cls.NAME is None:
        #     return builder_cls
        #
        # attrs = args[2]
        # fqdn = f'{attrs["__module__"]}.{builder_cls.NAME}'
        #
        # existing_builder_cls = BUILDER_CLASSES.get(fqdn)
        # if existing_builder_cls:
        #     return existing_builder_cls
        #
        # builder_cls.FQDN = fqdn
        # BUILDER_CLASSES[fqdn] = builder_cls
        # return builder_cls


@dataclasses.dataclass
class BuilderArg:
    name: str
    cmd_line_name: str
    cmd_line_action: str = None
    default: Union[str, int, bool] = None
    type: Type = None

    def get_value(self, values: Dict):
        if self.name in values:
            value = values[self.name]

            if self.type is None:
                return value

            return self.type(value)

        if self.default is None:
            raise Exception(f"Value for build argument {self.name} is not specified.")

        return self.default


class BuilderPathArg(BuilderArg):
    pass


class Builder(metaclass=BuilderMeta):
    NAME: str = None
    FQDN: str = None

    LOCALLY_ARG = BuilderArg(
        name="locally",
        cmd_line_name="--locally",
        cmd_line_action="store_true",
        default=False,
    )

    REUSE_EXISTING_DEPENDENCIES_OUTPUTS = BuilderArg(
        name="reuse_existing_dependencies_outputs",
        cmd_line_name="--reuse-existing-dependencies-outputs",
        cmd_line_action="store_true",
        default=False,
    )

    # RUN_DEPENDENCY_STEP_ARG = BuilderArg(
    #     name="run_dependency_step",
    #     cmd_line_name="--run-dependency-step",
    # )

    USE_ONLY_CACHE = BuilderArg(
        name="use_only_cache",
        cmd_line_name="--use-only-cache",
        cmd_line_action="store_true",
        default=False,
    )

    GET_ALL_DEPENDENCIES_ARG = BuilderArg(
        name="get_all_dependencies",
        cmd_line_name="--get-all-dependencies",
        cmd_line_action="store_true",
        default=False,
    )

    GET_FQDN_ARG = BuilderArg(
        name="get_fqdn",
        cmd_line_name="--get-fqdn",
        cmd_line_action="store_true",
        default=False
    )

    def __init__(
            self,
            base: BuilderStep,
            dependencies: List[BuilderStep] = None,
    ):
        self.name = self.__class__.NAME
        self.base = base
        self.dependencies = dependencies or []

        # These attributes will have values only after Builder's run.
        self.run_kwargs = None
        self._output_ready = False

    @classmethod
    def get_all_builder_args(cls) -> Dict[str, BuilderArg]:
        result = {}
        for name in dir(cls):

            attr = getattr(cls, name)

            if isinstance(attr, BuilderArg):
                result[name] = attr

        return result

    def get_docker_step(
            self,
            run_args: Dict
    ):
        copy_dependencies_str = ""

        for dep in self.dependencies:
            dep_rel_output_dir = dep.output_dir.relative_to(SOURCE_ROOT)
            in_docker_dep_output_dir = _IN_DOCKER_SOURCE_ROOT / dep_rel_output_dir
            copy_dependencies_str = f"{copy_dependencies_str}\n" \
                                    f"COPY --from={dep.id} / {in_docker_dep_output_dir}"

        rel_output_dir = self.output_dir.relative_to(SOURCE_ROOT)
        rel_work_dir = self.work_dir.relative_to(SOURCE_ROOT)

        dockerfile_cmd_args = []
        copy_args_dirs_str = ""
        build_args_contexts = {}
        for builder_arg in self.__class__.get_all_builder_args().values():

            if builder_arg is self.REUSE_EXISTING_DEPENDENCIES_OUTPUTS:
                dockerfile_cmd_args.append(builder_arg.cmd_line_name)
                continue

            if builder_arg is self.LOCALLY_ARG:
                dockerfile_cmd_args.append(builder_arg.cmd_line_name)
                continue

            arg_value = run_args.get(builder_arg.name)

            if builder_arg.cmd_line_action:
                if builder_arg.cmd_line_action.startswith("store_") and arg_value is not None:
                    store_action = f"store_{str(arg_value).lower()}"
                    if store_action == builder_arg.cmd_line_action:
                        dockerfile_cmd_args.append(builder_arg.cmd_line_name)
            else:
                if isinstance(builder_arg, BuilderPathArg):

                    arg_path = pl.Path(arg_value).absolute()
                    in_docker_arg_path = pl.Path(f"/tmp/builder_arg_dirs{arg_path}")
                    if arg_path.is_file():
                        in_docker_arg_dir = in_docker_arg_path.parent
                    else:
                        in_docker_arg_dir = in_docker_arg_path

                    final_arg_value = in_docker_arg_path

                    arg_context_name = f"arg_{builder_arg.name}"
                    build_args_contexts[arg_context_name] = arg_value
                    copy_args_dirs_str = f"{copy_args_dirs_str}\n" \
                                         f"COPY --from={arg_context_name} . {in_docker_arg_dir}"
                else:
                    final_arg_value = arg_value

                dockerfile_cmd_args.append(builder_arg.cmd_line_name)
                dockerfile_cmd_args.append(str(final_arg_value))

        #module = importlib.import_module(self.__class__.__module__)
        module = sys.modules[self.__class__.__module__]
        module_path = pl.Path(module.__file__)
        rel_module_path = module_path.relative_to(SOURCE_ROOT)

        module_path_parts = [*rel_module_path.parent.parts, rel_module_path.stem]
        module_fqdn = ".".join(module_path_parts)

        dockerfile_content = _DOCKERFILE_CONTENT_TEMPLATE.format(
            base_image=self.base.name,
            copy_dependencies=copy_dependencies_str,
            copy_args_dirs=copy_args_dirs_str,
            module=module_fqdn,
            builder_name=self.name,
            builder_args=shlex.join(dockerfile_cmd_args),
            work_dir=str(_IN_DOCKER_SOURCE_ROOT / rel_work_dir),
            output_dir=str(_IN_DOCKER_SOURCE_ROOT / rel_output_dir)
        )

        docker_step = BuilderStep(
            name=f"builder_{self.name}_docker_step",
            context=SOURCE_ROOT,
            dockerfile=dockerfile_content,
            build_contexts=[
                self.base,
                *self.dependencies,
            ],
            platform=self.base.platform,
            cache=False,
            local_dir_contexts=build_args_contexts,
        )

        return docker_step

    @property
    def output_dir(self) -> pl.Path:
        return _BUILDERS_OUTPUT_DIR / self.name

    @property
    def work_dir(self):
        return _BUILDERS_WORK_DIR / self.name

    @abc.abstractmethod
    def build(self):
        pass

    def get_builder_arg_value(self, builder_arg: BuilderArg):
        return builder_arg.get_value(self.run_kwargs)

    def run_package_builder(
        self,
        output_dir: pl.Path = None,
        locally: bool = False,
    ):
        return self.run_builder(
            output_dir=output_dir,
            **{
                self.__class__.LOCALLY_ARG.name: locally,
            }
        )

    def run_builder(
        self,
        output_dir: pl.Path = None,
        **kwargs,
    ):
        self.run_kwargs = kwargs
        locally = self.get_builder_arg_value(self.LOCALLY_ARG)
        reuse_existing_dependencies_outputs = self.get_builder_arg_value(
            self.REUSE_EXISTING_DEPENDENCIES_OUTPUTS
        )
        use_only_cache = self.get_builder_arg_value(
            self.USE_ONLY_CACHE
        )

        def _copy_to_output():
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(
                    self.output_dir,
                    output_dir,
                    dirs_exist_ok=True,
                )

        if self._output_ready:
            _copy_to_output()
            return

        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)

        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        if not locally:
            docker_step = self.get_docker_step(
                run_args=kwargs,
            )

            if use_only_cache:
                cache_policy = CachePolicy.USE_ONLY_CACHE
            else:
                cache_policy = CachePolicy.BUILD_ON_CACHE_MISS

            docker_step.run_and_output_in_local_directory(
                cache_policy=cache_policy
            )
            shutil.copytree(
                docker_step.output_dir / "work_dir",
                self.work_dir,
                dirs_exist_ok=True,
                symlinks=True,
            )
            shutil.copytree(
                docker_step.output_dir / "output_dir",
                self.output_dir,
                dirs_exist_ok=True,
                symlinks=True,
            )

        else:
            if not reuse_existing_dependencies_outputs:
                for step in self.dependencies:
                    step.run_and_output_in_local_directory()
            self.build()

        self._output_ready = True

        _copy_to_output()










    @classmethod
    def add_command_line_arguments(cls, parser: argparse.ArgumentParser):

        for builder_arg in cls.get_all_builder_args().values():

            extra_args = {}

            if builder_arg.cmd_line_action:
                extra_args["action"] = builder_arg.cmd_line_action

            if builder_arg.default:
                extra_args["default"] = builder_arg.default

            parser.add_argument(
                builder_arg.cmd_line_name,
                dest=builder_arg.name,
                **extra_args,
            )

    @classmethod
    def get_run_arguments_from_command_line(cls, args):
        result = {}
        for builder_arg in cls.get_all_builder_args().values():
            if not isinstance(builder_arg, BuilderArg):
                continue

            value = getattr(args, builder_arg.name)
            result[builder_arg.name] = value

        return result

    @classmethod
    def get_constructor_arguments_from_command_line(cls, args):
        return {}

    def get_all_dependencies(self) -> Dict[str, BuilderStep]:
        builder__dependencies = [self.base, *self.dependencies]
        all_dependencies = {}
        for dep in builder__dependencies:
            all_dependencies[dep.id] = dep
            all_dependencies.update(dep.get_children())

        return all_dependencies

    @classmethod
    def create_and_run_builder_from_command_line(cls, args):

        constructor_args = cls.get_constructor_arguments_from_command_line(args=args)
        builder = cls(**constructor_args)

        run_args = cls.get_run_arguments_from_command_line(args=args)

        # if args.run_dependency_step:
        #     builder.run_step(path=args.run_dependency_step)
        # else:
        #     builder.run_builder(
        #         **run_args
        #     )

        if args.get_fqdn:
            print(cls.FQDN)
            exit(0)

        if args.get_all_dependencies:
            all_dependencies = builder.get_all_dependencies()

            all_dependencies_ids = sorted(list(all_dependencies.keys()))
            print(json.dumps(all_dependencies_ids))
            exit(0)

        try:
            builder.run_builder(
                **run_args
            )
        except BuilderCacheMissError:
            logging.exception(f"Builder {cls.NAME} failed")

            if args.use_only_cache:
                print("cache_miss")
                exit(0)
            raise

        if args.use_only_cache:
            print("cache_hit")
            exit(0)



# def _cleanup_output_dirs():
#     if _BUILD_STEPS_OUTPUT_OCI_DIR.exists():
#         shutil.rmtree(_BUILD_STEPS_OUTPUT_OCI_DIR)
#     _BUILD_STEPS_OUTPUT_OCI_DIR.mkdir(parents=True)
#
#     if _BUILD_STEPS_OUTPUT_OUTPUT_DIR.exists():
#         shutil.rmtree(_BUILD_STEPS_OUTPUT_OUTPUT_DIR)
#     _BUILD_STEPS_OUTPUT_OUTPUT_DIR.mkdir(parents=True)
#
#     if _BUILDERS_OUTPUT_DIR.exists():
#         shutil.rmtree(_BUILDERS_OUTPUT_DIR)
#     _BUILDERS_OUTPUT_DIR.mkdir(parents=True)
#
#     if _BUILDERS_WORK_DIR.exists():
#         shutil.rmtree(_BUILDERS_WORK_DIR)
#     _BUILDERS_WORK_DIR.mkdir(parents=True)

# if __name__ == '__main__':
#     base_parser = argparse.ArgumentParser()
#     base_parser.add_argument("fqdn")
#     base_args, other_argv = base_parser.parse_known_args()
#
#     module_name, builder_name = base_args.fqdn.rsplit(".", 1)
#     #spec = importlib.util.spec_from_file_location(module_name, file_path)
#     # print("MODULE_NAME", module_name)
#     # print("NAMEEEE", builder_name)
#
#     from agent_build_refactored.tools.builder import Builder
#
#     #__import__(module_name)
#     module = importlib.import_module(module_name)
#
#     m = sys.modules[__name__]
#
#     builder_cls = sys.modules[__name__].BUILDER_CLASSES[builder_name]
#
#     parser = argparse.ArgumentParser()
#
#     builder_cls.add_command_line_arguments(parser=parser)
#     args = parser.parse_args(args=other_argv)
#
#     builder = builder_cls.create_and_run_builder_from_command_line(args=args)


def main(builder_fqdn: str, argv=None):
    builder_cls = BUILDER_CLASSES[builder_fqdn]

    parser = argparse.ArgumentParser()

    builder_cls.add_command_line_arguments(parser=parser)
    args = parser.parse_args(args=argv)

    module_name, builder_name = builder_fqdn.rsplit(".", 1)
    importlib.import_module(module_name)

    builder_cls.create_and_run_builder_from_command_line(args=args)