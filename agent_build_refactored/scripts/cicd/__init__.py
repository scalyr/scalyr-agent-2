import importlib
import os
from typing import Dict, List

from agent_build_refactored.tools.builder.builder_step import BuilderStep
from agent_build_refactored.tools.builder import BUILDER_CLASSES
BUILDER_MODULES = os.environ.get("BUILDER_MODULES", [])

for module in BUILDER_MODULES.split(","):
    importlib.import_module(module)


def get_all_dependencies() -> Dict[str, BuilderStep]:
    result = {}
    for builder_fqdn, builder_cls in BUILDER_CLASSES.items():
        builder = builder_cls()
        result.update(builder.get_all_dependencies())

    return result


all_dependencies = get_all_dependencies()


def group_dependencies() -> List[Dict[str, BuilderStep]]:
    global all_dependencies

    remaining_dependencies = all_dependencies.copy()
    result = []

    while remaining_dependencies:
        current_group = {}
        for dep_id, dep in list(remaining_dependencies.items()):

            add_to_current = True
            for child_id, child in dep.get_children().items():
                if child_id in remaining_dependencies:
                    add_to_current = False
                    break

            if add_to_current:
                current_group[dep_id] = dep

        for dep_id in current_group.keys():
            remaining_dependencies.pop(dep_id)

        result.append(current_group)

    return result


grouped_dependencies = group_dependencies()