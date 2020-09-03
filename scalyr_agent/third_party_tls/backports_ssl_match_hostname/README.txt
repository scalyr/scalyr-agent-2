
The ssl.match_hostname() function from Python 3.7
=================================================

The Secure Sockets Layer is only actually *secure*
if you check the hostname in the certificate returned
by the server to which you are connecting,
and verify that it matches to hostname
that you are trying to reach.

But the matching logic, defined in `RFC2818`_,
can be a bit tricky to implement on your own.
So the ``ssl`` package in the Standard Library of Python 3.2
and greater now includes a ``match_hostname()`` function
for performing this check instead of requiring every application
to implement the check separately.

This backport brings ``match_hostname()`` to users
of earlier versions of Python.
Simply make this distribution a dependency of your package,
and then use it like this::

    from backports.ssl_match_hostname import match_hostname, CertificateError
    [...]
    sslsock = ssl.wrap_socket(sock, ssl_version=ssl.PROTOCOL_SSLv23,
                              cert_reqs=ssl.CERT_REQUIRED, ca_certs=...)
    try:
        match_hostname(sslsock.getpeercert(), hostname)
    except CertificateError, ce:
        ...

Brandon Craig Rhodes is merely the packager of this distribution;
the actual code inside comes from Python 3.7 with small changes for
portability.


Requirements
------------

* If you need to use this on Python versions earlier than 2.6 you will need to
  install the `ssl module`_.  From Python 2.6 upwards ``ssl`` is included in
  the Python Standard Library so you do not need to install it separately.

.. _`ssl module`:: https://pypi.python.org/pypi/ssl

History
-------

* This function was introduced in python-3.2
* It was updated for python-3.4a1 for a CVE 
  (backports-ssl_match_hostname-3.4.0.1)
* It was updated from RFC2818 to RFC 6125 compliance in order to fix another
  security flaw for python-3.3.3 and python-3.4a5
  (backports-ssl_match_hostname-3.4.0.2)
* It was updated in python-3.5 to handle IPAddresses in ServerAltName fields
  (something that backports.ssl_match_hostname will do if you also install the
  ipaddress library from pypi).
* It was updated in python-3.7 to handle IPAddresses without the ipaddress library and dropped
  support for partial wildcards

.. _`ipaddress module`:: https://pypi.python.org/pypi/ipaddress

.. _RFC2818: http://tools.ietf.org/html/rfc2818.html
