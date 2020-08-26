# -*- coding: utf-8 -*-

import os
from distutils.core import setup

long_description = open(os.path.join(
    os.path.dirname(__file__), 'README.txt'
    )).read()

setup(
    name='backports.ssl_match_hostname',
    version='3.7.0.1',
    description='The ssl.match_hostname() function from Python 3.5',
    long_description=long_description,
    author='Brandon Rhodes',
    author_email='brandon@rhodesmill.org',
    maintainer='Toshio Kuratomi',
    maintainer_email='toshio@fedoraproject.org',
    url='http://bitbucket.org/brandon/backports.ssl_match_hostname',
    license='Python Software Foundation License',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: Python Software Foundation License',
        'Programming Language :: Python :: 2.4',
        'Programming Language :: Python :: 2.5',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.0',
        'Programming Language :: Python :: 3.1',
        'Programming Language :: Python :: 3.2',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Topic :: Security :: Cryptography',
        ],
    packages=['backports', 'backports.ssl_match_hostname'],
    )
