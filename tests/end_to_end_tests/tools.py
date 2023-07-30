# Copyright 2014-2022 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import dataclasses
import json
import pathlib as pl
import subprocess
import time
from typing import List, Union, Dict


@dataclasses.dataclass
class AgentPaths:
    """
    Container class that stores all essential agent paths.
    """

    configs_dir: pl.Path
    logs_dir: pl.Path
    install_root: pl.Path
    agent_log_path: pl.Path = dataclasses.field(init=False)
    agent_config_path: pl.Path = dataclasses.field(init=False)

    def __post_init__(self):
        self.agent_log_path = self.logs_dir / "agent.log"
        self.pid_file = self.logs_dir / "agent.pid"
        self.agent_config_path = self.configs_dir / "agent.json"
        self.agent_d_path = self.configs_dir / "agent.d"


class AgentCommander:
    """
    Simple wrapper around Scalyr agent's command line interface.
    """

    def __init__(
        self,
        executable_args: List[str],
        agent_paths: AgentPaths,
    ):
        """
        :param executable_args: Path to executables, may vary from how we want to run the agent.
        :param agent_paths: Helper class with all paths that are specific for the current agent installation.
        """
        self.executable_args = executable_args
        self.agent_paths = agent_paths

    def _check_call_command(self, command_args: List[str], **kwargs):
        """
        Wrap around 'subprocess.check_call' but only for the agent commands.
        All remaining arguments the same as for the 'subprocess.check_call'
        :param command_args: Agent's command line arguments.
        :param kwargs: Other subprocess.check_call parameters.
        """
        subprocess.check_call([*self.executable_args, *command_args], **kwargs)

    def _check_output_command(
        self,
        command_args: List[str],
        **kwargs,
    ) -> bytes:
        """
        Wrap around 'subprocess.check_output' but only for the agent commands.
        All remaining arguments the same as for the 'subprocess.check_output'
        :param command_args: Agent's command line arguments.
        :param kwargs: Other subprocess.check_call parameters.
        :return: Process' output in bytes.
        """
        output = subprocess.check_output(
            [*self.executable_args, *command_args], **kwargs
        )
        return output

    def start(self, no_fork: bool = False, env=None):
        cmd = ["start"]
        if no_fork:
            cmd.append("--no-fork")

        self._check_call_command(cmd, env=env)

    def start_and_wait(
        self,
        logger=None,
        env: Dict = None
    ):
        """
        Start the Agent and wait for a successful status.
        :param logger: Logger instance.
        :param env: Optional environment variables for the agent process.
        """
        self.start(env=env)

        time.sleep(0.5)

        attempts = 0

        while True:
            try:
                self.get_status_json()
            except subprocess.CalledProcessError as e:
                if logger:
                    logger.warning(f"Can not get agent status. Error: {e}\nRetry")
                if attempts >= 10:
                    agent_log = self.agent_paths.agent_log_path.read_text()
                    agent_log_tail = "".join(agent_log.splitlines()[:20])
                    if logger:
                        logger.error(
                            f"Can not start agent and get it status. Give up.\nAgent log: {agent_log_tail}"
                        )
                    raise e
                time.sleep(1)
                attempts += 1
            else:
                break

    def get_status(self) -> str:
        return self._check_output_command(["status", "-v"]).decode()

    def get_status_json(self) -> dict:
        output = self._check_output_command(
            ["status", "-v", "--format", "json"]
        ).decode()
        return json.loads(output)

    @property
    def is_running(self) -> bool:
        try:
            self._check_output_command(["status"], stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            if (
                e.returncode == 4
                and "The agent does not appear to be running." in e.stdout.decode()
            ):
                return False
            else:
                raise Exception(
                    f"Agent's 'status' command failed with unexpected error: {e}"
                )

        return True

    def stop(self):
        self._check_call_command(["stop"])

    def restart(self):
        self.stop()
        self.start_and_wait()


class TimeoutTracker:
    """
    Simple abstraction that keeps tracking time and can be used to timeout test cases.
    """

    def __init__(self, timeout_time: Union[int, float]):
        self._global_timeout_time = time.time() + timeout_time

        self._local_timeout_time = None
        self._message = None

    def __call__(self, timeout: Union[float, int], message: str = None):
        """
        This should be used together with context manager to set the 'sleep' method track the 'local' timeout
            which has to be tracked within that context manager.
        """
        self._local_timeout_time = time.time() + timeout
        self._message = message
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._local_timeout_time = None

    def sleep(self, delay: Union[float, int], message: str = None):
        timeout_time = self._local_timeout_time or self._global_timeout_time

        message = message or self._message or "Timeout has occurred."
        if time.time() + delay >= timeout_time:
            raise TimeoutError(message)
        time.sleep(delay)
