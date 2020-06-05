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


$python_dir_path=$args[0]
$ProgressPreference = "SilentlyContinue"

wget https://github.com/wixtoolset/wix3/releases/download/wix3112rtm/wix311-binaries.zip -OutFile wix311-binaries.zip
Expand-Archive -LiteralPath wix311-binaries.zip -DestinationPath C:\wix311
$Env:Path += ";C:\wix311;${python_dir_path}\Scripts"
$Env:WIX = "C:\wix311"

$ParentDirPath = split-path -parent $MyInvocation.MyCommand.Definition
$Env:PYTHONPATH = "$ParentDirPath\..\"

& "${python_dir_path}\python.exe" -m pip install psutil pyinstaller pywin32
& "${python_dir_path}\python.exe" build_package.py win32