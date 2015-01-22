# Copyright 2014 Scalyr Inc.
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
# ------------------------------------------------------------------------
#
# Note, this setup is based on the Sample Project example from Python
# Packaging Authority.
#
# Note, to install a new version of the package
# 1.  Edit the version number in scalyr_agent/agent_main.py
# 2.  Make sure you have a ~/.pypirc file that contains the username and
#     password for our account.  It should look something like:
#        [distutils]
#        index-servers=pypi
#  
#        [pypi]
#        repository = http://pypi.python.org/pypi
#        username = scalyr
#        password = <Password from passpack.. no need for quotes>
# 3.  Build and upload:
#     python setup.py sdist bdist_wheel --universal upload

from setuptools import setup, find_packages  # Always prefer setuptools over distutils
from codecs import open  # To use a consistent encoding
from os import path

import sys

if path.isdir('source_root'):
    sys.path.append('source_root')

from scalyr_agent.__scalyr__ import SCALYR_VERSION, determine_file_path

if "win32" == sys.platform:
    import py2exe

here = path.dirname(determine_file_path())

# Get the long description from the relevant file
with open(path.join(here, 'DESCRIPTION.rst'), encoding='utf-8') as f:
    long_description = f.read()

class Target:
    def __init__(self, **kw):
        self.version = SCALYR_VERSION
        self.description = 'TODO'
        self.copyright = 'TODO'
        self.__dict__.update(kw)

service_config = Target(
    description = 'Scalyr Agetn 2 Service',
    modules = ['scalyr_agent.ScalyrAgentService'],
    cmdline_style = 'pywin32',
)


setup(
    name='scalyr-agent-2',

    version=SCALYR_VERSION,

    description='The Python modules that implements Scalyr Agent 2',
    long_description=long_description,

    # The project's main homepage.
    url='https://www.scalyr.com/help/scalyr-agent-2',

    # Author details
    author='Scalyr, Inc',
    author_email='contact@scalyr.com',

    # Choose your license
    license='Apache',

    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Development Status :: 5 - Production/Stable',

        # Indicate who your project is intended for
        'Intended Audience :: System Administrators',
        'Topic :: System :: Logging',
        'Topic :: System :: Monitoring',

        # Pick your license as you wish (should match "license" above)
        'License :: OSI Approved :: Apache Software License',

        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.4',
        'Programming Language :: Python :: 2.5',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
    ],

    # What does your project relate to?
    keywords='monitoring tools',

    # You can just specify the packages manually here if your project is
    # simple. Or you can use find_packages().
    packages=find_packages(exclude=['tests*']),

    # List run-time dependencies here.  These will be installed by pip when your
    # project is installed. For an analysis of "install_requires" vs pip's
    # requirements files see:
    # https://packaging.python.org/en/latest/technical.html#install-requires-vs-requirements-files
    # install_requires=['peppercorn'],

    # If there are data files included in your packages that need to be
    # installed, specify them here.  If using Python 2.6 or less, then these
    # have to be included in MANIFEST.in as well.
    #package_data={
    #    'sample': ['package_data.dat'],
    #},

    # Although 'package_data' is the preferred approach, in some case you may
    # need to place data files outside of your packages.
    # see http://docs.python.org/3.4/distutils/setupscript.html#installing-additional-files
    # In this case, 'data_file' will be installed into '<sys.prefix>/my_data'
    #data_files=[('my_data', ['data/data_file'])],

    # To provide executable scripts, use entry points in preference to the
    # "scripts" keyword. Entry points provide cross-platform support and allow
    # pip to create the appropriate form of executable for the target platform.
    #entry_points={
    #    'console_scripts': [
    #        'sample=sample:main',
    #    ],
    #},
    console=[
        {
            'script': path.join('source_root', 'scalyr_agent', 'agent_main.py'),
            'dest_base': 'scalyr-agent-2'
        },
        {
            'script': path.join('source_root', 'scalyr_agent', 'config_main.py'),
            'dest_base': 'scalyr-agent-config'
        }
    ],
    service=[service_config],
)
