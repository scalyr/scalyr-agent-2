#!/usr/bin/python3 -tt
#
# Copyright: (c) 2018, Toshio Kuratomi
# License: PSF

import os
import os.path
from hashlib import sha1

import requests
import sh

URLS = {'test': 'https://raw.githubusercontent.com/python/cpython/master/Lib/test/test_ssl.py',
        'code': 'https://raw.githubusercontent.com/python/cpython/master/Lib/ssl.py'}

DESTDIR = os.path.join(os.path.dirname(__file__), 'upstream')

if __name__ == '__main__':
    for subject, url in URLS.items():
        upstream_file = os.path.join(DESTDIR, os.path.basename(url))
        with open(upstream_file, 'rb') as f:
            cur_data = f.read()
        cur_hash = sha1(cur_data).hexdigest()

        dest_file = '{}.new'.format(upstream_file)

        r = requests.get(url)
        if sha1(r.content).hexdigest() != cur_hash:
            print('New {} found: {}'.format(upstream_file, dest_file))

            with open(dest_file, 'wb') as f:
                f.write(r.content)
