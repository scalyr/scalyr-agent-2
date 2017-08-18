import webtest
import webapp2
import unittest

import scalyr_agent.builtin_monitors.url_monitor as url_monitor


class UrlMonitorGetHandler(webapp2.RequestHandler):
    def get(self):
        # Create the handler's response "Hello World!" in plain text.
        self.response.headers['Content-Type'] = 'text/plain'
        self.response.out.write('Hello World!')


class AppTest(unittest.TestCase):
    def setUp(self):
        # Create a WSGI application.
        app = webapp2.WSGIApplication([('/', UrlMonitorGetHandler)])
        self.testapp = webtest.TestApp(app)

    def tearDown(self):
        pass

    def testUrlMonitorGetHandlerStatusOk(self):
        response = self.testapp.get('/')
        self.assertEqual(response.status_int, 200)
        self.assertEqual(response.normal_body, 'Hello World!')
        self.assertEqual(response.content_type, 'text/plain')

    def testFormRequestGet(self):
        request = url_monitor.UrlMonitor.form_request('/', 'GET', None, [], None)
        self.assertEqual(request.get_method(), 'GET')

    def testFormRequestGet(self):
        request = url_monitor.UrlMonitor.form_request('/', 'POST', None, [], None)
        self.assertEqual(request.get_method(), 'POST')
