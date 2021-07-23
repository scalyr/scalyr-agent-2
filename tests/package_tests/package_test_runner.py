import pathlib as pl
import argparse
import subprocess

_PARENT_DIR = pl.Path(__file__).parent


parser = argparse.ArgumentParser()

parser.add_argument("--package-path", required=True)
parser.add_argument("--package-test-path")
parser.add_argument("--docker-image")
parser.add_argument("--scalyr-api-key", required=True)


args = parser.parse_args()

package_path = pl.Path(args.package_path)

if args.package_test_path:
    package_test_path = pl.Path(args.package_test_path)
else:
    package_test_path = _PARENT_DIR / "package_test.py"

if args.docker_image:
    subprocess.check_call(
        f"docker run -i --rm -v {package_test_path}:/package_test -v {package_path}:/{package_path.name} "
        f"--init {args.docker_image} /package_test --package-path /{package_path.name} "
        f"--scalyr-api-key {args.scalyr_api_key}",
        shell=True
    )
else:
    subprocess.check_call(
        f"{package_test_path} --package-path {package_path} "
        f"--scalyr-api-key {args.scalyr_api_key}",
        shell=True
    )
