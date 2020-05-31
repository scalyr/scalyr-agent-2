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

if False:
    from typing import List

import os
import glob
import datetime
from io import open

from cryptography import x509
from cryptography.hazmat.backends import default_backend

# By default we fail if any of the bundled cert expires in 2 years or sooner
DEFAULT_EXPIRE_THRESHOLD_TIMEDELTA = datetime.timedelta(days=(12 * 30 * 2))


def fail_if_cert_expires_in_timedelta(cert_path, expire_in_threshold_timedelta):
    # type: (str, datetime.timedelta) -> None
    """
    Fail and throw an exception if the provided certificate expires in the provided timedelta period
    or sooner.
    """
    with open(cert_path, "rb") as fp:
        content = fp.read()

    cert = x509.load_pem_x509_certificate(content, default_backend())

    now_dt = datetime.datetime.utcnow()
    expire_in_days = (cert.not_valid_after - now_dt).days

    if now_dt + expire_in_threshold_timedelta >= cert.not_valid_after:
        raise Exception(
            (
                "Certificate %s will expire in %s days (%s), please update!"
                % (cert_path, expire_in_days, cert.not_valid_after)
            )
        )
    else:
        print(
            "OK - certificate %s will expire in %s days (%s)"
            % (cert_path, expire_in_days, cert.not_valid_after)
        )


def get_bundled_cert_paths():
    # type: () -> List[str]
    """
    Return full absolute paths for all the bundled certs.
    """
    cwd = os.path.abspath(os.getcwd())

    result = []
    for file_name in glob.glob("certs/*"):
        file_path = os.path.join(cwd, file_name)
        result.append(file_path)

    return result


def main():
    cert_paths = get_bundled_cert_paths()

    for cert_path in cert_paths:
        fail_if_cert_expires_in_timedelta(
            cert_path, expire_in_threshold_timedelta=DEFAULT_EXPIRE_THRESHOLD_TIMEDELTA
        )


if __name__ == "__main__":
    main()
