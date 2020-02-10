import io
import re
import time
import datetime
from typing import List, TextIO
from urllib.parse import quote_plus
from urllib.parse import urlencode

import requests

from .agent_runner import BaseAgentContainerRunner

BASE_LINE_PATTERN = r"\s*(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}.\d+Z)\s+(?P<level>INFO|WARNING|ERROR|DEBUG)\s+\[(?P<logger>[^]]*)\]\s+\[(?P<file>[^]:]*):\d+\]"


class LogLineMatcher:
    def __init__(self, pattern: str):
        self._pattern = re.compile(pattern)

    def match(self, line: str):
        m = self._pattern.match(line)
        return bool(m)


class CollectorSpawnMatcher(LogLineMatcher):
    def __init__(self, collector_name):
        pattern = rf"{BASE_LINE_PATTERN}\s+spawned\s+(?P<collector>{collector_name})\s+\(pid=\d+\)"
        super().__init__(pattern)
        self.collector_name = collector_name

    def __str__(self):
        return f"Collector: {self.collector_name}"


class LineCounter(LogLineMatcher):
    def __init__(self, pattern, group_name, expected_count):
        pattern = r"^\s*(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}.\d+Z)\s+\[(?P<logger>[^]]*)\]\s+(?P<metric>(?:[^\s\.]+\.)+[^\s\.]+).*$"
        super().__init__(pattern)
        self._group_name = group_name
        self._expected_count = expected_count
        self._first = None
        self._count = 0

    def match(self, line):
        m = self._pattern.match(line)
        if not m:
            return False
        return self._count >= self._expected_count


class LogMatchCase:
    def __init__(self, matchers: List[LogLineMatcher], lines_limit=500):
        self._lines_limit = lines_limit
        self._matchers = matchers
        self._matched = list()

    def feed_line(self, line):
        for matcher in list(self._matchers):
            if matcher.match(line):
                self._matchers.remove(matcher)
                self._matched.append(matcher)

    def feed(self, stream, timeout=10):
        counter = 0
        while True:

            start_time = time.time()
            while True:
                line = stream.readline()
                if line:
                    break
                if time.time() - start_time >= timeout:
                    matchers_string = "".join([f"    {str(m)}\n" for m in self._matchers])
                    raise AssertionError(
                        f"Timeout. Log match case could not find needed lines for next matchers:\n{matchers_string}"
                    )
                time.sleep(0.01)

            self.feed_line(line)
            if len(self._matchers) == 0:
                return

            if counter >= self._lines_limit:
                raise AssertionError("Too much lines were passed and still no result.")

            counter += 1


class AgentVerifier:
    def __init__(self,
                 scalyr_server,
                 read_api_key,
                 host_name,
                 agent_runner: BaseAgentContainerRunner
                 ):
        self._read_api_key = read_api_key
        self._scalyr_server = scalyr_server
        self._host_name = host_name

        self._runner = agent_runner

    def request(self, log_file, line_count):
        params = {
            "maxCount": line_count,
            "startTime": "10m",
            "token": self._read_api_key,
        }

        params_str = urlencode(params)

        query = f"https://{self._scalyr_server}/api/query?queryType=log&{params_str}"

        filters = {
            "$serverHost": self._host_name,
            "$logfile": log_file
        }

        filter_fragments = list()

        for k, v in filters.items():
            filter_fragments.append(f'{k}=="{quote_plus(v)}"')

        filter_fragments_str = "+and+".join(filter_fragments)

        query = f"{query}&filter={filter_fragments_str}"

        with requests.Session() as session:
            resp = session.get(query)
        resp.raise_for_status()

        data = resp.json()

        messages = [match["message"] for match in data["matches"]]

        return io.StringIO("\n".join(messages))


    def verify(self):
        self._verify_system_metrics_monitor_log()
        self._verify_agent_log()

    def _verify_agent_log(self):

        collectors_case = LogMatchCase([
            CollectorSpawnMatcher("ifstat.py"),
            CollectorSpawnMatcher("dfstat.py"),
            CollectorSpawnMatcher("iostat.py"),
            CollectorSpawnMatcher("procstats.py"),
            CollectorSpawnMatcher("netstat.py"),
        ])

        collectors_case.feed(self._runner.agent_log_file)

        remote_stream = self.request(self._runner.agent_log_file.container_path, line_count=1000)

        collectors_case.feed(remote_stream)

    def _verify_system_metrics_monitor_log(self):

        lines = list()
        count = 0
        start_time = time.time()
        while True:
            line = self._runner.agent_system_metrics_monitor_log_file.readline()
            if line == "":
                if time.time() - start_time >= start_time:
                    raise TimeoutError()
                time.sleep(0.01)
                continue
            lines.append(line)
            count += 1
            if count >= 220:
                break

        remote_lines = self.request(self._runner.agent_system_metrics_monitor_log_file.container_path, line_count=220)

