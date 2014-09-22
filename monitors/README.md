Third-party monitor plugins
===================================

The `contrib` and `local` directories can be used to hold monitor plugins developed by third parties (non-Scalyr
engineers).

The `contrib` directory should be used by developers who wish to contribute their plugins to the main Scalyr repository
so that other Scalyr customers can use them.

The `local` directory should be used by developers who do not wish to contribute their plugins, but rather just
wish to keep the plugins in their own forked repositories and included in any packages built by them using the
`build_package.py` tool.
