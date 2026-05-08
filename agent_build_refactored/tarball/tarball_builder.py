import os
import shutil
import tarfile

from agent_build_refactored.utils.old_build_util import (
    make_path,
    make_directory,
    recursively_delete_files_by_name,
    recursively_delete_dirs_by_name,
    write_to_file,
    get_install_info,
    cat_files,
    glob_files,
    replace_shebang,
    make_soft_link,
    get_source_root,
)

def build_base_files(install_type, base_configs="config"):
    """Build the basic structure for a package in a new directory scalyr-agent-2 in the current working directory.

    This creates scalyr-agent-2 in the current working directory and then populates it with the basic structure
    required by most of the packages.

    It copies the source files, the certs, the configuration directories, etc.  This will make sure to exclude
    files like .pyc, .pyo, etc.

    In the end, the structure will look like:
      scalyr-agent-2:
        py/scalyr_agent/           -- All the scalyr_agent source files
        certs/ca_certs.pem         -- The trusted SSL CA root list.
        config/agent.json          -- The configuration file.
        bin/scalyr-agent-2         -- Symlink to the agent_main.py file to run the agent.
        bin/scalyr-agent-2-config  -- Symlink to config_main.py to run the configuration tool
        build_info                 -- A file containing the commit id of the latest commit included in this package,
                                      the time it was built, and other information.

    @param install_type: String with type of the installation. For now it can be 'package' or 'tar'
    @param base_configs:  The directory (relative to the top of the source tree) that contains the configuration
        files to copy (such as the agent.json and agent.d directory).  If None, then will use `config`.
    """
    original_dir = os.getcwd()
    # This will return the parent directory of this file.  We will use that to determine the path
    # to files like scalyr_agent/ to copy the source files
    agent_source_root = get_source_root()

    make_directory("scalyr-agent-2/py")
    os.chdir("scalyr-agent-2")

    make_directory("certs")
    make_directory("bin")
    make_directory("misc")

    # Copy the version file.  We copy it both to the root and the package root.  The package copy is done down below.
    shutil.copy(make_path(agent_source_root, "VERSION"), "VERSION")

    # Copy the source files.
    os.chdir("py")

    shutil.copytree(make_path(agent_source_root, "scalyr_agent"), "scalyr_agent")

    # Write install_info file inside the 'scalyr_agent' package.
    os.chdir("scalyr_agent")

    install_info = get_install_info(install_type)
    write_to_file(install_info, "install_info.json")
    os.chdir("..")

    shutil.copytree(make_path(agent_source_root, "monitors"), "monitors")
    os.chdir("monitors")
    recursively_delete_files_by_name("README.md")
    os.chdir("..")
    shutil.copy(
        make_path(agent_source_root, "VERSION"),
        os.path.join("scalyr_agent", "VERSION"),
    )

    # create copies of the agent_main.py with python2 and python3 shebang.
    agent_main_path = os.path.join(agent_source_root, "scalyr_agent", "agent_main.py")
    agent_main_py2_path = os.path.join("scalyr_agent", "agent_main_py2.py")
    agent_main_py3_path = os.path.join("scalyr_agent", "agent_main_py3.py")
    replace_shebang(agent_main_path, agent_main_py2_path, "#!/usr/bin/env python2")
    replace_shebang(agent_main_path, agent_main_py3_path, "#!/usr/bin/env python3")
    main_permissions = os.stat(agent_main_path).st_mode
    os.chmod(agent_main_py2_path, main_permissions)
    os.chmod(agent_main_py3_path, main_permissions)

    # Exclude certain files.
    # TODO:  Should probably use MANIFEST.in to do this, but don't know the Python-fu to do this yet.
    #
    # Don't include the tests directories.  Also, don't include the .idea directory created by IDE.
    recursively_delete_dirs_by_name(r"\.idea", "tests")
    recursively_delete_files_by_name(
        r".*\.pyc", r".*\.pyo", r".*\.pyd", r"all_tests\.py", r".*~"
    )

    os.chdir("..")

    # Copy the config
    if base_configs is not None:
        config_path = base_configs
    else:
        config_path = "config"

    shutil.copytree(make_path(agent_source_root, config_path), "config")

    # Make sure config file has 640 permissions
    os.chmod("config/agent.json", int("640", 8))

    # Create the trusted CA root list.
    os.chdir("certs")
    cat_files(
        glob_files(make_path(agent_source_root, "certs/*_root.pem")), "ca_certs.crt"
    )
    cat_files(
        glob_files(make_path(agent_source_root, "certs/*_intermediate.pem")),
        "intermediate_certs.pem",
    )
    for cert_file in glob_files(make_path(agent_source_root, "certs/*.pem")):
        shutil.copy(cert_file, cert_file.split("/")[-1])

    # TODO: Check certificate expiration same as we do as part of tox lint target
    # NOTE: This requires us to update Jenkins pipeline and other places where this script is called
    # to install cryptography library
    os.chdir("..")

    # Misc extra files needed for some features.
    os.chdir("misc")
    # This docker file is needed by the `scalyr-agent-2-config --docker-create-custom-dockerfile` command.  We
    # put it in all distributions (not just the docker_tarball) in case a customer creates an imagine using a package.
    shutil.copy(
        make_path(agent_source_root, "docker/Dockerfile.custom_agent_config"),
        "Dockerfile.custom_agent_config",
    )
    shutil.copy(
        make_path(agent_source_root, "docker/Dockerfile.custom_k8s_config"),
        "Dockerfile.custom_k8s_config",
    )
    os.chdir("..")

    # Create symlinks for the agent_main
    os.chdir("bin")

    make_soft_link("../py/scalyr_agent/agent_main.py", "scalyr-agent-2")

    shutil.copy(
        make_path(
            agent_source_root,
            "agent_build_refactored/files/linux/scalyr-agent-2-config",
        ),
        "scalyr-agent-2-config",
    )

    # add switch python version script.
    shutil.copy(
        os.path.join(
            agent_source_root,
            "agent_build_refactored/managed_packages/non-aio/files/bin/scalyr-switch-python.sh",
        ),
        "scalyr-switch-python",
    )

    os.chdir("..")

    os.chdir(original_dir)

def build_tarball_package(variant, version, no_versioned_file_name):
    """Builds the scalyr-agent-2 tarball in the current working directory.

    @param variant: If not None, will add the specified string into the final tarball name. This allows for different
        tarballs to be built for the same type and same version.
    @param version: The agent version.
    @param no_versioned_file_name:  True if the version number should not be embedded in the artifact's file name.

    @return: The file name of the built tarball.
    """
    # Use build_base_files to build all of the important stuff in ./scalyr-agent-2
    build_base_files(install_type="tar")

    # Build the rest of the directories required for the tarball install.  Mainly, the log and data directories
    # in the tarball itself where the running process will store its state.
    make_directory("scalyr-agent-2/data")
    make_directory("scalyr-agent-2/log")
    make_directory("scalyr-agent-2/config/agent.d")
    # NOTE: We in intentionally set this permission bit for agent.d directory to make sure it's not
    # readable by others.
    os.chmod("scalyr-agent-2/config/agent.d", int("741", 8))

    # Create a file named packageless.  This signals to the agent that
    # this a tarball install instead of an RPM/Debian install, which changes
    # the default paths for the config, logs, data, etc directories.  See
    # configuration.py.
    write_to_file("1", "scalyr-agent-2/packageless")

    if variant is None:
        base_archive_name = "scalyr-agent-%s" % version
    else:
        base_archive_name = "scalyr-agent-%s.%s" % (version, variant)

    shutil.move("scalyr-agent-2", base_archive_name)

    output_name = (
        "%s.tar.gz" % base_archive_name
        if not no_versioned_file_name
        else "scalyr-agent.tar.gz"
    )
    # Tar it up.
    tar = tarfile.open(output_name, "w:gz")
    tar.add(base_archive_name)
    tar.close()

    return output_name
