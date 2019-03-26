#!/bin/bash
#
# Helper script for building and optionally publishing the various Scalyr Agent
# container images.  This will both build and publish the images.
# It relies on the tarball containing the source and Dockerfile
# to be embedded at the end of this script.
#
# This is used to generate the two different flavors of the
# Scalyr Agent on Docker and the Scalyr agent on K8s.

# Warning, do not change lines without making corresponding change in `build_package.py`.  That
# script relies on these lines.
REPOSITORIES=""      # OVERRIDE_REPOSITORIES
TAGS=""              # OVERRIDE_TAGS

function print_usage() {
cat <<EOF
Usage $0 [options] where options are:
    -h,--help            Display this help message."
    --extract-packages   Extracts the embedded Dockerfile and source tarball.
    --repositories       A comma-separated list of the repositories that this
                         image should be tagged and published to.
    --tags               A comma-separated list of the tags for the image.
                         Note, each tag is applied to each repository listed in `--repository`
    --publish            The script will push the images to all repositories under all tags.

EOF
}

function die() {
  echo "$1";
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

# Only write $1 to STDOUT if $2 is non-zero
function report_progress() {
  if [ -z "$2" ]; then
    echo $1
  fi
}

# Runs the docker command in $1 and sends output to /dev/null if $2 is non-empty.
function run_docker_command() {
  if [ -z "$2" ]; then
      docker $1
  else
      docker $1 > /dev/null
  fi
  return
}

TMPDIR=`mktemp -d`;
trap "rm -rf $TMPDIR" EXIT;

PUBLISH=""
QUIET=""

# Handle the options
while (( $# > 0)); do
  case "$1" in

    -h|--help)
      print_usage;
      exit 0;;

    --extract-packages)
      echo "Extracting...";
      untar_tarball $0 || die "Failed to extract packages";
      cp $TMPDIR/Dockerfile ./ || die "Failed to copy the Dockerfile to current directory";
      cp $TMPDIR/*.tar.gz ./ ||
        die "Failed to copy the source tarball to the current directory";
      exit 0;;

    --repositories)
      REPOSITORIES="$2";
      shift
      shift;;

    --tags)
      TAGS="$2";
      shift
      shift;;

    --publish)
      PUBLISH="yes";
      shift;;

    --quiet)
      QUIET="yes";
      shift;;

    *)
      echo "Unrecognized option: $1";
      exit 1;
      break;;
  esac
done


# Split the comma-separated lists in the two environment variables into bash arrays.
IFS=',' read -r -a REPOS_LIST <<< "$REPOSITORIES"
IFS=',' read -r -a TAGS_LIST <<< "$TAGS"

# Create a list of all images tags by taking the cross product of REPOS and TAGS.
IMAGES=()
for repo in "${REPOS_LIST[@]}"
do
  for tag in "${TAGS_LIST[@]}"
  do
    IMAGES+=("$repo:$tag")
  done
done

report_progress "Extracting Dockerfile and source tarball." "$QUIET";

untar_tarball $0 || die "Failed to extract packages";

cd $TMPDIR

report_progress "Building image." "$QUIET";

# We need to pass a separate -t option for each tag we want to add to the image.  Build a string
# that holds all of those values
TAG_OPTIONS=""
for x in "${IMAGES[@]}"
do
   TAG_OPTIONS="$TAG_OPTIONS -t $x"
done

run_docker_command "build $TAG_OPTIONS ." "$QUIET" || die "Failed to build the container image"

if [ ! -z "$PUBLISH" ]; then
  report_progress "Publishing image(s)." "$QUIET";

  for x in "${IMAGES[@]}"
  do
    run_docker_command "push $x" "$QUIET";
  done
fi

report_progress "Success." "$QUIET";

exit 0;

# The encoded tar file will go below here. Do not modify the next line.
# TARFILE_FOLLOWS:
