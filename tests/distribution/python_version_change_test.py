import pytest
import sys

from ..smoke_tests.tools.package.base_builder import AgentImageBuilder


def dec(f):
    def wr(fx):
        f(fx)
        ar = sys.argv
        a = 1

    return wr


class PackageBuilder(AgentImageBuilder):
    @property
    def get_dockerfile_content(cls):  # type: () -> six.text_type
        return


@pytest.fixture()
def fx():
    return 10


def pytest_generate_tests(metafunc):
    if "fx" in metafunc.fixturenames:
        metafunc.parametrize(
            "fx", metafunc.config.getoption("--fx")
        )


def testk(fx):
    pass
