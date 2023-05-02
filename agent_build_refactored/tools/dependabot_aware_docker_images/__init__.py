import re
import pathlib as pl

PARENT_DIR = pl.Path(__file__).parent.absolute()


def parse_dockerfile(path: pl.Path):
    content = path.read_text()

    for line in content.splitlines():
        trimmed_line = line.strip()
        if not trimmed_line.startswith("FROM"):
            continue

        m = re.search(r"^FROM\s+(\S+)$", trimmed_line)

        image_name = m.group(1)
        return image_name

    raise Exception(f"Can't find image name in the dockerfile {path}")



UBUNTU_22_04 = parse_dockerfile(path=PARENT_DIR / "ubuntu-22.04.Dockerfile")

a=10
