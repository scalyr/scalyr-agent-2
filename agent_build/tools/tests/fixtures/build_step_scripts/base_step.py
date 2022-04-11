import os
import pathlib as pl

result_file_path = pl.Path(os.environ["BASE_RESULT_FILE_PATH"])
input_value = os.environ["INPUT"]
result_file_path.write_text(f"{input_value}_python")