import subprocess

_BUILDX_BUILDER_NAME = "agent_image_buildx_builder"

def main():
    # Prepare buildx builder, first check if there is already existing builder.
    builders_list_output = subprocess.check_output([
        "docker",
        "buildx",
        "ls"
    ]).decode().strip()

    # Builder is not found, create new one.
    if _BUILDX_BUILDER_NAME not in builders_list_output:
        subprocess.check_call([
            "docker",
            "buildx",
            "create",
            "--driver-opt=network=host",
            "--name",
            _BUILDX_BUILDER_NAME
        ])

    # Use needed builder.
    subprocess.check_call([
        "docker",
        "buildx",
        "use",
        _BUILDX_BUILDER_NAME
    ])


if __name__ == '__main__':
    main()