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
#
# Disclaimer!  This is not a really operational setup.py file.  We need to improve this
# so it does work as a Python user would normally expect.  It only supports two uses
# cases right now:  uploading the Python module to pypi (instructions above) and
# building the Windows installer using py2exe.  However, building the Windows installer
# only works via the build_package.py script.  If you try to just invoke the build
# from here, the files would not be set up correctly.  We need to improve this, but
# it is low on the list of priorities right now.

from setuptools import setup, find_packages  # Always prefer setuptools over distutils
from codecs import open  # To use a consistent encoding
from os import path

import os
import re
import sys
import shutil

if path.isdir('source_root'):
    sys.path.append('source_root')

# need to include third_party path here otherwise
# we break win32 builds
if path.isdir('source_root/scalyr_agent/third_party'):
    sys.path.append('source_root/scalyr_agent/third_party')

from scalyr_agent.__scalyr__ import SCALYR_VERSION, get_install_root

_file_version = SCALYR_VERSION

if "win32" == sys.platform:

    # For prereleases, we use weird version numbers like 4.0.4.pre5.1 .  That does not work for Windows which
    # requires X.X.X.X.  So, we convert if necessary.
    if len(_file_version.split('.')) == 5:
        parts = _file_version.split('.')
        del parts[3]
        _file_version = '.'.join(parts)

    version = re.compile( '^\d+(\.\d+)?(\.\d+)?(\.\d+)?$' )

    # if we still don't have a valid version string, then bail
    if not version.match( _file_version ):
        #we have an unknown version string - so bail
        raise Exception( "Invalid version string: %s\nThis will cause issues with the windows installer, which requires version strings to be N.N.N.N" % _file_version )


    # ModuleFinder can't handle runtime changes to __path__, but win32com uses them
    try:
        # py2exe 0.6.4 introduced a replacement modulefinder.
        # This means we have to add package paths there, not to the built-in
        # one.  If this new modulefinder gets integrated into Python, then
        # we might be able to revert this some day.
        # if this doesn't work, try import modulefinder
        try:
            import py2exe.mf as modulefinder
        except ImportError:
            import modulefinder
        import win32com, sys
        for p in win32com.__path__[1:]:
            modulefinder.AddPackagePath("win32com", p)

        for extra in ["win32com.shell"]: #,"win32com.mapi"
            __import__(extra)
            m = sys.modules[extra]
            for p in m.__path__[1:]:
                modulefinder.AddPackagePath(extra, p)
    except ImportError:
        # no build path setup, no worries.
        pass

    import py2exe

# Get the long description from the relevant file
with open(path.join(get_install_root(), 'DESCRIPTION.rst'), encoding='utf-8') as f:
    long_description = f.read()


class Target:
    def __init__(self, **kw):
        self.version = _file_version
        self.description = 'TODO'
        self.copyright = 'TODO'
        self.__dict__.update(kw)

service_config = Target(
    description='Scalyr Agent 2 Service',
    modules=['scalyr_agent.platform_windows'],
    dest_base='ScalyrAgentService',
    cmdline_style='pywin32'
)

# Determine which of the two uses cases we are executing.. either we are on Windows building the
# Windows installer using py2exe, or we are uploading the module to pypi.
if 'win32' == sys.platform:
    my_data_files = [('', [path.join('source_root', 'VERSION')])]
    for my_license in os.listdir(path.join('data_files', 'licenses')):
        license_file = path.join('data_files', 'licenses', my_license)
        if os.path.isfile(license_file):
            x = 'third_party_licenses', [license_file]
            my_data_files.append(x)
    my_package_data = None
else:
    my_data_files = []
    my_package_data = {'scalyr_agent': ['VERSION']}
    # Copy VERSION to the source directory to make it easier to include it as package data.  There's
    # is surely a better way here, but my setup.py fu is very weak.
    shutil.copy('VERSION', 'scalyr_agent')

setup(
    name='scalyr-agent-2',

    version=_file_version,

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

    package_data=my_package_data,

    # Although 'package_data' is the preferred approach, in some case you may
    # need to place data files outside of your packages.
    # see http://docs.python.org/3.4/distutils/setupscript.html#installing-additional-files
    # In this case, 'data_file' will be installed into '<sys.prefix>/my_data'
    data_files=my_data_files,

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
            'dest_base': 'scalyr-agent-2',
        },
        {
            'script': path.join('source_root', 'scalyr_agent', 'config_main.py'),
            'dest_base': 'scalyr-agent-2-config',
        }
    ],
    service=[service_config],

    options={
        'py2exe': {
            # TODO(windows): Auto-generate this list based on contents of the monitors directory.
            'includes': 'scalyr_agent.builtin_monitors.windows_system_metrics,'
                        'scalyr_agent.builtin_monitors.windows_process_metrics,'
                        'scalyr_agent.builtin_monitors.apache_monitor,'
                        'scalyr_agent.builtin_monitors.graphite_monitor,'
                        'scalyr_agent.builtin_monitors.mysql_monitor,'
                        'scalyr_agent.builtin_monitors.nginx_monitor,'
                        'scalyr_agent.builtin_monitors.shell_monitor,'
                        'scalyr_agent.builtin_monitors.syslog_monitor,'
                        'scalyr_agent.builtin_monitors.test_monitor,'
                        'scalyr_agent.builtin_monitors.url_monitor,'
                        'scalyr_agent.builtin_monitors.windows_event_log_monitor',
            'dll_excludes': ["IPHLPAPI.DLL", "NSI.dll", "WINNSI.DLL", "WTSAPI32.dll"],
        }
    }
)

if 'win32' != sys.platform:
    # Delete the temporary copy of VERSION that we created above.
    tmp_path = os.path.join('scalyr_agent', 'VERSION')
    if os.path.isfile(tmp_path):
        os.unlink(tmp_path)

