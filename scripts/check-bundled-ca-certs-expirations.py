#!/usr/bin/env python
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

"""
Script which errors out if any of the bundled certs will expire in 6 months or sooner.
"""

from __future__ import absolute_import
from __future__ import print_function

import os
import sys
import glob
import datetime
from io import open

from cryptography import x509
from cryptography.hazmat.backends import default_backend


def main():
    cwd = os.path.abspath(os.getcwd())

    for file_name in glob.glob("certs/*"):
        file_path = os.path.join(cwd, file_name)

        with open(file_path, "rb") as fp:
            content = fp.read()

        cert = x509.load_pem_x509_certificate(content, default_backend())

        if (
            datetime.datetime.utcnow() + datetime.timedelta(days=30 * 6)
            >= cert.not_valid_after
        ):
            print(
                (
                    "Certificate %s will expire in 6 months or sooner (%s), please update!"
                    % (file_path, cert.not_valid_after)
                )
            )
            sys.exit(1)
        else:
            print(
                "OK - certificate %s will expire in %s"
                % (file_path, cert.not_valid_after)
            )


if __name__ == "__main__":
    main()
