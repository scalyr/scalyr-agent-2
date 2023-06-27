set -e

../configure \
  CFLAGS="-I${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/include -I${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/include/ncurses" \
  LDFLAGS="${LDFLAGS} -L${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}/lib" \
	--enable-shared=yes \
  --with-openssl="${COMMON_PYTHON_DEPENDENCY_INSTALL_PREFIX}" \
	--with-readline=edit \
	--prefix="${INSTALL_PREFIX}" \
	--with-suffix="-original" \
	--with-ensurepip=no