from tests.utils.compat import Path
from tests.distribution_builders.base import BaseDistributionBuilder


class UbuntuBuilder(BaseDistributionBuilder):
    IMAGE_TAG = "scalyr-agent-testings-ubuntu"
    DOCKERFILE = Path(__file__).parent / "Dockerfile"
