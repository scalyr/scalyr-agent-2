from __future__ import absolute_import
import pytest
import tempfile
import time
from io import open

try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib

from tests.utils.log_reader import (
    LogReader,
    LogReaderError,
    LogMetricReader,
    LogReaderTimeoutError,
)

from concurrent.futures import ThreadPoolExecutor


def write_line(line, path):
    with open(path, "a") as fp:
        fp.write(line)
        fp.write("\n")


def test_log_reader():
    log_file_fd, log_file_path = tempfile.mkstemp(prefix="scalyr_tesing")
    log_file_path = pathlib.Path(log_file_path)

    reader = LogReader(str(log_file_path))

    with log_file_path.open("a") as fp:
        fp.write("line1\n")

    assert reader.wait_for_next_line() == "line1"
    assert reader.last_line == "line1"

    with log_file_path.open("a") as fp:
        fp.write("line2\n")
        fp.write("line3\n")

    assert reader.wait_for_matching_line("line3") == "line3"
    assert reader.last_line == "line3"

    with log_file_path.open("a") as fp:
        fp.write("line4\n")
        fp.write("line5\n")

    reader.wait(0.5)

    assert reader.last_line == "line5"

    reader.add_error_check(r"error \d+")

    with log_file_path.open("a") as fp:
        fp.write("line6\n")
        fp.write("error 5\n")

    assert reader.wait_for_next_line() == "line6"

    with pytest.raises(LogReaderError):
        reader.wait_for_next_line()


def test_log_metric_reader():
    log_file_fd, log_file_path = tempfile.mkstemp(prefix="scalyr_tesing")
    log_file_path = pathlib.Path(log_file_path)

    class MyLogMetricReader(LogMetricReader):
        LINE_PATTERN = r"(?P<metric_name>[^:]+):\s*(?P<metric_value>.+)"

    reader = MyLogMetricReader(str(log_file_path))

    assert reader.current_metrics == {}

    write_line("metric1: 23", log_file_path)

    assert reader.current_metrics == {}

    assert reader.wait_for_metrics_exist(["metric1"]) == {"metric1": 23}

    write_line("metric2: 44", log_file_path)
    write_line("metric1: 24", log_file_path)

    reader.go_to_end()

    assert reader.current_metrics == {"metric1": 24, "metric2": 44}

    executor = ThreadPoolExecutor()

    wait_future = executor.submit(
        reader.wait_for_metrics_equal, expected={"metric1": 26, "metric2": 45}
    )

    time.sleep(0.1)

    assert not wait_future.done()

    write_line("metric2: 45", log_file_path)

    time.sleep(0.1)

    assert not wait_future.done()

    write_line("metric1: 26", log_file_path)
    time.sleep(0.1)

    wait_future.result()

    assert wait_future.done()

    assert reader.current_metrics == {"metric1": 26, "metric2": 45}

    write_line("metric1: 100", log_file_path)
    write_line("metric2: 200", log_file_path)

    reader.wait_for_metrics_equal(expected={"metric1": 100, "metric2": 200})

    # test_timeout
    with pytest.raises(LogReaderTimeoutError):
        reader.wait_for_metrics_equal(
            expected={"metric1": 300, "metric2": 400}, timeout=0.2
        )
