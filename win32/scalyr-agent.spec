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


from PyInstaller.utils.hooks import collect_submodules


block_cipher = None


main_a = Analysis(['source_root\\scalyr_agent\\agent_main.py'],
             pathex=[
                'source_root\\scalyr_agent\\builtin_monitors',
				'source_root\\scalyr_agent\\third_party',
				'source_root\\scalyr_agent\\third_party_python2'
				],
			 hiddenimports = collect_submodules('scalyr_agent.builtin_monitors') + ['pkg_resources.py2_warn'],
             datas=[('data_files\\VERSION.txt', '.'), ('data_files\\licenses', 'third_party_licenses'), ('data_files\\build_info', '.')],
)

config_a = Analysis(['source_root\\scalyr_agent\\config_main.py'],
             pathex=[
                'source_root\\scalyr_agent\\builtin_monitors',
                'source_root\\scalyr_agent\\third_party',
				'source_root\\scalyr_agent\\third_party_python2'
				],
             hiddenimports = collect_submodules('scalyr_agent.builtin_monitors') + ['pkg_resources.py2_warn'],
             datas=[('data_files\\VERSION.txt', '.'), ('data_files\\licenses', 'third_party_licenses'), ('data_files\\build_info', '.')],
             )

service_a = Analysis(['source_root\\scalyr_agent\\platform_windows.py'],
             pathex=[
                'source_root\\scalyr_agent\\builtin_monitors',
                'source_root\\scalyr_agent\\third_party',
				'source_root\\scalyr_agent\\third_party_python2',
				],
             hiddenimports = collect_submodules('scalyr_agent.builtin_monitors') + ['pkg_resources.py2_warn'],
             datas=[('data_files\\VERSION.txt', '.'), ('data_files\\licenses', 'third_party_licenses'), ('data_files\\build_info', '.')],
             )



MERGE( (main_a, 'scalyr-agent-2', 'scalyr-agent-2.exe'), (config_a, 'scalyr-agent-2-config', 'scalyr-agent-2-config.exe'), (service_a, 'ScalyrAgentService', 'ScalyrAgentService.exe'))


main_pyz = PYZ(main_a.pure, main_a.zipped_data,
             cipher=block_cipher)

config_pyz = PYZ(config_a.pure, config_a.zipped_data,
             cipher=block_cipher)

service_pyz = PYZ(service_a.pure, service_a.zipped_data,
             cipher=block_cipher)

main_exe = EXE(main_pyz,
          main_a.scripts,
          [],
          exclude_binaries=True,
          name='scalyr-agent-2.exe',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=True )

config_exe = EXE(config_pyz,
          config_a.scripts,
          [],
          exclude_binaries=True,
          name='scalyr-agent-2-config.exe',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=True )

service_exe = EXE(service_pyz,
          service_a.scripts,
          [],
          exclude_binaries=True,
          name='ScalyrAgentService.exe',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=True )

coll = COLLECT(main_exe,
               main_a.binaries,
               main_a.zipfiles,
               main_a.datas,
			   config_exe,
               config_a.binaries,
               config_a.zipfiles,
               config_a.datas,
			   service_exe,
               service_a.binaries,
               service_a.zipfiles,
               service_a.datas,
               name='scalyr-agent-2')
