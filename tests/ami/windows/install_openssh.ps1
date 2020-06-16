#!/usr/bin/env bash
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
#
# This script downloads and installs OpenSSH server from https://github.com/PowerShell/Win32-OpenSSH.OpenSSH.
# Script requires following environment variables being set.
#   PUBLIC_KEY - string that contains public key for future authorization.
#



function Expand-ZIPFile($file, $destination) {
    # extract zip file in older versions of the powershell.
	$shell = new-object -com shell.application
	$zip = $shell.NameSpace((Resolve-Path $file).Path)
	foreach($item in $zip.items())
		{
			$shell.Namespace($destination).copyhere($item)
		}
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12


wget https://github.com/PowerShell/Win32-OpenSSH/releases/download/v8.1.0.0p1-Beta/OpenSSH-Win64.zip -OutFile OpenSSH-Win64.zip;
#Expand-Archive -LiteralPath OpenSSH-Win64.zip -DestinationPath "C:\Program Files" -Force;
Expand-ZIPFile -File  "~\OpenSSH-Win64.zip" -Destination "C:\Program Files"

rm OpenSSH-Win64.zip -Force

mv "C:\Program Files\OpenSSH-Win64" "C:\Program Files\openssh";
$env:Path += "C:\Program Files\openssh";

# run openssh installation script.
& "C:\Program Files\openssh\install-sshd.ps1";

# configure firewall to enable 22 port.
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22;

Set-Service sshd -StartupType Automatic;

# we need to start sshd service, because it should create registry folder for it in the first launch.
net start sshd;

# create new registry item to change default openssh shell to powershell.
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force;
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShellCommandOption -Value "/c" -PropertyType String -Force;

mkdir ~\.ssh -Force;

# Configure ssh server to accept specified public key by adding it into 'authorized_keys' file.
Add-Content ~\.ssh\authorized_keys $Env:PUBLIC_KEY;


# comment out particular lines in sshd_config to make it work with ~/.ssh directory.
(Get-Content "C:\ProgramData\ssh\sshd_config") `
   -replace 'Match Group administrators', '#Match Group administrators' `
   -replace "       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys", "#       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys" |
 Out-File "C:\ProgramData\ssh\sshd_config" -Encoding utf8;

# restart service to apply changes.
net stop sshd;
net start sshd;