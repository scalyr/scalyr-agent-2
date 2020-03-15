from __future__ import absolute_import
from tests.smoke_tests.tools.package import ALL_DISTRIBUTION_NAMES


def pytest_addoption(parser):
    parser.addoption(
        "--package-image-cache-path",
        action="store",
        default=None,
        help="Path to a directory that will be used as a cache for docker image. "
        "If docker image file does not exist, image builder will save it here, and will import it next time."
        "This option is useful in couple with CI cache.",
    )

    # the next two options can be set multiple times
    # and every pair represents one pair of fixtures (package_distribution, package_python_version)
    # that will be passed to 'test_agent_package_smoke' test case. One pair = one test case to run.
    parser.addoption(
        "--package-distribution",
        action="append",
        default=[],
        choices=ALL_DISTRIBUTION_NAMES,
        help="list of distribution names for package smoke tests.",
    )
    parser.addoption(
        "--package-python-version",
        action="append",
        default=[],
        help="list of python version for package smoke tests.",
        choices=["python2", "python3"],
    )
