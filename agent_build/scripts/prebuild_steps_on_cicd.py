import json

from agent_build.tools.environment_deployments.deployments import CacheableBuilder
from agent_build.package_builders import DOCKER_IMAGE_BUILDERS


ALL_STEPS_TO_PREBUILD = {}

for builder in DOCKER_IMAGE_BUILDERS.values():
    for cacheable_step in builder.get_all_cacheable_deployment_steps():
        if not cacheable_step.pre_build_in_cdcd:
            continue
        ALL_STEPS_TO_PREBUILD[cacheable_step.id] = cacheable_step

ALL_STEP_BUILDERS = []
for step_id, step in ALL_STEPS_TO_PREBUILD.items():
    class StepWrapperBuilder(CacheableBuilder):
        REQUIRED_STEPS = [cacheable_step]


    StepWrapperBuilder.assign_fully_qualified_name(
        class_name=StepWrapperBuilder.__name__,
        class_name_suffix=step.id,
        module_name=__name__
    )
    ALL_STEP_BUILDERS.append(StepWrapperBuilder)

if __name__ == '__main__':
    matrix = {
        "include": []
    }

    for builder in ALL_STEP_BUILDERS:
        matrix["include"].append(
            {
                "step-builder-fqdn": builder.get_fully_qualified_name(),
                "os": "ubuntu-20.04",
                "python-version": "3.8.13",
            }
        )

    print(json.dumps(matrix))