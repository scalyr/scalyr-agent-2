$python_dir_path=$args[0]
$ProgressPreference = "SilentlyContinue"

wget https://github.com/wixtoolset/wix3/releases/download/wix3112rtm/wix311-binaries.zip -OutFile wix311-binaries.zip
Expand-Archive -LiteralPath wix311-binaries.zip -DestinationPath C:\wix311
$Env:Path += ";C:\wix311;${python_dir_path}\Scripts"
$Env:WIX = "C:\wix311"

& "${python_dir_path}\python.exe" -m pip install psutil pyinstaller pywin32
& "${python_dir_path}\python.exe" build_package.py win32