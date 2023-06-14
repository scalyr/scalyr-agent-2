set -e

../configure \
  CFLAGS="-I${COMMON_DEPENDENCIES_INSTALL_PREFIX}/include -I${COMMON_DEPENDENCIES_INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="${LDFLAGS} -L${COMMON_DEPENDENCIES_INSTALL_PREFIX}/lib" \
	--enable-shared=yes \
  --with-openssl="${OPENSSL_INSTALL_PREFIX}" \
	--with-readline=edit \
	--prefix="${PYTHON_INSTALL_PREFIX}" \
	--with-suffix="-original" \
	--with-ensurepip=no