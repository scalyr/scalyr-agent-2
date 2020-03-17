from tests.utils.compat import Path
from tests.distribution_builders.base import BaseDistributionBuilder


class AmazonlinuxBuilder(BaseDistributionBuilder):
    IMAGE_TAG = "scalyr-agent-testings-amazonlinux"
    DOCKERFILE = Path(__file__).parent / "Dockerfile"
