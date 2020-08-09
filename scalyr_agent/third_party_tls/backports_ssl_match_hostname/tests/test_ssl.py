# coding: utf-8
# Test the support for SSL and sockets

import sys
import socket

# Divergence: unittest2 so that we have assertRaisesRegexp
if sys.version_info < (3,):
    import unittest2 as unittest
else:
    import unittest

from backports import ssl_match_hostname as ssl


class BasicSocketTests(unittest.TestCase):

    def test_match_hostname(self):
        def ok(cert, hostname):
            ssl.match_hostname(cert, hostname)
        def fail(cert, hostname):
            self.assertRaises(ssl.CertificateError,
                              ssl.match_hostname, cert, hostname)

        # -- Hostname matching --

        cert = {'subject': ((('commonName', 'example.com'),),)}
        ok(cert, 'example.com')
        ok(cert, 'ExAmple.cOm')
        fail(cert, 'www.example.com')
        fail(cert, '.example.com')
        fail(cert, 'example.org')
        fail(cert, 'exampleXcom')

        cert = {'subject': ((('commonName', '*.a.com'),),)}
        ok(cert, 'foo.a.com')
        fail(cert, 'bar.foo.a.com')
        fail(cert, 'a.com')
        fail(cert, 'Xa.com')
        fail(cert, '.a.com')

        # only match wildcards when they are the only thing
        # in left-most segment
        cert = {'subject': ((('commonName', 'f*.com'),),)}
        fail(cert, 'foo.com')
        fail(cert, 'f.com')
        fail(cert, 'bar.com')
        fail(cert, 'foo.a.com')
        fail(cert, 'bar.foo.com')

        # NULL bytes are bad, CVE-2013-4073
        cert = {'subject': ((('commonName',
                              'null.python.org\x00example.org'),),)}
        ok(cert, 'null.python.org\x00example.org') # or raise an error?
        fail(cert, 'example.org')
        fail(cert, 'null.python.org')

        # error cases with wildcards
        cert = {'subject': ((('commonName', '*.*.a.com'),),)}
        fail(cert, 'bar.foo.a.com')
        fail(cert, 'a.com')
        fail(cert, 'Xa.com')
        fail(cert, '.a.com')

        cert = {'subject': ((('commonName', 'a.*.com'),),)}
        fail(cert, 'a.foo.com')
        fail(cert, 'a..com')
        fail(cert, 'a.com')

        # wildcard doesn't match IDNA prefix 'xn--'
        # Divergence: explicitly mark text string with u
        idna = u'püthon.python.org'.encode("idna").decode("ascii")
        cert = {'subject': ((('commonName', idna),),)}
        ok(cert, idna)
        cert = {'subject': ((('commonName', 'x*.python.org'),),)}
        fail(cert, idna)
        cert = {'subject': ((('commonName', 'xn--p*.python.org'),),)}
        fail(cert, idna)

        # wildcard in first fragment and  IDNA A-labels in sequent fragments
        # are supported.
        # Divergence: explicitly mark text strings with u
        idna = u'www*.pythön.org'.encode("idna").decode("ascii")
        cert = {'subject': ((('commonName', idna),),)}
        fail(cert, u'www.pythön.org'.encode("idna").decode("ascii"))
        fail(cert, u'www1.pythön.org'.encode("idna").decode("ascii"))
        fail(cert, u'ftp.pythön.org'.encode("idna").decode("ascii"))
        fail(cert, u'pythön.org'.encode("idna").decode("ascii"))

        # Slightly fake real-world example
        cert = {'notAfter': 'Jun 26 21:41:46 2011 GMT',
                'subject': ((('commonName', 'linuxfrz.org'),),),
                'subjectAltName': (('DNS', 'linuxfr.org'),
                                   ('DNS', 'linuxfr.com'),
                                   ('othername', '<unsupported>'))}
        ok(cert, 'linuxfr.org')
        ok(cert, 'linuxfr.com')
        # Not a "DNS" entry
        fail(cert, '<unsupported>')
        # When there is a subjectAltName, commonName isn't used
        fail(cert, 'linuxfrz.org')

        # A pristine real-world example
        cert = {'notAfter': 'Dec 18 23:59:59 2011 GMT',
                'subject': ((('countryName', 'US'),),
                            (('stateOrProvinceName', 'California'),),
                            (('localityName', 'Mountain View'),),
                            (('organizationName', 'Google Inc'),),
                            (('commonName', 'mail.google.com'),))}
        ok(cert, 'mail.google.com')
        fail(cert, 'gmail.com')
        # Only commonName is considered
        fail(cert, 'California')

        # -- IPv4 matching --
        cert = {'subject': ((('commonName', 'example.com'),),),
                'subjectAltName': (('DNS', 'example.com'),
                                   ('IP Address', '10.11.12.13'),
                                   ('IP Address', '14.15.16.17'))}
        ok(cert, '10.11.12.13')
        ok(cert, '14.15.16.17')
        fail(cert, '14.15.16.18')
        fail(cert, 'example.net')

        # -- IPv6 matching --
        if hasattr(socket, 'AF_INET6'):
            cert = {'subject': ((('commonName', 'example.com'),),),
                    'subjectAltName': (
                        ('DNS', 'example.com'),
                        ('IP Address', '2001:0:0:0:0:0:0:CAFE\n'),
                        ('IP Address', '2003:0:0:0:0:0:0:BABA\n'))}
            ok(cert, '2001::cafe')
            ok(cert, '2003::baba')
            fail(cert, '2003::bebe')
            fail(cert, 'example.net')

        # -- Miscellaneous --

        # Neither commonName nor subjectAltName
        cert = {'notAfter': 'Dec 18 23:59:59 2011 GMT',
                'subject': ((('countryName', 'US'),),
                            (('stateOrProvinceName', 'California'),),
                            (('localityName', 'Mountain View'),),
                            (('organizationName', 'Google Inc'),))}
        fail(cert, 'mail.google.com')

        # No DNS entry in subjectAltName but a commonName
        cert = {'notAfter': 'Dec 18 23:59:59 2099 GMT',
                'subject': ((('countryName', 'US'),),
                            (('stateOrProvinceName', 'California'),),
                            (('localityName', 'Mountain View'),),
                            (('commonName', 'mail.google.com'),)),
                'subjectAltName': (('othername', 'blabla'), )}
        ok(cert, 'mail.google.com')

        # No DNS entry subjectAltName and no commonName
        cert = {'notAfter': 'Dec 18 23:59:59 2099 GMT',
                'subject': ((('countryName', 'US'),),
                            (('stateOrProvinceName', 'California'),),
                            (('localityName', 'Mountain View'),),
                            (('organizationName', 'Google Inc'),)),
                'subjectAltName': (('othername', 'blabla'),)}
        fail(cert, 'google.com')

        # Empty cert / no cert
        self.assertRaises(ValueError, ssl.match_hostname, None, 'example.com')
        self.assertRaises(ValueError, ssl.match_hostname, {}, 'example.com')

        # Issue #17980: avoid denials of service by refusing more than one
        # wildcard per fragment.
        cert = {'subject': ((('commonName', 'a*b.example.com'),),)}
        with self.assertRaisesRegex(
                ssl.CertificateError,
                "partial wildcards in leftmost label are not supported"):
            ssl.match_hostname(cert, 'axxb.example.com')

        cert = {'subject': ((('commonName', 'www.*.example.com'),),)}
        with self.assertRaisesRegex(
                ssl.CertificateError,
                "wildcard can only be present in the leftmost label"):
            ssl.match_hostname(cert, 'www.sub.example.com')

        cert = {'subject': ((('commonName', 'a*b*.example.com'),),)}
        with self.assertRaisesRegex(
                ssl.CertificateError,
                "too many wildcards"):
            ssl.match_hostname(cert, 'axxbxxc.example.com')

        cert = {'subject': ((('commonName', '*'),),)}
        with self.assertRaisesRegex(
                ssl.CertificateError,
                "sole wildcard without additional labels are not support"):
            ssl.match_hostname(cert, 'host')

        cert = {'subject': ((('commonName', '*.com'),),)}
        with self.assertRaisesRegex(
                ssl.CertificateError,
                r"hostname 'com' doesn't match '\*.com'"):
            ssl.match_hostname(cert, 'com')

        # extra checks for _inet_paton()
        for invalid in ['1', '', '1.2.3', '256.0.0.1', '127.0.0.1/24']:
            with self.assertRaises(ValueError):
                ssl._inet_paton(invalid)
        for ipaddr in ['127.0.0.1', '192.168.0.1']:
            self.assertTrue(ssl._inet_paton(ipaddr))
        if hasattr(socket, 'AF_INET6'):
            for ipaddr in ['::1', '2001:db8:85a3::8a2e:370:7334']:
                self.assertTrue(ssl._inet_paton(ipaddr))
