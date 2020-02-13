from typing import Mapping, Optional
import multiprocessing
import sys
from pathlib import Path
import os

from scalyr_agent import agent_main
from .runner import AgentRunner
from ..utils import get_env

from scalyr_agent.platform_controller import DefaultPaths

import six


# from .runner import AgentRunner


class DirectAgentRunner(AgentRunner):
    """
    Agent runner to launch Scalyr agent in separate process, but on the same machine.
    """

    def __init__(self, test_config=None, fork=True):  # type: (Mapping, bool) -> None
        """.
        :param fork: If set, run agent in separate process.
        """
        # Define this object before superclass constructor call, because it gets initialized there.
        self._platform_controller_default_paths = None  # type: Optional[DefaultPaths]

        super(DirectAgentRunner, self).__init__()

        # process object to run Scalyr agent in separate process.
        self._agent_process = None  # type: Optional[multiprocessing.Process]
        self._to_fork = fork

        # object to pass to scalyr agent while it is launching.

    def _init_paths(self, default_paths):  # type: (DefaultPaths) -> None
        """Because agent runs on the same machine, we need to remap all system files"""
        for name, value in list(default_paths.__dict__.items()):
            # remove root from each default path.
            value = Path(value)
            value = self._data_dir_path / value.relative_to(value.parts[0])
            setattr(default_paths, name, str(value))

        self._platform_controller_default_paths = default_paths
        super(DirectAgentRunner, self)._init_paths(default_paths)

    @property
    def _server_host(self):  # type: () -> six.text_type
        return get_env("SCALYR_TEST_HOST_NAME")

    def _agent_launcher_factory(self):
        """
        Create a subclass of the 'scalyr_agent.agent_main.ScalyrAgent'.
        The subclass has modifications for more convenient testing.
        """

        class _ScalyrAgent(agent_main.ScalyrAgent):
            def __init__(_agent, platform_controller):
                """
                #type: (PlatformController)
                """

                class _PlatformController(type(platform_controller)):
                    @property
                    def default_paths(_plaform):
                        return self._platform_controller_default_paths

                # quick solution to make 'platform_controller' to return modified default paths without recreating it.
                platform_controller.__class__ = _PlatformController
                super(_ScalyrAgent, _agent).__init__(platform_controller)

        return _ScalyrAgent

    def _launch_agent(self):
        """
        Launch agent by calling main function from 'scalyr_agent.agent.main'.
        :return:
        """
        original_scalyr_agent = agent_main.ScalyrAgent

        # monkey patch 'scalyr_agent.agent.main.ScalyrAgent'
        # to be able to control some aspects of launching of the agent.
        agent_main.ScalyrAgent = self._agent_launcher_factory()

        original_cmd_args = sys.argv
        # modify command line arguments to launch agent.
        sys.argv = [sys.argv[0], "start", "--no-fork"]
        try:
            agent_main.main()
        finally:
            agent_main.ScalyrAgent = original_scalyr_agent
            sys.argv = original_cmd_args

    def _start(self):
        super(DirectAgentRunner, self)._start()
        if self._to_fork:
            self._agent_process = multiprocessing.Process(target=self._launch_agent)
            self._agent_process.start()
        else:
            self._launch_agent()
