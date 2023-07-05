import argparse
import importlib
import json
import os
from typing import Dict

from agent_build_refactored.scripts.cicd import all_dependencies, grouped_dependencies


def create_github_actions_cacheable_dependencies_matrix():
    for i, group in enumerate(grouped_dependencies):

        group_matrix_include = []
        for step_id, step in group.items():
            group_matrix_include.append({
                "id": step_id,
            })

        group_matrix = {
            "include": group_matrix_include
        }
        group_matrix_json = json.dumps(group_matrix)

        print(f"DEPENDENCY_GROUP_MATRIX_{i}={group_matrix_json}")
        print(f"DEPENDENCY_GROUP_MATRIX_{i}_SIZE={len(group_matrix_include)}")

if __name__ == '__main__':
    create_github_actions_cacheable_dependencies_matrix()

