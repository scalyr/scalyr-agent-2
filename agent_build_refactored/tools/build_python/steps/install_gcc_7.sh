set -e

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


yum install -y centos-release-scl

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


yum install -y devtoolset-7
yum install -y scl-utils
yum remove -y help2man m4 perl

echo "source /opt/rh/devtoolset-7/enable" >> ~/.bashrc
echo "export LD_LIBRARY_PATH="/usr/local/lib:/usr/local/lib64:\${LD_LIBRARY_PATH}"" >> ~/.bashrc
echo "export PATH="/usr/local/bin:/root/.cargo/bin:\${PATH}"" >> ~/.bashrc
echo "export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:\${PATH}"" >> ~/.bashrc