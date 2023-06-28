set -e

DIR=./certs
mkdir -p $DIR ${DIR}/daemon ${DIR}/client
SAN=$@
SAN_CLIENT=client

pushd $DIR
CAROOT=$(pwd) mkcert -cert-file daemon/cert.pem -key-file daemon/key.pem ${SAN}
CAROOT=$(pwd) mkcert -client -cert-file client/cert.pem -key-file client/key.pem ${SAN_CLIENT}
cp -f rootCA.pem daemon/ca.pem
cp -f rootCA.pem client/ca.pem
rm -f rootCA.pem rootCA-key.pem
popd