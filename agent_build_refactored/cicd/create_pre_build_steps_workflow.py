import argparse
import pathlib as pl
import yaml

SOURCE_ROOT = pl.Path(__file__).parent.parent.parent

def main(output:pl.Path):
    template_path = SOURCE_ROOT / ".github/workflows/templates/run-pre-build-jobs.yml"
    template_content = template_path.read_text()
    workflow = yaml.safe_load(template_content)
    jobs = workflow["jobs"]

    a=10

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrices", required=True)
    parser.add_argument("--output", required=True)

    args = parser.parse_args()

    main(
        output=pl.Path(args.output)
    )



