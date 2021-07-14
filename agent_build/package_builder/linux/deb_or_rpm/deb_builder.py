import sys

from agent_build.package_builder.linux.deb_or_rpm.fpm_based_package_builder import FpmBasedPackageBuilder


class DebPackageBuilder(FpmBasedPackageBuilder):

    @property
    def package_type_name(self) -> str:
        return "deb"


if __name__ == '__main__':
    DebPackageBuilder.handle_command_line(argv=sys.argv[1:])