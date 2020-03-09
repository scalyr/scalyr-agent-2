from __future__ import absolute_import
import os
import time
import threading


from io import open
from six.moves import range

from utils import wait_for_agent_start_and_get_pid

DUMMY_LINE = (
    "2020-03-08 16:11:08.246Z INFO [dummy] [dummy.py:589] Just a dummy log line. {0}\n"
)


def sender(file_path, interval):
    with open(file_path, "a") as f:
        counter = 0
        while True:
            f.write(DUMMY_LINE.format(counter))
            f.flush()
            time.sleep(interval)
            counter += 1

if __name__ == "__main__":
    agent_data_path = os.environ["AGENT_DATA_PATH"]
    pid_file_path = os.path.join(agent_data_path, "log", "agent.pid")
    pid = wait_for_agent_start_and_get_pid(pid_file_path)

    log_file = os.path.join(agent_data_path, "log", "test_log1.log")
    log_file2 = os.path.join(agent_data_path, "log", "test_log2.log")
    log_file3 = os.path.join(agent_data_path, "log", "test_log3.log")
    log_file4 = os.path.join(agent_data_path, "log", "test_log4.log")

    threads = list()
    for file, interval in [(log_file, 0.5), (log_file2, 1), (log_file3, 2)]:
        thread = threading.Thread(target=sender, args=(file, interval))
        threads.append(thread)
        thread.start()

    with open(log_file4, "a") as f:
        for i in range(5000):
            f.write(DUMMY_LINE.format(i))

    for thread in threads:
        thread.join()
