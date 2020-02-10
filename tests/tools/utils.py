import tempfile


def create_temp_dir(prefix="scalyr_test_"):
    return tempfile.TemporaryDirectory(prefix=prefix)


def create_temp_named_file(mode, prefix="scalyr_test_"):
    return tempfile.NamedTemporaryFile(mode, prefix="scalyr_test_", suffix='.file')