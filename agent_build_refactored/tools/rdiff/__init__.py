import pathlib as pl
import subprocess
from typing import List, Dict


def run_rdiff_in_container(
    command_args: List[str],
    mount_mapping: Dict[pl.Path, pl.Path],
    image_name: str,
):

    mount_args = []
    for source_path, dst_path in mount_mapping.items():
        mount_args.extend([
            "-v",
            f"{source_path}:{dst_path}"
        ])

    subprocess.run(
        [
            "docker",
            "run",
            "-i",
            "--rm",
            *mount_args,
            image_name,
            *command_args
        ],
        check=True
    )


def create_files_diff_with_rdiff(
    original_file_dir: pl.Path,
    original_file_name: str,
    new_file_dir: pl.Path,
    new_file_name: str,
    result_delta_file_dir: pl.Path,
    result_delta_file_name: str,
    result_signature_file_dir: pl.Path,
    result_signature_file_name: str,
    image_name: str,
):

    in_docker_original_file_parent = pl.Path("/tmp") / original_file_dir.relative_to("/")
    in_docker_original_file = in_docker_original_file_parent / original_file_name

    in_docker_new_file_parent = pl.Path("/tmp") / new_file_dir.relative_to("/")
    in_docker_new_file = in_docker_new_file_parent / new_file_name

    in_docker_signature_file_parent = pl.Path("/tmp") / result_signature_file_dir.relative_to("/")
    in_docker_signature_file = in_docker_signature_file_parent / result_signature_file_name

    in_docker_delta_file_parent = pl.Path("/tmp") / result_delta_file_dir.relative_to("/")
    in_docker_delta_file = in_docker_delta_file_parent / result_delta_file_name

    run_rdiff_in_container(
        [
            "/bin/bash",
            "/scripts/create_diff.sh",
            str(in_docker_original_file),
            str(in_docker_new_file),
            str(in_docker_signature_file),
            str(in_docker_delta_file)

        ],
        mount_mapping={
            original_file_dir: in_docker_original_file_parent,
            new_file_dir: in_docker_new_file_parent,
            result_signature_file_dir: in_docker_signature_file_parent,
            result_delta_file_dir: in_docker_delta_file_parent
        },
        image_name=image_name
    )


def restore_new_file_from_diff(
    original_file_dir: pl.Path,
    original_file_name: str,
    delta_file_dir: pl.Path,
    delta_file_name: str,
    result_new_file_dir: pl.Path,
    result_new_file_name: str,
    image_name: str
):

    in_docker_original_file_parent = pl.Path("/tmp") / original_file_dir.relative_to("/")
    in_docker_original_file = in_docker_original_file_parent / original_file_name

    in_docker_new_file_parent = pl.Path("/tmp") / result_new_file_dir.relative_to("/")
    in_docker_new_file = in_docker_new_file_parent / result_new_file_name

    in_docker_delta_file_parent = pl.Path("/tmp") / delta_file_dir.relative_to("/")
    in_docker_delta_file = in_docker_delta_file_parent / delta_file_name

    run_rdiff_in_container(
        [
            "/bin/bash",
            "/scripts/restore_from_diff.sh",
            str(in_docker_original_file),
            str(in_docker_delta_file),
            str(in_docker_new_file),

        ],
        mount_mapping={
            original_file_dir: in_docker_original_file_parent,
            result_new_file_dir: in_docker_new_file_parent,
            delta_file_dir: in_docker_delta_file_parent
        },
        image_name=image_name
    )
