
import hashlib
import logging
import os
import scalyr_agent.monitor_utils.annotation_config as annotation_config
import scalyr_agent.third_party.requests as requests
import scalyr_agent.json_lib as json_lib
from scalyr_agent.json_lib import JsonObject
from scalyr_agent.json_lib import JsonConversionException, JsonMissingFieldException
import threading
import time
import traceback
import scalyr_agent.scalyr_logging as scalyr_logging

import urllib

global_log = scalyr_logging.getLogger(__name__)

class K8sApiException( Exception ):
    """A wrapper around Exception that makes it easier to catch k8s specific
    exceptions
    """
    pass

class PodInfo( object ):
    """
        A collection class that stores label and other information about a kubernetes pod
    """
    def __init__( self, name='', namespace='', uid='', node_name='', labels={}, container_names=[], annotations={} ):

        self.name = name
        self.namespace = namespace
        self.uid = uid
        self.node_name = node_name
        self.labels = labels
        self.container_names = container_names
        self.annotations = annotations

        # generate a hash we can use to compare whether or not
        # any of the pod info has changed
        md5 = hashlib.md5()
        md5.update( name )
        md5.update( namespace )
        md5.update( uid )
        md5.update( node_name )

        # flatten the labels dict in to a single string
        flattened = []
        for k,v in labels.iteritems():
            flattened.append( k )
            flattened.append( v )
        md5.update( ''.join( flattened ) )

        # flatten the container names
        md5.update( ''.join( container_names ) )

        # flatten the annotations dict in to a single string
        flattened = []
        for k,v in annotations.iteritems():
            flattened.append( k )
            flattened.append( str(v) )

        md5.update( ''.join( flattened ) )

        self.digest = md5.digest()

    def exclude_pod( self, container_name=None, default=False ):
        """
            Returns whether or not this pod should be excluded based
            on include/exclude annotations.  If an annotation 'exclude' exists
            then this will be returned.  If an annotation 'include' exists, then
            the boolean opposite of 'include' will be returned.  'include' will
            always override 'exclude' if it exists.

            param: container_name - if specified, and container_name exists in
              the pod annotations, then the container specific annotations will
              also be checked.  These will supercede the pod level include/exclude
              annotations
            param: default - Boolean the default value if no annotations are found

            return Boolean - whether or not to exclude this pod
        """

        def exclude_status( annotations, default ):
            exclude = annotations.get_bool('exclude', default_value=default)

            # include will always override value of exclude if both exist
            exclude = not annotations.get_bool('include', default_value=not exclude)

            return exclude

        result = exclude_status( self.annotations, default )

        if container_name and container_name in self.annotations:
            result = exclude_status( self.annotations[container_name], result )

        return result

class KubernetesCache( object ):
    """
        A lazily updated cache for k8s api queries

        A full update of cached data occurs whenever the cache is queried and
        `cache_expiry_secs` have passed since the last full update.

        If a cache miss occurs e.g. pods were created since the last cache update but
        that is not yet reflected in the cached data, individual queries to the
        api are made that get the required data only, and no more.

        If too many cache misses occur within `cache_miss_interval` (e.g. a large
        number of pods were created since the last full cache update) this will also
        trigger a full update of the cache.

        This abstraction is thread-safe-ish, assuming objects returned
        from querying the cache are never written to.
    """

    def __init__( self, k8s, logger, cache_expiry_secs=120, max_cache_misses=20, cache_miss_interval=10, filter=None ):
        """
            Initialises a Kubernees Cache
            @param: k8s - a KubernetesApi object
            @param: logger - a Scalyr logger
            @param: cache_expiry_secs - the number of seconds to wait before doing a full update of data from the k8s api
            @param: max_cache_misses - the maximum of number of cache misses that can occur in
                                       `cache_miss_interval` before doing a full update of data from the k8s api
            @param: cache_miss_interval - the number of seconds that `max_cache_misses` can occur in before a full
                                          update of the cache occurs
            @param: filter - a field selector filter when doing bulk query items (e.g. to limit the results to the current node)
        """
        # protects self.pods
        self._lock = threading.Lock()

        # dict of pods dicts.  The outer dict is hashed by namespace,
        # and the inner dict is hashed by pod
        self._pods = {}

        self._k8s = k8s
        self._logger = logger
        self._filter = filter

        self._cache_expiry_secs = cache_expiry_secs
        self._last_full_update = time.time() - cache_expiry_secs - 1
        self._last_pod_cache_miss_update = self._last_full_update
        self._max_cache_misses = max_cache_misses
        self._cache_miss_interval = cache_miss_interval
        self._pod_query_cache_miss = 0


    def pods_shallow_copy(self):
        """Retuns a shallow copy of the pods dict"""
        result = {}
        self._lock.acquire()
        try:
            for k, v in self._pods.iteritems():
                result[k] = v
        finally:
            self._lock.release()

        return result

    def _update( self, current_time ):
        """ do a full update of all pod information from the API
        """

        try:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, 'Attempting to update k8s data from API' )
            pods_result = self._k8s.query_pods( filter=self._filter )
            pods = self._process_pods( pods_result )
        except Exception, e:
            self._logger.warning( "Exception occurred when updating k8s cache.  Cache was not updated %s\n%s" % (str( e ), traceback.format_exc()) )
            # early return because we don't want to update our cache with bad data,
            # but wait at least another full cache expiry before trying again
            self._last_full_update = current_time
            return

        self._lock.acquire()
        try:
            self._pods = pods
            self._last_full_update = current_time
        finally:
            self._lock.release()


    def _update_pod( self, pod_namespace, pod_name ):
        """ update a single pod, returns the pod if found, otherwise return None """
        result = None
        try:
            # query k8s api and process pod
            pod = self._k8s.query_pod( pod_namespace, pod_name )
            result = self._process_pod( pod )
        except K8sApiException, e:
            # Don't do anything here.  This means the pod we are querying doensn't exist
            # and it's up to the caller to handle this by detecting a None result
            pass

        # update our cache if we have a result
        if result:
            self._logger.log( scalyr_logging.DEBUG_LEVEL_2, "Processing single pod: %s/%s" % (result.namespace, result.name) )
            self._lock.acquire()
            try:
                if result.namespace not in self._pods:
                    self._pods[result.namespace] = {}
                current = self._pods[result.namespace]
                current[result.name] = result

            finally:
                self._lock.release()

        return result

    def _process_pods( self, pods ):
        """
            Processes the JsonObject returned from querying the pods and creates PodInfo object,

            @param pods: The JSON object returned as a response from quering all pods

            @return: a dict keyed by namespace, whose values are a dict of pods inside that namespace, keyed by pod name
        """

        # get all pods
        items = pods.get( 'items', [] )

        # iterate over all pods, getting PodInfo and storing it in the result
        # dict, hashed by namespace and pod name
        result = {}
        for pod in items:
            info = self._process_pod( pod )
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "Processing pod: %s:%s" % (info.namespace, info.name) )

            if info.namespace not in result:
                result[info.namespace] = {}

            current = result[info.namespace]
            if info.name in current:
                self._logger.warning( "Duplicate pod '%s' found in namespace '%s', overwriting previous values" % (info.name, info.namespace),
                                      limit_once_per_x_secs=300, limit_key='duplicate-pod-%s' % info.uid )

            current[info.name] = info

        return result


    def _process_pod( self, pod ):
        """ Generate a PodInfo object from a JSON object
        @param pod: The JSON object returned as a response to querying
            a specific pod from the k8s API

        @return A PodInfo object
        """

        result = {}

        metadata = pod.get( 'metadata', {} )
        spec = pod.get( 'spec', {} )
        labels = metadata.get( 'labels', {} )
        annotations = metadata.get( 'annotations', {} )

        pod_name = metadata.get( "name", '' )
        namespace = metadata.get( "namespace", '' )

        container_names = []
        for container in spec.get( 'containers', [] ):
            container_names.append( container.get( 'name', 'invalid-container-name' ) )

        try:
            annotations = annotation_config.process_annotations( annotations )
        except BadAnnotationConfig, e:
            self._logger.warning( "Bad Annotation config for %s/%s.  All annotations ignored. %s" % (namespace, pod_name, str( e )),
                                  limit_once_per_x_secs=300, limit_key='bad-annotation-config-%s' % info.uid )
            annotations = {}


        self._logger.log( scalyr_logging.DEBUG_LEVEL_2, "Annotations: %s" % ( str( annotations ) ) )

        # create the PodInfo
        result = PodInfo( name=pod_name,
                          namespace=namespace,
                          uid=metadata.get( "uid", '' ),
                          node_name=spec.get( "nodeName", '' ),
                          labels=labels,
                          container_names=container_names,
                          annotations=annotations)
        return result

    def _expired( self, current_time ):
        """ returns a boolean indicating whether the cache has expired
        """
        return self._last_full_update + self._cache_expiry_secs < current_time

    def update_if_expired( self, current_time ):
        """
        If the cache has expired, perform a full update of all pod information from the API
        """
        if self._expired( current_time ):
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "k8s cache expired, performing full update" )
            self._update( current_time )


    def _update_if_pod_cache_miss_count_exceeds_threshold( self, current_time ):
        """
            If too many cache misses happen on single pod queries within a short timespan
            force an update of all pods.
            return: True if updated, False otherwise
        """

        updated = False
        if self._pod_query_cache_miss > self._max_cache_misses:
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "Too many k8s cache misses, performing full update " )
            self._update( current_time )
            updated = True
        return updated

    def _lookup_pod( self, pod_namespace, pod_name, current_time ):
        """ Look to see if the pod specified by the pod_namespace and pod_name
        exist within the cached data.

        Return the pod info, or None if not found
        """
        result = None
        self._lock.acquire()
        try:
            namespace = self._pods.get( pod_namespace, {} )
            result = namespace.get( pod_name, None )

            # check for cache misses
            if result is None:
                # if we are within the last cache miss interval, increment miss count
                if current_time < self._last_pod_cache_miss_update + self._cache_miss_interval:
                    self._pod_query_cache_miss += 1
                else:
                    # otherwise reset the interval and miss count
                    self._pod_query_cache_miss = 1
                    self._last_pod_cache_miss_update = current_time

        finally:
            self._lock.release()

        return result

    def pod( self, pod_namespace, pod_name, current_time=None ):
        """ returns pod info for the pod specified by pod_namespace and pod_name
        or None if no pad matches.

        Querying the pod information is thread-safe, but the returned object should
        not be written to.
        """

        # update the cache if we are expired
        if current_time is None:
            current_time = time.time()

        self.update_if_expired( current_time )

        # see if the pod exists in the cache and return it if so
        result = self._lookup_pod( pod_namespace, pod_name, current_time )
        if result:
            self._logger.log( scalyr_logging.DEBUG_LEVEL_2, "cache hit for pod %s/%s" % (pod_namespace, pod_name) )
            return result

        # do a full update if too many cache misses in a short period
        # of time
        if self._update_if_pod_cache_miss_count_exceeds_threshold( current_time ):
            # pod might exist in the cache now, so check again
            result = self._lookup_pod( pod_namespace, pod_name, current_time )
        else:
            # otherwise query pod individually
            self._logger.log( scalyr_logging.DEBUG_LEVEL_2, "cache miss for pod %s/%s" % (pod_namespace, pod_name) )
            result = self._update_pod( pod_namespace, pod_name )

        return result


class KubernetesApi( object ):
    """Simple wrapper class for querying the k8s api
    """

    def __init__( self, ca_file='/run/secrets/kubernetes.io/serviceaccount/ca.crt' ):
        """Init the kubernetes object
        """

        # fixed well known location for authentication token required to
        # query the API
        token_file="/var/run/secrets/kubernetes.io/serviceaccount/token"

        # fixed well known location for namespace file
        namespace_file="/var/run/secrets/kubernetes.io/serviceaccount/namespace"

        self._http_host="https://kubernetes.default"

        global_log.log( scalyr_logging.DEBUG_LEVEL_1, "Kubernetes API host: %s", self._http_host )
        self._timeout = 10.0

        self._session = None

        self._ca_file = ca_file

        # We create a few headers ahead of time so that we don't have to recreate them each time we need them.
        self._standard_headers = {
            'Connection': 'Keep-Alive',
            'Accept': 'application/json',
        }

        # The k8s API requires us to pass in an authentication token
        # which we can obtain from a token file in a 'well known' location
        token = ''

        try:
            # using with is ok here, because we need to be running
            # a recent version of python for various 3rd party libs
            with open( token_file, 'r' ) as f:
                token = f.read()
        except IOError, e:
            pass

        #get the namespace this pod is running on
        self.namespace = 'default'
        try:
            # using with is ok here, because we need to be running
            # a recent version of python for various 3rd party libs
            with open( namespace_file, 'r' ) as f:
                self.namespace = f.read()
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

    def get_pod_name( self ):
        """ Gets the pod name of the pod running the scalyr-agent """
        return os.environ.get( 'SCALYR_K8S_POD_NAME' ) or os.environ.get( 'HOSTNAME' )


    def get_node_name( self, pod_name ):
        """ Gets the node name of the node running the agent """
        node = os.environ.get( 'SCALYR_K8S_NODE_NAME' )
        if not node:
            pod = self.query_pod( self.namespace, pod_name )
            spec = pod.get( 'spec', {} )
            node = spec.get( 'nodeName' )
        return node

    def query_api( self, path, pretty=0 ):
        """ Queries the k8s API at 'path', and converts OK responses to JSON objects
        """
        self._ensure_session()
        pretty='pretty=%d' % pretty
        if "?" in path:
            pretty = '&%s' % pretty
        else:
            pretty = '?%s' % pretty

        url = self._http_host + path + pretty
        response = self._session.get( url, verify=self._verify_connection(), timeout=self._timeout )
        if response.status_code != 200:
            global_log.log(scalyr_logging.DEBUG_LEVEL_3, "Invalid response from K8S API.\n\turl: %s\n\tstatus: %d\n\tresponse length: %d"
                % ( url, response.status_code, len(response.text)), limit_once_per_x_secs=300, limit_key='k8s_api_query' )
            raise K8sApiException( "Invalid response from Kubernetes API when querying '%s': %s" %( path, str( response ) ) )
        return json_lib.parse( response.text )

    def query_pod( self, namespace, pod ):
        """Wrapper to query a pod in a namespace"""
        if not pod or not namespace:
            return JsonObject()

        query = '/api/v1/namespaces/%s/pods/%s' % (namespace, pod)
        return self.query_api( query )

    def query_pods( self, namespace=None, filter=None ):
        """Wrapper to query all pods in a namespace, or across the entire cluster"""
        query = '/api/v1/pods'
        if namespace:
            query = '/api/v1/namespaces/%s/pods' % (namespace)

        if filter:
            query = "%s?fieldSelector=%s" % (query, urllib.quote( filter ))

        return self.query_api( query )

    def query_namespaces( self ):
        """Wrapper to query all namespaces"""
        return self.query_api( '/api/v1/namespaces' )

