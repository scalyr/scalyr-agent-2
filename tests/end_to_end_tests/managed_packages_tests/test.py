from tests.end_to_end_tests.managed_packages_tests.remote_tests_run import run_test_in_docker


def test(portable_test_runner):

    run_test_in_docker(
        test_runner_path=portable_test_runner,
    )