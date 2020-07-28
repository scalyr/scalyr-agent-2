Third Party Libraries
=====================

This directory holds libraries that the Scalyr team has included from other projects.  Some of these 
libraries have been forked to allow for them to be linked into the Scalyr Agent 2, while some are just
straight copies so that our customers do not need to separately install these dependencies.  These libraries
are released under their respective licenses which are included in the directories.

Licenses for those libraries are available in the
[licenses/](https://github.com/scalyr/scalyr-agent-2/tree/master/scalyr_agent/third_party/licenses/) directory.

Library details
================

The following libraries are included:

  * [tcollector](#tcollector)
  * [PyMySQL](#PyMySQL)
  * [uuid](#uuid)
  * [redis-py](#redis-py)
  * [Requests](#requests)
  * [PySNMP](#pysnmp)
  * [PyASN1](#pyasn1)
  * [PySMI](#pysmi)
  * [PLY](#ply)
  * [pg8000](#pg8000)
  * [docker-py](#docker-py)
  * [docker-pycreds](#docker-pycreds)
  * [ipaddress](#ipaddress)
  * [six](#six)
  * [backports.ssl-match-hostname](#ssl-match-hostname)
  * [PySocks](#PySocks)
  * [glob2](#glob2)

## tcollector<a name="tcollector"> (GPL v3)

A project that enables adhoc metric collection by writing simple collectors, similar to ScalyrMonitors.
For additional details, please visit the
[tcollector project page](http://opentsdb.net/docs/build/html/user_guide/utilities/tcollector.html).

This library has been forked by the Scalyr team.  It is used by the `linux_system_metrics` Monitor Plugin.

## PyMySQL<a name="PyMySQL"> (MIT)

A pure Python implementation of a MySQL client library.  For additional details, please visit the
[PyMySQL project page](http://www.pymysql.org/).

The `mysql_monitor` depends on this library.
 
Currently, this library is just a straight copy, but we may wish to fork it in the future.  The original
library only supports Python 2.6 and higher, whereas the agent attempts to support Python 2.4 and higher.  If
there is enough customer demand to allow the `mysql_monitor` to run with Python 2.4 or 2.5, we may fork and
invest the time to make the necessary modifications.

## uuid<a name="uuid"> (PSF)

UUID object and generation functions compatible with Python 2.4.  The standard Python uuid module only supports
Python 2.5 and higher but was based on a package available from [pypi](https://pypi.python.org/pypi/uuid/).  
That package still supports earlier versions of Python and so this is just a straight copy from that package.

## redis-py<a name="redis-py"> (MIT)

A redis client for Python.  For additional details, please visit the [redis-py github repository](https://github.com/andymccurdy/redis-py).

The `redis_monitor` depends on this library.

Currently this library is just a straight copy, but we may wish to fork it in the future.  The original
library only supports Python 2.6 or higher.  If there is enough customer demand to allow the `redis_monitor`
to run with earlier versions of Python we may fork and invest the time to make the necessary modifications.

## Requests<a name="requests-py"> (Apache 2.0)

Improved HTTP request handling.  For additional details, please visit the [requests homepage](http://docs.python-requests.org/).

This is a straight copy from the main Requests git repository.  Currently this library is just a straight
copy, but we may wish to fork it in the future.  The original library only supports Python 2.6 or higher.
If there is enough customer demand to allow Requests to run with earlier versions of Python we may fork
and invest the time to make the necessary modifications.

## PySNMP<a name="pysnmp"> (BSD 2 clause)

A pure Python SNMP library used by scalyr_agent.builtin_monitors.snmp_monitor

Currently this library is just a straight copy, and has support for Python 2.4 and later.

## PyASN1<a name="pyasn1"> (BSD 2 clause)

A pure Python ASN.1 library.

Used by PySNMP.

## PySMI<a name="pysmi"> (BSD 2 clause)

A pure Python library for parsing and conversion of SNMP/SMI MIBs.

Used by PySNMP

## PLY<a name="ply"> (BSD 3 clause)

A pure Python implementation of lex and yacc.

Used by PySMI.

## pg8000<a name="pg8000"> (BSD 3 clause)

A Pure-Python interface to the PostgreSQL database engine

## docker-py<a name="docker-py"> (Apache 2.0)

A docker client for Python.  For additional details, please visit the [docker-py github repository](https://github.com/docker/docker-py).

The `docker_monitor` depends on this library.

Currently this library is just a straight copy, but with references to the websocket-client module removed, due to being licensed under LGPL.

## docker-pycreds<a name="docker-pycreds"> (Apache 2.0)

Python bindings for the docker credentials store API.  A dependency of docker-py.  See project home [here](https://github.com/shin-/dockerpy-creds/).

## ipaddress<a name="ipaddress"> (PSF 2.0)

IPv4/IPv6 manipulation library.  A dependency of docker-py.  See project home [here](https://github.com/phihag/ipaddress).

## six<a name="six"> (MIT)

Python 2 and 3 compatibility utilities.  A dependency of docker-py.  See project home [here](http://pypi.python.org/pypi/six/).

## backports.ssl-match-hostname<a name="ssl-match-hostname"> (PSF)

The ssl.match_hostname() function from Python 3.5.  A dependency of docker-py.  See project home [here](http://bitbucket.org/brandon/backports.ssl_match_hostname).

## PySocks<a name="PySocks"> (BSD 3 clause)

PySocks library.  Used to enable SOCKS support for Requests.

## glob2<a name="glob2"> (BSD 2 clause)

An extended version of Python's builtin glob module which adds support for recursive '**' globbing syntax. See project home [here](https://github.com/miracle2k/python-glob2).
