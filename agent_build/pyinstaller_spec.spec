# -*- mode: python ; coding: utf-8 -*-
# Copyright 2014-2020 Scalyr Inc.
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
    MERGE,
    PYZ,
    EXE,
    COLLECT,
)


def is_windows():
    return platform.platform().lower().startswith("win")

def is_linux():
    return platform.system().lower() == "linux"

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

elif is_linux():
    HIDDEN_IMPORTS.extend([
        "scalyr_agent.builtin_monitors.linux_system_metrics",
        "scalyr_agent.builtin_monitors.linux_process_metrics",
    ])


datas=[
    (os.path.join("..", "VERSION"), "."),
    # (os.path.join("..","licenses"), "third_party_licenses"),
    # (os.path.join("..","build_info"), "."),
]

if is_linux():
    datas.extend([
        (
            os.path.join("..","scalyr_agent", "third_party", "tcollector", "collectors"),
            os.path.join("scalyr_agent", "third_party", "tcollector", "collectors")
        ),
    ])

main_a = Analysis(
    [os.path.join("..", "scalyr_agent", "agent_main.py")],
    pathex=[
        os.path.join("..", "scalyr_agent"),
        os.path.join("..", "scalyr_agent", "builtin_monitors"),
        #os.path.join("../..", "scalyr_agent", "third_party"),
    ],
    hiddenimports=HIDDEN_IMPORTS,
    datas=datas,
)

config_a = Analysis(
    [os.path.join("..", "scalyr_agent", "config_main.py")],
    # pathex=[
    #     os.path.join("..", "scalyr_agent", "third_party"),
    # ],
    hiddenimports=HIDDEN_IMPORTS,
    datas=datas
)

windows_service_a = None

if is_windows():
    windows_service_a = Analysis(
        [os.path.join("..", "scalyr_agent", "platform_windows.py")],
        pathex=[
            os.path.join("..", "scalyr_agent", "third_party"),
        ],
        hiddenimports=HIDDEN_IMPORTS,
        datas=[
            (os.path.join("..", "VERSION"), "."),
            #(os.path.join("..", "scalyr_agent", "third_party", "licenses"), "third_party_licenses"),
            #(os.path.join("..","build_info"), "."),
        ],
    )

WINDOWS_SERVICE_EXECUTABLE_NAME = "ScalyrAgentService.exe"

main_executable_name = "scalyr-agent-2"
config_executable_name = "scalyr-agent-2-config"


if is_windows():
    main_executable_name += ".exe"
    config_executable_name += ".exe"

# objects_to_merge = [
#     (main_a, "scalyr-agent-2", main_executable_name),
#     (config_a, "scalyr-agent-2-config", config_executable_name),
#
# ]

# if is_windows():
#     objects_to_merge.extend([
#         (windows_service_a, "ScalyrAgentService", WINDOWS_SERVICE_EXECUTABLE_NAME),
#     ])

#MERGE(*objects_to_merge)


main_pyz = PYZ(main_a.pure, main_a.zipped_data, cipher=block_cipher)

config_pyz = PYZ(config_a.pure, config_a.zipped_data, cipher=block_cipher)

windows_service_pyz = None

if is_windows():
    windows_service_pyz = PYZ(windows_service_a.pure, windows_service_a.zipped_data, cipher=block_cipher)


main_exe = EXE(
    main_pyz,
    main_a.scripts,
    main_a.binaries,
    main_a.zipfiles,
    main_a.datas,
    #exclude_binaries=True,
    name=main_executable_name,
    debug=IS_DEBUG,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

# config_exe = EXE(
#     config_pyz,
#     config_a.scripts,
#     [],
#     exclude_binaries=True,
#     name=config_executable_name,
#     debug=IS_DEBUG,
#     bootloader_ignore_signals=False,
#     strip=False,
#     upx=True,
#     console=True,
# )

config_exe = EXE(
    config_pyz,
    config_a.scripts,
    config_a.binaries,
    config_a.zipfiles,
    config_a.datas,
    #exclude_binaries=False,
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
        windows_service_a.scripts,
        windows_service_a.binaries,
        windows_service_a.zipfiles,
        windows_service_a.datas,
        #exclude_binaries=True,
        name=WINDOWS_SERVICE_EXECUTABLE_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=True,
    )

# if is_windows():
#     objects_to_collect.extend([
#         windows_service_exe,
#         windows_service_a.binaries,
#         windows_service_a.zipfiles,
#         windows_service_a.datas,
#     ])

# coll = COLLECT(
#     *objects_to_collect,
#     name="scalyr-agent-2",
# )
