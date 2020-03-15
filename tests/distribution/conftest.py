from __future__ import absolute_import
from tests.smoke_tests.tools.package import ALL_DISTRIBUTION_NAMES


def pytest_addoption(parser):
    parser.addoption(
        "--fx",
        action="append",
        default=[],
        help="list of python version for package smoke tests."
    )
