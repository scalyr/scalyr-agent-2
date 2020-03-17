from tests.utils.compat import Path

from tests.utils.base_builder import AgentImageBuilder

dockerfile = Path(Path(__file__).parent, "Dockerfile")


class BaseDistributionBuilder(AgentImageBuilder):
    COPY_AGENT_SOURCE = True

    def get_dockerfile_content(cls):  # type: () -> six.text_type
        content = super(BaseDistributionBuilder, cls).get_dockerfile_content()
        return content.format(
            fpm_package_builder_dockerfile=dockerfile.read_text()
        )
