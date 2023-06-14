set -e

for orig_file_path in ${TARGET_ROOT_PATH}/bin/* ; do
  dir_name="$(dirname "${orig_file_path}")"
  filename="$(basename "${orig_file_path}")"
  tool_name="${filename//${TARGET}-/}"
  ln -s "${filename}" "${dir_name}/${tool_name}"
done