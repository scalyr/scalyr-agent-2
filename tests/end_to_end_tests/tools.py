import dataclasses
import pathlib as pl
import logging
import inspect
import functools

from agent_build.tools.constants import SOURCE_ROOT


def _get_source_related_frames():
    """
    Return only those frames from the call stack which caller module files are from the source code.
    """
    result = []
    for frame in inspect.stack():
        file_path = pl.Path(frame.filename)
        if str(file_path).startswith(str(SOURCE_ROOT)):
            result.append(frame)

    return result


def get_testing_logger(name: str):
    logger = logging.getLogger(name=name)

    # Save position in stack that has to be without indents.
    base_stack_pos = len(_get_source_related_frames())

    original_make_record = logger.makeRecord

    @functools.wraps(logger.makeRecord)
    def indent_make_record(name, level, fn, lno, msg, *args, **kwargs):
        stack_pos = len(_get_source_related_frames())
        indent = "  " * ((stack_pos - base_stack_pos) - 1)
        msg = f"{indent}{msg}"
        return original_make_record(name, level, fn, lno, msg, *args, **kwargs)

    logger.makeRecord = indent_make_record

    return logger




# class IndentFormatter(logging.Formatter):
#     """
#     Custom logger formatter that takes into account current position in the call stack to
#     indent log records that are done in nested functions to make logs more structured.
#     """
#     def __init__( self, fmt=None, datefmt=None, style='%', validate=True):
#         logging.Formatter.__init__(self, fmt=fmt, datefmt=datefmt, style=style, validate=validate)
#         self.baseline = len(self._get_source_related_frames())
#
#     @staticmethod
#     def _get_source_related_frames():
#         """
#         Return only those frames from the call stack which caller module files are from the source code.
#         """
#         result = []
#         for frame in  inspect.stack():
#             file_path = pl.Path(frame.filename)
#             if str(file_path).startswith(str(SOURCE_ROOT)):
#                 result.append(frame)
#
#         return result
#
#     def format( self, rec):
#         stack = self._get_source_related_frames()
#         rec.message = f"    {rec.message}"*(len(stack)-self.baseline)
#         out = logging.Formatter.format(self, rec)
#         return out

# def set_indented_formatter_logger(logger: logging.Logger):
#     handler = logging.StreamHandler()
#     formatter = IndentFormatter()
#     handler.setFormatter(formatter)
#     logger.addHandler(handler)


@dataclasses.dataclass
class AgentPaths:
    configs_dir: pl.Path
    logs_dir: pl.Path
    install_root: pl.Path
    agent_log_path: pl.Path = dataclasses.field(init=False)
    agent_config_path: pl.Path = dataclasses.field(init=False)

    def __post_init__(self):
        self.agent_log_path = self.logs_dir / "agent.log"
        self.pid_file = self.logs_dir / "agent.pid"
        self.agent_config_path = self.configs_dir / "agent.json"
        self.agent_d_path = self.configs_dir / "agent.d"
