

from agent_build_refactored.tools.constants import CpuArch
from agent_build_refactored.managed_packages.managed_packages_builders import LinuxAIOPackagesBuilder, get_package_builder_by_name


builder_cls = get_package_builder_by_name("deb-aio-x86_64")

builder = builder_cls()
#builder.run_builder_locally()
builder.run_builder(locally=False)

a=10