import os
import pathlib as pl

result_file_path = pl.Path(os.environ["BASE_RESULT_FILE_PATH"])
input_value = os.environ["INPUT"]

result_string = f"{input_value}_python"
if "AGENT_BUILD_IN_DOCKER" in os.environ:
    result_string = f"{result_string}_in_docker"

result_file_path.write_text(result_string)