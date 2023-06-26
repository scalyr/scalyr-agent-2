set -e



../configure \
  CFLAGS="-I${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/include -I${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/include/ncurses -I${OPENSSL_INSTALL_PREFIX}/include" \
  LDFLAGS="${LDFLAGS} -L${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib -L${OPENSSL_INSTALL_PREFIX}/lib" \
	--enable-shared=yes \
  --with-openssl="${OPENSSL_INSTALL_PREFIX}" \
	--with-readline=edit \
	--prefix="${INSTALL_PREFIX}" \
	--with-suffix="-original" \
	--with-ensurepip=no