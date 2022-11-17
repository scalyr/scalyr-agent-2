# Building and publishing of the Linux Managed Packages.

In order to provide Linux packages that does not depend on system's Python interpreter
we build our own Python interpreter and ship it as a separate ``dependency`` package for 
the agent package.

The structure of this package has to guarantee that files for these packages does not interfere with 
files of local system Python interpreter. To achieve that, agent's Python interpreter 
package files are installed in their own ``sub-directories``

```
/usr/libe/scalyr-agent-2-dependecies
/usr/libexec/scalyr-agent-2-dependecies
/usr/shared/scalyr-agent-2-dependecies
/usr/include/scalyr-agent-2-dependecies
```

Agent package is build with specifying this Python package as a dependency and, when installed, it is configured to 
run with this Python.

## Python interpreter compatibility

We build our Python interpreter inside Centos:6 and that gives us decent GLIBC versions compatibility.

# Agent libs dependency package.

There's also another dependency package that the agent's package depends on. This package contains all agent 
requirement libraries such as ``requests``, ``orjson`` etc. If agent requirements are changed, we only have to build 
and re-publish this package without re-publishing the Python package.

Agent libs package also follows the same filesystem structure as Python package.