from agent_build.package_builder.linux.deb_or_rpm.fpm_based_package_builder import FpmBasedPackageBuilder


class RpmPackageBuilder(FpmBasedPackageBuilder):

    @property
    def package_type_name(self) -> str:
        return "rpm"