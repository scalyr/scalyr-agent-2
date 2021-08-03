# -*- mode: python ; coding: utf-8 -*-
# Copyright 2014-2021 Scalyr Inc.
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

import os
import platform
import pathlib

from PyInstaller.building.build_main import Analysis  # pylint: disable=import-error
from PyInstaller.building.api import (  # pylint: disable=import-error
    PYZ,
    EXE,
)


def is_windows():
    return platform.platform().lower().startswith("win")

def is_linux():
    return platform.system().lower().startswith("linux")

block_cipher = None
IS_DEBUG = False

HIDDEN_IMPORTS = [
    "scalyr_agent.builtin_monitors.apache_monitor",
    "scalyr_agent.builtin_monitors.graphite_monitor",
    "scalyr_agent.builtin_monitors.mysql_monitor",
    "scalyr_agent.builtin_monitors.nginx_monitor",
    "scalyr_agent.builtin_monitors.shell_monitor",
    "scalyr_agent.builtin_monitors.syslog_monitor",
    "scalyr_agent.builtin_monitors.test_monitor",
    "scalyr_agent.builtin_monitors.url_monitor",

]

if is_windows():
    HIDDEN_IMPORTS.extend([
        "scalyr_agent.builtin_monitors.windows_event_log_monitor",
        "scalyr_agent.builtin_monitors.windows_system_metrics",
        "scalyr_agent.builtin_monitors.windows_process_metrics",
    ])

    HIDDEN_IMPORTS.extend(["win32timezone"])

# add linux specific modules.
elif is_linux():
    HIDDEN_IMPORTS.extend([
        "scalyr_agent.builtin_monitors.linux_system_metrics",
        "scalyr_agent.builtin_monitors.linux_process_metrics",
    ])


datas=[
    (os.path.join("..", "VERSION"), "."),
]

# Add tcollectors.
if is_linux():
    datas.extend([
        (
            os.path.join("..","scalyr_agent", "third_party", "tcollector", "collectors"),
            os.path.join("scalyr_agent", "third_party", "tcollector", "collectors")
        ),
    ])

agent_main_analysis = Analysis(
    [os.path.join("..", "scalyr_agent", "agent_main.py")],
    pathex=[
        os.path.join("..", "scalyr_agent"),
        os.path.join("..", "scalyr_agent", "builtin_monitors"),
    ],
    hiddenimports=HIDDEN_IMPORTS,
    datas=datas,
)

agent_config_analysis = Analysis(
    [os.path.join("..", "scalyr_agent", "config_main.py")],
    pathex=[
        os.path.join("..", "scalyr_agent"),
        os.path.join("..", "scalyr_agent", "builtin_monitors"),
    ],
    hiddenimports=HIDDEN_IMPORTS,
    datas=datas
)

windows_service_analysis = None

if is_windows():
    windows_service_analysis = Analysis(
        [os.path.join("..", "scalyr_agent", "platform_windows.py")],
        pathex=[
            os.path.join("..", "scalyr_agent"),
            os.path.join("..", "scalyr_agent", "builtin_monitors"),
        ],
        hiddenimports=HIDDEN_IMPORTS,
        datas=datas
    )

WINDOWS_SERVICE_EXECUTABLE_NAME = "ScalyrAgentService.exe"

main_executable_name = "scalyr-agent-2"
config_executable_name = "scalyr-agent-2-config"


if is_windows():
    main_executable_name += ".exe"
    config_executable_name += ".exe"


main_pyz = PYZ(agent_main_analysis.pure, agent_main_analysis.zipped_data, cipher=block_cipher)

config_pyz = PYZ(agent_config_analysis.pure, agent_config_analysis.zipped_data, cipher=block_cipher)

windows_service_pyz = None

if is_windows():
    windows_service_pyz = PYZ(windows_service_analysis.pure, windows_service_analysis.zipped_data, cipher=block_cipher)


main_exe = EXE(
    main_pyz,
    agent_main_analysis.scripts,
    agent_main_analysis.binaries,
    agent_main_analysis.zipfiles,
    agent_main_analysis.datas,
    exclude_binaries=False,
    name=main_executable_name,
    debug=IS_DEBUG,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

config_exe = EXE(
    config_pyz,
    agent_config_analysis.scripts,
    agent_config_analysis.binaries,
    agent_config_analysis.zipfiles,
    agent_config_analysis.datas,
    exclude_binaries=False,
    name=config_executable_name,
    debug=IS_DEBUG,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

windows_service_exe = None

if is_windows():
    windows_service_exe = EXE(
        windows_service_pyz,
        windows_service_analysis.scripts,
        windows_service_analysis.binaries,
        windows_service_analysis.zipfiles,
        windows_service_analysis.datas,
        exclude_binaries=False,
        name=WINDOWS_SERVICE_EXECUTABLE_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=True,
    )