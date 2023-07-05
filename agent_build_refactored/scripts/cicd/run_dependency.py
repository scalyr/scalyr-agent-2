import argparse

from agent_build_refactored.scripts.cicd import all_dependencies

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("dependency_id", choices=all_dependencies.keys())

    args = parser.parse_args()

    dependency = all_dependencies[args.dependency_id]

    dependency.run()