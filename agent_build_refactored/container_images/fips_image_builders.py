from typing import Dict, Type

from agent_build_refactored.container_images.image_builders import (
    ContainerisedAgentBuilder,
    ImageType,
)
from agent_build_refactored.utils.constants import CpuArch

_FIPS_IMAGES_SUPPORTED_ARCHITECTURES = [
    CpuArch.x86_64,
    CpuArch.AARCH64,
]


_FIPS_BUILDER_NAME = "ubuntu-fips"

FIPS_CONTAINERISED_AGENT_BUILDERS: Dict[str, Type] = {}


class UbuntuFipsContainerisedAgentBuilder(ContainerisedAgentBuilder):
    NAME = _FIPS_BUILDER_NAME
    BASE_DISTRO = _FIPS_BUILDER_NAME
    TAG_SUFFIXES = ["-ubuntu", ""]

    def get_image_registry_names(self, image_type: ImageType):
        """
        Use the same names as for normal images but with the 'fips' suffix
        """
        names = super(UbuntuFipsContainerisedAgentBuilder, self).get_image_registry_names(
            image_type=image_type
        )

        return [f"{n}-fips" for n in names]

    def get_supported_architectures(self):
        return _FIPS_IMAGES_SUPPORTED_ARCHITECTURES[:]


FIPS_CONTAINERISED_AGENT_BUILDERS[_FIPS_BUILDER_NAME] = UbuntuFipsContainerisedAgentBuilder