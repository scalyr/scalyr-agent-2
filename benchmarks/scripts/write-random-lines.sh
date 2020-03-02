#!/usr/bin/env bash
# Copyright 2014-2020 Scalyr Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Script which generates and writes random lines to the provided file path. For
# simplicy and speed (avoding the overhead of generating random lines and / or
# reading from a dictionary, it simply reads random bytes from /dev/urandom).
#
# NOTE: We don't care about secure values here so we use non blocking and faster
# /dev/urandom and not /dev/random

# Path to which we should write data to
FILE_PATH=${1-"/tmp/random.log"}

# Single chunk size
# NOTE: We write in smaller chunks with a delay in between to make sure agent
# doesn't fall to far behind
CHUNK_SIZE=${2:-"2M"}

# How many chunks to write. If this value is 5 and CHUNK_SIZE is 4, we will
# write 20 MB in total (5 * 4)
CHUNKS_COUNT=${3-5}

# Line / word length in characters
WORD_LENGTH=${4-"100"}

# How long to wait between writting each chunk
WRITE_DELAY=${5-0.2}

echo "Writting lines to file ${FILE_PATH}"
echo "CHUNK_SIZE=${CHUNK_SIZE}"
echo "CHUNKS_COUNT=${CHUNKS_COUNT}"
echo "WORD_LENGTH=${WORD_LENGTH}"
echo "WRITE_DELAY=${WRITE_DELAY}"
echo ""

i=1
while [ $i -le "${CHUNKS_COUNT}" ]
do
    echo "Writting chunk ${i} to file ${FILE_PATH}"
    #< /dev/urandom tr -d -c '[:alpha:]' | head -c "${CHUNK_SIZE}" | fold -w"${WORD_LENGTH}" >> "${FILE_PATH}"
    i=$(( i + 1 ))

    if [ $i -le "${CHUNKS_COUNT}" ]; then
        sleep "${WRITE_DELAY}"
    fi
done
