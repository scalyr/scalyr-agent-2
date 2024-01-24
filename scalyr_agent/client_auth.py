import datetime
import json
import urllib
from base64 import b64encode

from urllib.parse import urlparse

from scalyr_agent.third_party import requests


class ClientAuth(object):
    def __init__(self, configuration, headers):
        self.configuration = configuration
        self.headers = headers
        if self.configuration.auth == "oauth2":
            self.auth = OAuth2(self.configuration, self.headers)
        elif self.configuration.auth == "bearer":
            self.auth = BearerToken(self.configuration, self.headers)
        else:
            self.auth = NoAuth(self.configuration, self.headers)

    def authenticate(self):
        return self.auth.authenticate()

class NoAuth(object):
    def __init__(self, configuration, headers):
        self.headers = headers

    def authenticate(self):
        # Add a header just so for traceability
        self.headers["x-no-auth"]="true"
        return True

# Simple Authorization Header as Bearer Token using `api_key` configuration
class BearerToken(object):
    def __init__(self, configuration, headers):
        headers.set("Authorization", "Bearer " + configuration.api_key)

    def authenticate(self):
        return True

# Implement https://datatracker.ietf.org/doc/html/rfc6749#section-4.4 flow
class OAuth2(object):
    def __init__(self, configuration, headers):
        self.headers = headers # Headers modified for external requests
        self.client_id = configuration.client_id
        self.client_secret = configuration.client_secret
        self.token_url = configuration.token_url
        scopes = " ".join(configuration.scopes)
        # Payload Body for the token exchange
        self.auth_request = "grant_type=client_credentials&scope=" + urllib.parse.quote_plus(scopes)
        # Our token to use in requests
        self.token = None
        # When the token expires
        self.expiry_time = datetime.datetime.now()
        self.verify_ssl = configuration.verify_server_certificate
        # Authentication Headers for the token exchange
        authorization_header_value = b64encode( bytes(('' + self.client_id + ':' + self.client_secret).encode("utf-8"))).decode('utf-8')
        self.auth_headers = { "Content-Type": "application/x-www-form-urlencoded", "Authorization" : "Basic " + authorization_header_value}

    def authenticate(self):
        if self.token == None or self.expiry_time < datetime.datetime.now():
            print("Request/Refresh OAuth2 Token")
            if not self.refresh_token():
                raise Exception("OAuth2: Unable to refresh token")
        self.headers["Authorization"]="Bearer " + self.token
        return True

    def refresh_token(self):
        resp = requests.post(self.token_url, data=self.auth_request, headers=self.auth_headers, verify=self.verify_ssl)
        if resp.status_code == 200:
            auth_response = json.loads(resp.content)
            self.token = auth_response["access_token"]
            self.expiry_time = datetime.datetime.now() + datetime.timedelta(seconds=auth_response["expires_in"])
            return True
        else:
            raise Exception("Unable to obtain OAuth2 Token: " + str(resp.status_code) + "(" + str(resp.content) + ")")
        return False
