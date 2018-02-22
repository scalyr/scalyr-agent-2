
import scalyr_agent.third_party.requests as requests
import scalyr_agent.json_lib as json_lib
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonConversionException, JsonMissingFieldException

class Kubernetes( object ):
    """Simple wrapper class for querying the k8s api
    """

    def __init__( self, ca_file='/run/secrets/kubernetes.io/serviceaccount/ca.crt' ):
        """Init the kubernetes object
        """

        # fixed well known location for authentication token required to
        # query the API
        token_file="/var/run/secrets/kubernetes.io/serviceaccount/token"
        self._http_host="https://kubernetes.default"
        self._timeout = 10.0

        self._session = None

        self._ca_file = ca_file

        # We create a few headers ahead of time so that we don't have to recreate them each time we need them.
        self._standard_headers = {
            'Connection': 'Keep-Alive',
            'Accept': 'application/json',
        }

        token = ''

        try:
            # using with is ok here, because we need to be running
            # a recent version of python for various 3rd party libs
            with open( token_file, 'r' ) as f:
                token = f.read()
        except IOError, e:
            pass

        self._standard_headers["Authorization"] = "Bearer %s" % (token)

    def _verify_connection( self ):
        """ Return whether or not to use SSL verification
        """
        if self._ca_file:
            return self._ca_file
        return False

    def _ensure_session( self ):
        """Create the session if it doesn't exist, otherwise do nothing
        """
        if not self._session:
            self._session = requests.Session()
            self._session.headers.update( self._standard_headers )

    def query_api( self, path, pretty=0 ):
        """ Queries the k8s API at 'path', and converts OK responses to JSON objects
        """
        self._ensure_session()
        url = self._http_host + path + '?pretty=%d' % (pretty)
        response = self._session.get( url, verify=self._verify_connection(), timeout=self._timeout )
        if response.status_code != 200:
            raise Exception( "Invalid response from Kubernetes API when querying '%s': %s" %( path, str( response ) ) )
        return json_lib.parse( response.text )

    def query_pod( self, namespace, pod ):
        """Wrapper to query a pod in a namespace"""
        return self.query_api( '/api/v1/namespaces/%s/pods/%s' % (namespace, pod) )

    def query_pods( self, namespace ):
        """Wrapper to query all pods in a namespace"""
        return self.query_api( '/api/v1/namespaces/%s/pods' % (namespace) )

    def query_namespaces( self ):
        """Wrapper to query all namespaces"""
        return self.query_api( '/api/v1/namespaces' )
