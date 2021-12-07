import subprocess
import sys

from agent_build.tools import constants
from agent_build.tools.environment_deployments import deployments


def test_example_deployment(tmp_path):
    # Create cache directory. The deployment will store the cached results of its steps in it.
    cache_path = tmp_path

    # Because the GitHub Actions CI/CD can not run the deployment directly from the code, it has to use
    # a special helper command-line script '/agent_build/scripts/run_deployment.py', so we also do the testing through
    # that script to test that part too.

    # We use the instance if the example deployment only to get its name,
    # but we do not use that instance to perform the deployment itself.
    # Knowing the name, the helper script will find and perform the deployment.
    example_deployment_name = deployments.EXAMPLE_ENVIRONMENT.name
    run_deployment_script_path = constants.SOURCE_ROOT / "agent_build/scripts/run_deployment.py"

    try:
        step_output = subprocess.check_output(
            [
                sys.executable,
                str(run_deployment_script_path),
                "deployment",
                example_deployment_name,
                "deploy",
                "--cache-dir",
                str(cache_path)
            ],
            stderr=subprocess.STDOUT
        ).decode()
    except subprocess.CalledProcessError as e:
        stdout = e.stdout.decode()
        raise AssertionError(f"Deployment failed. Stdout:\n{stdout}")

    deployment_step_script_path = deployments.ExampleStep.SCRIPT_PATH

    assert f"=========== Run Deployment Step Script'{deployment_step_script_path.name}' ===========" in step_output
    assert f"=========== The Deployment Step Script '{deployment_step_script_path.name}' is successfully ended ===========" in step_output
