# import pathlib as pl
#
# from agent_build_refactored.tools.constants import CpuArch, SOURCE_ROOT
#
#
# _PARENT_DIR = pl.Path(__file__).parent
#
#
# class UbuntuToolset(BuilderStep):
#     def __init__(
#         self,
#
#     ):
#
#         requirements_file = SOURCE_ROOT / "dev-requirements-new.txt"
#
#         super(UbuntuToolset, self).__init__(
#             name=_PARENT_DIR.name,
#             context=_PARENT_DIR,
#             dockerfile=_PARENT_DIR / "Dockerfile",
#             platform=CpuArch.x86_64,
#             build_args={
#                 "REQUIREMENTS_CONTENT": requirements_file.read_text(),
#             }
#         )
#
#
# UBUNTU_TOOLSET_X86_64 = UbuntuToolset()