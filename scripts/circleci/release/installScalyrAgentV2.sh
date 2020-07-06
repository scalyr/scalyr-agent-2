#!/bin/bash
#
# test!!!!!!!!!!!!!!!!!5
# Installs necessary packages to run the Scalyr Agent 2 on the host.
# To perform this task, the script  Analyzes the system and attempts to
# install the correct repository configuration files to enable installing
# and updating the Scalyr Agent using either yum or apt-get.  Which
# repository type is used is determined by the available commands on this
# system.
#
# After the repository is set up, then this script install the Scalyr Agent
# packages as well and optionally performs some configuration updates.
#
# This script must be executed as root.
#
# This script has two packages (an RPM and and Debian package) that
# each contain the appropriate configuration files for either the yum
# or apt repository setup.  These packages can be extracted from this
# script file using the --extract-packages option.

function print_usage() {
cat <<EOF
Usage $0 [options] where options are:
    -h,--help              Display this help message."
    --extract-packages     Extracts the embedded RPM and Debian packages to
                           install the Scalyr package repository configuration
                           and exits.
    --force-apt            Forces the script to install the Scalry APT
                           repository configuration files.
    --force-yum            Forces the script to install the Scalyr Yum
                           repository configuration files.
    --force-alt-yum        Forces the script to install the Scalyr Alternate
                           Yum repository configuration files.  The alternate
                           repository is for older linux systems such as
                           RHEL5 or CentOS 5 which do not support the signing
                           keys used in the main repository.
    --set-api-key KEY      Updates the configuration file with the provided
                           key.
    --read-api-key-from-stdin
                           Prompts the user to enter their account's
                           Write Logs key and updates the configuration
                           file with the result.
    --set-scalyr-server SERVER
                           Updates the configuration with the provided value for
                           the scalyr_server field.  It does this by writing
                           a new configuration fragment.
    --start-agent          If specified, this script will start the agent
                           running in the background once the installation
                           is finished.
    --verbose              If set, will send all of the output from the
                           underlying yum/apt-get commands to stdout instead
                           of piping them to a separate log file.  This output
                           can be a bit hard to read.
    --version              Specifies the version number of the scalyr-agent-2
                           package to install, rather than the latest.
EOF
}

function die() {
  echo "$1";
  exit 1;
}

function die_install() {
  echo "Install failed: $1";
  exit 1;
}

# Extracts the tarball in the script (whose filename is in $1).
# It will leave the tarball in $TMPDIR.
function extract_tarball() {
  line_start=`awk '/^# TARFILE_FOLLOWS:/ { print NR + 1; exit 0; }' $1`
  tail -n+$line_start $1 > $TMPDIR/packages.tar;
}

# Extracts and untars the tarball in the script (whose filename is in
# $1).  It will leave the packages in $TMPDIR.
function untar_tarball() {
  extract_tarball "$1" &&
    tar --directory $TMPDIR -oxf $TMPDIR/packages.tar &&
    rm $TMPDIR/packages.tar ||
    return;
}

# Executes the specified command in $1, sending the stderr and stdout to
# the command log file if $VERBOSE is not set.
# An optional $2 can hold a function that should be executed instead of "die" when
# there is an error.  It will be invoked with the parameter that would have been passed to "die".
function run_command() {
  if [ -n "$2" ]; then
    die_func=$2
  else
    die_func=die
  fi
  err_msg="Install failed while executing \"$1\".  Execute \"$1\" to see error.";
  if [ -n "$VERBOSE" ]; then
    $1 || $die_func "$err_msg";
  else
    echo "**** Running command \"$1\" ******"  >> $COMMAND_LOG 2>&1;
    $1 >> $COMMAND_LOG 2>&1 || $die_func "$err_msg";
    echo "**** Finished command \"$1\" ******"  >> $COMMAND_LOG 2>&1;
  fi
}

# Write the passed in messages to both stdout and the command log if
# script is not running in verbose mode.
function lecho() {
  if [ -n "$VERBOSE" ]; then
    echo "$1";
  else
    echo "$1";
    echo "$1" >> $COMMAND_LOG 2>&1;
  fi
}

# Helper method invoked to check to see if an install failed because apt-transport-https is not installed
# (some Debian distros have a separate package for using HTTPS for downloading packages).  $1 contains the
# error message that would normally be printed out.
function check_for_https_error() {
  apt_install_command="sudo apt-get install -y --force-yes apt-transport-https ca-certificates"
  if grep -q "/usr/lib/apt/methods/https could not be found" $COMMAND_LOG; then
    echo ""
    echo "** Failed because apt-transport-https is not installed. **"
    echo "  Please execute \"$apt_install_command\" and rerun script."
    exit 1
  else
    die "$1"
  fi
}

TMPDIR=`mktemp -d`;
trap "rm -rf $TMPDIR" EXIT;

# The repository we will install the agent against.  Either yum, apt, or
# yum-alt.
REPO_TYPE=
# If non-empty, the write logs api key that should be inserted into the
# configuration file after initial installation is complete.
CONFIG_KEY=
# If non-empty, should run in verbose mode where all the output of the
# underlying commands is sent to stdout, stderr.
VERBOSE=
# If non-empty, this script should start the agent after the installation
# if finished.
START_AGENT=
# The version number to install, if not the latest.
VERSION=
# If non-empty, the scalyr server to use for uploading logs.
SCALYR_SERVER=

# Handle the options
while (( $# > 0)); do
  case "$1" in

    -h|--help)
      print_usage;
      exit 0;;

    --extract-packages)
      echo "Extracting...";
      untar_tarball $0 || die "Failed to extract packages";
      cp $TMPDIR/*.rpm ./ || die "Failed to copy rpm to current directory";
      cp $TMPDIR/*.deb ./ ||
        die "Failed to copy Debian package to current directory";
      exit 0;;

    --force-apt)
      REPO_TYPE="apt";
      shift;;

    --force-yum)
      REPO_TYPE="yum";
      shift;;

    --force-alt-yum)
      REPO_TYPE="alt-yum";
      shift;;

    --read-api-key-from-stdin)
      CONFIG_KEY="stdin";
      shift;;

    --set-api-key)
      CONFIG_KEY="$2";
      shift
      shift;;

    --set-scalyr-server)
      SCALYR_SERVER="$2";
      shift
      shift;;

    --start-agent)
      START_AGENT="yes"
      shift;;

    --verbose)
      VERBOSE="yes"
      shift;;

    --version)
      VERSION="$2"
      shift;
      shift;;

    --read-api-key-from-stdin)
      CONFIG_KEY="stdin";
      shift;;

    *)
      die "Unrecognized option: $1";
      break;;
  esac
done

fail() {
  # Check for error which indicates suitable Python interpreter is not
  # installed on the system and print a more user-friendly error
  if grep -q "Suitable Python interpreter not found" ${COMMAND_LOG}; then
    echo ""
    echo "** Failed because suitable Python interpreter is not found. **"
    echo "Please install suitable interpreter and rerun the script."
    echo ""
    echo "The package name usually is \"python\" for Python 2 and \"python3\" for Python."
    echo "An exception to that is RHEL 8 / CentOS 8 where the package name for Python 2 is \"python2\"."
  fi

  if [ -f "${COMMAND_LOG}" ]; then
    echo ""
    echo "Displaying last 20 lines from ${COMMAND_LOG}"
    echo ""
    echo "..."
    tail -20 "${COMMAND_LOG}" 2> /dev/null
    echo ""
  fi

  echo "See $COMMAND_LOG for additional details."
  rm -rf "${TMPDIR}"

  exit 1
}

function fail_unable_to_detect_package_manager_type() {
  # NOTE: We pass arbitrary caller idto this function so we can track it back
  # to where this function has been called
  CALLER_ID=$1

  # Function which should be called if we are unable to automatically detect
  # available package manager type (apt / yum).
  # It prints the error message and exits with non zero.
  lecho "";
  lecho "Unable to determine whether system uses yum or apt-get (caller_id=${CALLER_ID})";
  lecho "Maybe this system doesn't have either?.";
  lecho "";
  lecho "If this is not correct, you may manually specify which system to";
  lecho "use by specifying either the --force-yum or --force-apt option";
  lecho "when executing this script.";
  lecho "";
  lecho "Failing to install.";
  exit 1;
}

function print_detected_yum_package_manager() {
  CALLER_ID=$1

  lecho "  Determined system uses yum for package management. (caller_id=${CALLER_ID})";
  lecho " If you think automatic detection was wrong, you can abort the script (CTRL+C) and re-run it with --force-apt / --force-alt-yum flag"

  # We sleep to give user a chance to abort the script before proceeding
  sleep 2
}

function print_detected_yum_package_manager_el5() {
  CALLER_ID=$1

  lecho "  Determined system uses yum for package management. (el5) (caller_id=${CALLER_ID})";
  lecho " If you think automatic detection was wrong, you can abort the script (CTRL+C) and re-run it with --force-apt / --force-alt-yum flag"

  # We sleep to give user a chance to abort the script before proceeding
  sleep 2
}

function print_detected_apt_package_manager() {
  CALLER_ID=$1

  lecho "  Determined system uses apt for package management. (caller_id=${CALLER_ID})";
  lecho " If you think automatic detection was wrong, you can abort the script (CTRL+C) and re-run it with --force-yum / --force-alt-yum flag"

  # We sleep to give user time to abort the script before proceeding
  sleep 2
}

# If we are not using verbose mode, then prepare the COMMAND_LOG
# where we will send all of the stdout/stderr for the major commands
# we run.
if [ -z "$VERBOSE" ]; then
  COMMAND_LOG="scalyr_install.log"
  # Begin a new log.
  timestamp=`date`;
  echo "$timestamp: Installing scalyr-agent-2 packages." > $COMMAND_LOG ||
    die_install "Could not write to $COMMAND_LOG file.  Fix permissions and try again.";
  # Add in extra message to be printed at EXIT to remind folks the should look
  # in the command log.  We should remove this trap down below if the
  # installation is successful.
  trap "fail" EXIT;
fi

lecho "Installing scalyr-agent-2:";
lecho "  Extracting configuration packages from downloaded script.";
untar_tarball $0 || die_install "Failed to extract packages";

if [ -z "$REPO_TYPE" ]; then
  if [ -f /etc/redhat-release ]; then
    if [ -n "`grep \"CentOS release 5\" /etc/redhat-release`" ]; then
      print_detected_yum_package_manager_el5 "1"
      REPO_TYPE="alt-yum";
    elif [ -n "`grep \"Red Hat Enterprise Linux Server release 5\" /etc/redhat-release`" ]; then
      print_detected_yum_package_manager_el5 "2"
      REPO_TYPE="alt-yum";
    else
      print_detected_yum_package_manager "3"
      REPO_TYPE="yum";
    fi
  elif command -v yum > /dev/null 2>&1 && command -v apt-get > /dev/null 2>&1; then
    # If both commands are installed we use some additional heuristics to
    # detect if this is a debian or red hat based distro.
    # Another option would be to simply abort and instruct user to either user
    # --force-apt / --force-yum flag
    if [ -f "/etc/debian_version" ]; then
      print_detected_apt_package_manager "4"
      REPO_TYPE="apt";
    elif [ "$(grep -Ei 'debian|buntu|mint' /etc/*release)" ]; then
      print_detected_apt_package_manager "5"
      REPO_TYPE="apt";
    elif [ "$(grep -Ei 'fedora|redhat' /etc/*release)" ]; then
      print_detected_yum_package_manager "6"
      REPO_TYPE="yum";
    else
      fail_unable_to_detect_package_manager_type "7"
    fi
  # NOTE: Command existence checks could give false positives in case user has
  # yum-utils package installed on Ubuntu and vice-versa so we have them at the
  # very end.
  elif command -v yum > /dev/null 2>&1; then
    print_detected_yum_package_manager "8"
    REPO_TYPE="yum";
  elif command -v apt-get > /dev/null 2>&1; then
    print_detected_apt_package_manager "9"
    REPO_TYPE="apt";
  else
    fail_unable_to_detect_package_manager_type "10"
  fi
elif [[ $REPO_TYPE == "apt" ]]; then
  lecho "  Configuring to use apt-get for package installs.";
elif [[ $REPO_TYPE == "yum" ]]; then
  lecho "  Configuring to use yum for package installs.";
else
  lecho "  Configuring to use yum for package installs. (el5)";
fi

# The bootstrap rpm name will be something like
# scalyr-repo-bootstrap-1.2-1.noarch.rpm,
# scalyr-repo-bootstrap-1.2-1.internal.noarch.rpm
# scalyr-repo-bootstrap-1.2-1.beta.noarch.rpm
bootstrap_rpm=`ls $TMPDIR/*bootstrap*-1.[nib]*.rpm`

# If we are using the alternate yum repository, then just change around
# which files we are going to be installing so that we can reuse the
# same code down below.
if [[ $REPO_TYPE == "alt-yum" ]]; then
  bootstrap_rpm=`ls $TMPDIR/*bootstrap*-1.alt*.rpm`
  REPO_TYPE="yum"
fi

if [[ $REPO_TYPE == "yum" ]]; then
  # We attempt to uninstall any old version of the package that may have
  # been left on the system.
  lecho "  Removing any old configuration files for the Scalyr yum repository.";
  run_command "yum remove -y scalyr-repo";
  run_command "yum remove -y scalyr-repo-bootstrap";

  lecho "  Installing Scalyr yum repository configuration files.";

  # Install the bootstrap rpm for the repository configuration.  This isn't
  # signed since it is the first package, so disable the gpg check.
  run_command "yum install --nogpgcheck -y $bootstrap_rpm";

  lecho "  Updating Scalyr yum repository configuration files using repository.";
  # Now, use the repository to update the repository configuration.  This
  # removes the old bootstrap package and allows the repository to distribute
  # updates to the repository configuration itself.  This is the cleanest
  # way we found to make sure the repository configuration can be updated.
  run_command "yum install -y scalyr-repo";

  PACKAGE_NAME="scalyr-agent-2"
  if [[ -n "$VERSION" ]]; then
    PACKAGE_NAME="scalyr-agent-2-$VERSION"
  fi

  lecho "  Installing scalyr-agent-2 package"
  run_command "yum install -y $PACKAGE_NAME";
else
  # We attempt to uninstall any old version of the package that may have
  # been left on the system.
  lecho "  Removing any old configuration files for the Scalyr apt repository.";
  run_command "dpkg -r scalyr-repo";
  run_command "dpkg -r scalyr-repo-bootstrap";

  echo "  Installing Scalyr apt repository configuration files.";
  # Manually install dependencies for the repo package, since `dpkg -i` doesn't install them for you.
  run_command "apt-get -y install gnupg"
  # Now install the repo package, which must be done using `dpkg` since it is a package on local disk.
  # Do not use `apt-get install` here. Even though it does now support installing a package from local disk, older
  # versions run by our customers do not.
  run_command "dpkg -i $TMPDIR/*.deb";

  # We need an apt-get update to force apt to refresh the list of repositories
  # and available packages.  Since this will cause all to refresh,
  # it takes a little bit of time, but we do not have a choice.
  # Also, we specifically check for an error some distros experience where apt-transport-https is not installed to
  # give a better error message.  We cannot depend on that package because not all separate out the https on its own.
  lecho "  Refreshing available package list (may take several minutes)";
  run_command "apt-get update" check_for_https_error;

  lecho "  Updating Scalyr yum repository configuration files using repository.";
  run_command "apt-get -y install scalyr-repo";

  PACKAGE_NAME="scalyr-agent-2"
  if [[ -n "$VERSION" ]]; then
    PACKAGE_NAME="scalyr-agent-2=$VERSION"
  fi

  lecho "  Installing scalyr-agent-2 package"
  run_command "apt-get -y install $PACKAGE_NAME";
fi

if [ -n "$CONFIG_KEY" ]; then
  lecho "  Inserting api key into the scalyr-agent-2 agent config.";
  if [[ $CONFIG_KEY == "stdin" ]]; then
      /usr/sbin/scalyr-agent-2-config --set-key-from-stdin ||
        die_install "Failed to update configuration file with api key."
  else
      /usr/sbin/scalyr-agent-2-config --set-key "$CONFIG_KEY" ||
        die_install "Failed to update configuration file with api key."
  fi
fi

if [ -n "$SCALYR_SERVER" ]; then
  lecho "  Creating scalyr_server.json config to set the scalyr server to use.";
  /usr/sbin/scalyr-agent-2-config --set-scalyr-server "$SCALYR_SERVER" ||
      die_install "Failed to update the scalyr_server field."
fi

lecho "Success installing Scalyr agent.";
lecho "";

if [ -n "$START_AGENT" ]; then
  run_command "/usr/sbin/scalyr-agent-2 start";
  lecho "Agent verified configuration and has successfully launched in background.";
  lecho "You may run the following command to retrieve detailed status:";
  lecho "  sudo scalyr-agent-2 status -v";
else
  lecho "You should now be able to start the agent by running the following";
  lecho "command: ";
  lecho "  sudo scalyr-agent-2 start";
fi

rm -f "$COMMAND_LOG" ||
  die "Install succeeded but could not delete tmp log: $COMMAND_LOG";
rm -rf "$TMP_DIR" ||
  die "Install succeeded but could not delete tmp directory: $TMP_DIR";

# Reset the signal:
trap EXIT;

exit 0;

# The encoded tar file will go below here.
# TARFILE_FOLLOWS:
