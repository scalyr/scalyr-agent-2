
function Expand-ZIPFile($file, $destination) {
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

& "C:\Program Files\openssh\install-sshd.ps1";

New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22;


Set-Service sshd -StartupType Automatic;
net start sshd;

New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force;
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShellCommandOption -Value "/c" -PropertyType String -Force;

mkdir ~\.ssh -Force;
Add-Content ~\.ssh\authorized_keys $Env:PUBLIC_KEY;

(Get-Content "C:\ProgramData\ssh\sshd_config") `
   -replace 'Match Group administrators', '#Match Group administrators' `
   -replace "       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys", "#       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys" |
 Out-File "C:\ProgramData\ssh\sshd_config" -Encoding utf8;

net stop sshd;
net start sshd;