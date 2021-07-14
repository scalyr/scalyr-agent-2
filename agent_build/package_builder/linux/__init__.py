import pathlib as pl
import shutil
from typing import Union

from agent_build import common
from agent_build.package_builder.package_filesystem import build_base_files


def build_common_docker_and_package_files(
    build_info: common.PackageBuildInfo,
    package_type: str,
    output_path: Union[str, pl.Path],
    base_configs_path: Union[str, pl.Path],
    clear_output_if_exists: bool = True
):
    """
    Builds the common `root` system used by Debian, RPM, and container source tarballs

    :param build_info: Whether or not to create the link from initd to the scalyr agent binary.
    :param base_configs_path:  The directory (relative to the top of the source tree) that contains the configuration
        files to copy (such as the agent.json and agent.d directory).  If None, then will use `config`.
    :param output_path: The output path where the result files are stored.
    :param clear_output_if_exists: If True, remove the output folder if it exist. If False save output to the existing
        folder.
    """

    output_path = pl.Path(output_path)

    if output_path.exists() and clear_output_if_exists:
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True, exist_ok=True)

    # Build base files in the "/usr/share/scalyr-agent-2"
    build_base_files(
        build_info=build_info,
        package_type=package_type,
        output_path=output_path / "usr/share/scalyr-agent-2"
    )

    pl.Path(output_path, "var/log/scalyr-agent-2").mkdir(parents=True)
    pl.Path(output_path, "var/lib/scalyr-agent-2").mkdir(parents=True)

    # Copy the init.d script.
    init_d_path = output_path / "etc/init.d"
    init_d_path.mkdir(parents=True)
    shutil.copy2(
        common.SOURCE_ROOT / "agent_build/package_builder/linux/init.d/scalyr-agent-2",
        init_d_path / "scalyr-agent-2"
    )

    # Copy config
    shutil.copytree(base_configs_path, output_path / "etc/scalyr-agent-2")

    # Make sure there is an agent.d directory regardless of the config directory we used.
    agent_d_path = output_path / "etc/scalyr-agent-2/agent.d"
    agent_d_path.mkdir()
    # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
    # readable by others.
    agent_d_path.chmod(int("741", 8))

    # usr_sbin_path = output_path / "usr/sbin"
    # usr_sbin_path.mkdir(parents=True)
    #
    # # Create symlinks to the binaries.
    # binaries = [
    #     "scalyr-agent-2",
    #     "scalyr-agent-2-config",
    # ]
    #
    # for binary in binaries:
    #     symlink_path = usr_sbin_path / binary
    #     symlink_path.symlink_to(pl.Path("/usr/share/scalyr-agent-2/bin", binary))