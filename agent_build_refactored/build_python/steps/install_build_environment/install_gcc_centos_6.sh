#!/usr/bin/env bash
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

# This script is meant to be executed by the instance of the 'agent_build_refactored.tools.runner.RunnerStep' class.
# Every RunnerStep provides common environment variables to its script:
#   SOURCE_ROOT: Path to the projects root.
#   STEP_OUTPUT_PATH: Path to the step's output directory.
#
# This script prepares base build environment for the X86_64 linux GLIBC binary packages, it expects to be run in
# Centos 6 to compile against lower GLIBS (2.12).
# It switches to Centos 6 vault repository sources (since its original sources are now disabled)
# and installs newer version of gcc.

set -e

# Update main sources from vault.
cat <<EOT > /etc/yum.repos.d/CentOS-Base.repo
[C6.10-base]
name=CentOS-6.10 - Base
baseurl=https://vault.epel.cloud/6.10/os/\$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-6
enabled=1
metadata_expire=never

[C6.10-updates]
name=CentOS-6.10 - Updates
baseurl=https://vault.epel.cloud/6.10/updates/\$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-6
enabled=1
metadata_expire=never

[C6.10-extras]
name=CentOS-6.10 - Extras
baseurl=https://vault.epel.cloud/6.10/extras/\$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-6
enabled=1
metadata_expire=never

[C6.10-contrib]
name=CentOS-6.10 - Contrib
baseurl=https://vault.epel.cloud/6.10/contrib/\$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-6
enabled=0
metadata_expire=never


[C6.10-centosplus]
name=CentOS-6.10 - CentOSPlus
baseurl=https://vault.epel.cloud/6.10/centosplus/\$basearch/
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-6
enabled=0
metadata_expire=never
EOT


cat <<EOT > /etc/yum.repos.d/CentOS-SCLo-scl-rh.repo
[centos-sclo-rh]
name=CentOS-6 - SCLo rh
baseurl=https://vault.epel.cloud/centos/6.10/sclo/\$basearch/rh/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-SIG-SCLo

[centos-sclo-rh-source]
name=CentOS-6 - SCLo rh Sources
baseurl=https://vault.epel.cloud/centos/6.10/sclo/Source/rh/
gpgcheck=1
enabled=0
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-SIG-SCLo

[centos-sclo-rh-debuginfo]
name=CentOS-6 - SCLo rh Debuginfo
baseurl=https://debuginfo.centos.org/centos/6.10/sclo/\$basearch/
gpgcheck=1
enabled=0
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-SIG-SCLo
EOT

cat <<EOT > /etc/yum.repos.d/CentOS-SCLo-scl.repo
[centos-sclo-sclo]
name=CentOS-6 - SCLo sclo
baseurl=https://vault.epel.cloud/centos/6.10/sclo/\$basearch/sclo/
gpgcheck=1
enabled=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-SIG-SCLo


[centos-sclo-sclo-source]
name=CentOS-6 - SCLo sclo Sources
baseurl=https://vault.epel.cloud/centos/6.10/sclo/Source/sclo/
gpgcheck=1
enabled=0
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-SIG-SCLo

[centos-sclo-sclo-debuginfo]
name=CentOS-6 - SCLo sclo Debuginfo
baseurl=https://debuginfo.centos.org/centos/6.10/sclo/\$basearch/
gpgcheck=1
enabled=0
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-CentOS-SIG-SCLo
EOT


# Install newer tools, such as gcc-9
yum install -y centos-release-scl
yum install -y devtoolset-9 perl-core

echo "source /opt/rh/devtoolset-9/enable" >> ~/.bashrc
echo -e "/usr/local/lib\n/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf

yum clean all
rm -rf /var/cache/yum
