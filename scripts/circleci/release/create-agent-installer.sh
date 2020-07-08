#!/bin/bash

set -e;

function die() {
  echo "$1";
  exit 1;
}

function create_pubkey_file() {
  if [[ $2 == "main" ]]; then
    gpg --armor --export $GPG_SIGNING_KEYID > $1;
  else
    gpg --armor --export $GPG_ALT_SIGNING_KEYID > $1;
  fi
}

# Creates the postinstall.sh script for the apt repository package.
# This script is run after the Debian package has been installed,
# both for the new install and upgrade cases.
function create_apt_postinstall_script() {
  if [ -z "$FINGERPRINT_KEYID" ]; then
    die "You must first define fingerprint keyid.";
  fi
  cat > postinstall.sh <<EOF

# If we are installing or updating, be sure to add the key to the rpm's
# key ring.
mkdir -p /usr/share/debsig/keyrings/$FINGERPRINT_KEYID;
gpg --no-tty --no-default-keyring --keyring /usr/share/debsig/keyrings/$FINGERPRINT_KEYID/debsig.gpg --import /etc/apt/trusted.gpg.d/scalyr.asc  > /dev/null 2>&1;
chmod a+r /usr/share/debsig/keyrings/$FINGERPRINT_KEYID/debsig.gpg;
chmod a+rx /usr/share/debsig/keyrings/$FINGERPRINT_KEYID;
apt-key add /etc/apt/trusted.gpg.d/scalyr.asc  > /dev/null;

exit 0;

EOF
}

function create_apt_preuninstall_script() {
  if [ -z "$FINGERPRINT_KEYID" ]; then
    die "You must first define fingerprint keyid.";
  fi
  cat > preuninstall.sh <<EOF
#!/bin/bash

set -e
# Remove the installed key from the key ring.
apt-key del $FINGERPRINT_KEYID > /dev/null;
rm -fr /usr/share/debsig/keyrings/$FINGERPRINT_KEYID;

exit 0;
EOF
}

function create_apt_repo_file() {
  cat > $1 <<EOF
deb https://scalyr-repo.s3.amazonaws.com/$REPO_BASE_URL/apt scalyr main
EOF
}


function create_apt_policy_file() {
  cat > $1 <<EOF
<?xml version="1.0"?>1111
<!DOCTYPE Policy SYSTEM "http://www.debian.org/debsig/1.0/policy.dtd">
<Policy xmlns="http://www.debian.org/debsig/1.0/">
<Origin Name="Scalyr Inc" id="$FINGERPRINT_KEYID"
Description="Packages from Scalyr Inc"/>

<Selection>
<Required Type="origin" File="debsig.gpg" id="$FINGERPRINT_KEYID"/>
</Selection>

<Verification MinOptional="0">
<Required Type="origin" File="debsig.gpg" id="$FINGERPRINT_KEYID"/>
</Verification>

</Policy>
EOF
}

function create_package() {
  if [[ $1 == "rpm" ]]; then
     repo_type="yum"
     extradeps=""
  else
     repo_type="apt"
     # Debian is now failing installs where you use apt-keys in a postinstall script but do not depend on gnupg
     # Note, anything added here should be installed in the installScalyrAgentV2.sh and installScalyrRepo.sh scripts
     extradeps="--depends gnupg"
  fi

  iteration=""
  # Add 'alt' to the release tag if this is for the alternate repo.
  if [[ $2 == "alt" ]]; then
    iteration="${iteration}.alt"
  fi

  # Add in the branch as another part of the iteration/release field.
  if [[ $REPO_BRANCH == "internal" ]]; then
    iteration="${iteration}.internal"
  elif [[ $REPO_BRANCH == "beta" ]]; then
    iteration="${iteration}.beta"
  fi

  if [ -n "$iteration" ]; then
    if [[ $1 == "rpm" ]]; then
      iteration="--iteration 1${iteration}"
    else
      iteration="--iteration ${iteration:1}"
    fi
  fi

  replaces=""
  package_name="scalyr-repo"
  if [[ $3 == "bootstrap" ]]; then
    package_name="scalyr-repo-bootstrap"
  else
    replaces="--replaces scalyr-repo-bootstrap"
  fi

  fpm -s dir -a all -t $1 -n $package_name -v $REPO_PACKAGE_VERSION \
    --license "Apache 2.0" \
    --deb-user root \
    --deb-group root \
    --rpm-user root \
    --rpm-group root \
    --vendor Scalyr $iteration \
    --maintainer contact@scalyr.com \
    --provides scalyr-repro $replaces \
    --description "Configuration information for the Scalyr $repo_type repository." \
    --depends 'bash >= 3.2' $extradeps \
    --url http://scalyr.com \
    --after-install postinstall.sh \
    --before-remove preuninstall.sh \
    etc > /dev/null
}

function create_yum_postinstall_script() {
  MY_SIGNING_KEYID="$GPG_SIGNING_KEYID"
  MY_KEYIDX="1"
  if [[ $1 == "alt" ]]; then
    MY_SIGNING_KEYID="$GPG_ALT_SIGNING_KEYID"
    MY_KEYIDX="2"
  fi

  # We have to lowercase the keyid to use down below.
  keyid=`echo $GPG_SIGNING_KEYID | awk '{print tolower($0)}'`

  cat > postinstall.sh <<EOF
#!/bin/bash

set -e;
# If we are installing or updating, be sure to add the key to the rpm's
# key ring.  We only add it if the key isn't already installed, otherwise
# we will get duplicates.  We could remove this if we could remove the
# key in the preuninstall script, but we can't.
if ! rpm -q gpg-pubkey-$keyid > /dev/null 2>&1 ; then
  rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-scalyr-$MY_KEYIDX > /dev/null;
fi

exit 0;

EOF
}

# Creates the preuninstall.sh script to use in the yum repo package.
# This script is run before the package is uninstalled, either for an
# upgrade or for complete removal.
# $1 should equal "main" or "alt" depending on whether or not this
# is for the main or alternate yum repository.
function create_yum_preuninstall_script() {
  MY_SIGNING_KEYID="$GPG_SIGNING_KEYID"
  if [[ $1 == "alt" ]]; then
    MY_SIGNING_KEYID="$GPG_ALT_SIGNING_KEYID"
  fi

  if [ -z "$MY_SIGNING_KEYID" ]; then
    die "The signing key was not set before generating yum repo package.";
  fi

  # We have to lowercase the keyid to use down below.
  keyid=`echo $MY_SIGNING_KEYID | awk '{print tolower($0)}'`

  # Write the script out.
  cat > preuninstall.sh <<EOF
#!/bin/bash

set -e;
# Remove the installed key from the key ring.
# TODO: Uncomment this once we know how to remove key
# from within the preuinstall script.  However, we cannot now
# because we are not allowed to remove an RPM while we are executing
# a preuinstall script since the original package has a lock on the
# RPM db.  For now, we will just live with leaving the key installed,
# which really isn't that big of a deal.
# rpm -e gpg-pubkey-$keyid > /dev/null;

exit 0;
EOF
}

function create_repo_file() {
  KEYIDX="1"
  ALT=""
  if [[ $2 == "alt" ]]; then
    KEYIDX="2"
    ALT="-alt"
  fi

  cat > $1 <<EOF
[scalyr]
includepkgs=scalyr-agent,scalyr-agent-2,scalyr-repo1111
name=Scalyr packages - noarch
baseurl=https://scalyr-repo.s3.amazonaws.com/$REPO_BASE_URL/yum${ALT}/binaries/noarch
mirror_expire=300
metadata_expire=300
enabled=1
gpgcheck=1
gpgkey=file:///etc/pki/rpm-gpg/RPM-GPG-KEY-scalyr-$KEYIDX

EOF
}

function create_yum_repo_packages() {
  # We need a few files for the package.
  # - The postinstall and preuninstall scripts responsible for adding and
  #   removing the signing key to the RPM's keyring.
  # - The signing key (public) in etc/pki/rpm-gpg/RPM-GPG-KEY-scalyr-1
  # - The repo config in etc/yum.repos.d/scalyr.repo
  create_yum_postinstall_script $1;
  create_yum_preuninstall_script $1;
  mkdir -p etc/pki/rpm-gpg;
  if [[ $1 == "alt" ]]; then
    create_pubkey_file "etc/pki/rpm-gpg/RPM-GPG-KEY-scalyr-2" $1;
  else
    create_pubkey_file "etc/pki/rpm-gpg/RPM-GPG-KEY-scalyr-1" $1;
  fi
  mkdir -p etc/yum.repos.d;
  create_repo_file "etc/yum.repos.d/scalyr.repo" $1;

  create_package "rpm" $1 "primary";
  create_package "rpm" $1 "bootstrap";
}


function create_main_yum_repo_packages() {
  create_yum_repo_packages "main";
}

function create_alt_yum_repo_packages() {
  create_yum_repo_packages "alt";
}

function clean_package_files() {
  # Both the yum and apt packages only use /etc and the post and preuninstall
  # scripts.
  rm postinstall.sh;
  rm preuninstall.sh;
  rm -rf etc;
}

# Creates the Debian package containing the configuration information for the
# apt repository.  This creates both the bootstrap and primary package.
function create_apt_repo_packages() {
  # We need these files for the apt configuration.
  # - The postinstall and preuninstall scripts.
  # - The GPG public signing key in etc/apt/trusted.gpg.d/scalyr.asc
  # - The apt repository file in etc/apt/sources.list.d/scalyr.list
  # - The policy file in etc/debsig/policies/$FINGERPRINT_KEYID/scalyr.pol

  # We first need to write the public key because we need the FINGERPRINT_KEYID
  # for most of the rest of the files.
  mkdir -p etc/apt/trusted.gpg.d;
  create_pubkey_file "etc/apt/trusted.gpg.d/scalyr.asc" "main";

  # Apt uses a different keyid format than the RPMs or GPG, so we have to
  # construct it here.  Their keyid is the last four hexadecimal groups in
  # the fingerprint.
  #FINGERPRINT_KEYID=`gpg --with-fingerprint etc/apt/trusted.gpg.d/scalyr.asc | grep "Key fingerprint" | awk '{print $10$11$12$13}'`
  FINGERPRINT_KEYID=GPG_SIGNING_KEYID


  create_apt_postinstall_script;

  create_apt_preuninstall_script;

  mkdir -p "etc/apt/sources.list.d";
  create_apt_repo_file "etc/apt/sources.list.d/scalyr.list";

  mkdir -p "etc/debsig/policies/$FINGERPRINT_KEYID";

  create_apt_policy_file "etc/debsig/policies/$FINGERPRINT_KEYID/scalyr.pol";

  create_package "deb" "main" "primary";
  create_package "deb" "main" "bootstrap";
}

SCRIPTPATH="$( cd "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

GPG_SIGNING_KEYID=$1
GPG_ALT_SIGNING_KEYID=$2
REPO_BASE_URL=$3
REPO_BRANCH=$4

REPO_PACKAGE_VERSION="1.2.2"


create_apt_repo_packages;
clean_package_files;
create_main_yum_repo_packages;
clean_package_files;
create_alt_yum_repo_packages;

tar -cf repo_packages.tar *bootstrap*.rpm *bootstrap*.deb;

cp $SCRIPTPATH/installScalyrAgentV2.sh installScalyrAgentV2.sh
cat installScalyrAgentV2.sh
cat repo_packages.tar >> installScalyrAgentV2.sh
rm -rf *bootstrap*.rpm
rm -rf *bootstrap*.deb

