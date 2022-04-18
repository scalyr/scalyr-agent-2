import argparse
import pathlib as pl
import tarfile
import os

from agent_build import prepare_agent_filesystem

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-path",
        required=True,
        help="Output path for the container tarball."
    )
    args = parser.parse_args()

    output_path = pl.Path(args.output_path)

    if not output_path.exists():
        output_path.mkdir(parents=True)

    agent_filesystem_root_path = output_path / "root"

    prepare_agent_filesystem.build_linux_lfs_agent_files(
        copy_agent_source=True,
        output_path=agent_filesystem_root_path,
        install_info_str="",
        config_path=pl.Path(""),
    ),

    container_tarball_path = output_path / "scalyr-agent.tar.gz"

    # Do a manual walk over the contents of root so that we can use `addfile` to add the tarfile... which allows
    # us to reset the owner/group to root.  This might not be that portable to Windows, but for now, Docker is
    # mainly Posix.
    with tarfile.open(container_tarball_path, "w:gz") as container_tar:

        for root, dirs, files in os.walk(agent_filesystem_root_path):
            to_copy = []
            for name in dirs:
                to_copy.append(os.path.join(root, name))
            for name in files:
                to_copy.append(os.path.join(root, name))

            for x in to_copy:
                file_entry = container_tar.gettarinfo(
                    x, arcname=str(pl.Path(x).relative_to(agent_filesystem_root_path))
                )
                file_entry.uname = "root"
                file_entry.gname = "root"
                file_entry.uid = 0
                file_entry.gid = 0

                if file_entry.isreg():
                    with open(x, "rb") as fp:
                        container_tar.addfile(file_entry, fp)
                else:
                    container_tar.addfile(file_entry)