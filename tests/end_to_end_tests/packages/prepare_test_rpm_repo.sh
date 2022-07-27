set -e

sh_c cp -a "$PYTHON_BUILD/openssl/." /
sh_c cp -a "$PYTHON_BUILD/python/." /
sh_c cp -a "$PYTHON_BUILD/python_deps/." /
sh_c cp -a "$AGENT_DEPS/dependencies/." /
echo "/usr/local/lib64" >> /etc/ld.so.conf.d/local.conf
echo "/usr/local/lib" >> /etc/ld.so.conf.d/local.conf
ldconfig

#yum install -y createrepo libxcrypt-compat
yum install -y createrepo findutils chkconfig