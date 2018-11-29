
import hashlib
import logging
import os
import random
import string

import scalyr_agent.monitor_utils.annotation_config as annotation_config
import scalyr_agent.third_party.requests as requests
import scalyr_agent.util as util
from scalyr_agent.json_lib import JsonObject
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

class KubeletApiException( Exception ):
    """A wrapper around Exception that makes it easier to catch k8s specific
    exceptions
    """
    pass

class PodInfo( object ):
    """
        A collection class that stores label and other information about a kubernetes pod
    """
    def __init__( self, name='', namespace='', uid='', node_name='', labels={}, container_names=[], annotations={}, deployment_name=None, daemonset_name=None ):

        self.name = name
        self.namespace = namespace
        self.uid = uid
        self.node_name = node_name
        self.labels = labels
        self.container_names = container_names
        self.annotations = annotations
        self.deployment_name = deployment_name
        self.daemonset_name = daemonset_name

        # generate a hash we can use to compare whether or not
        # any of the pod info has changed
        md5 = hashlib.md5()
        md5.update( name )
        md5.update( namespace )
        md5.update( uid )
        md5.update( node_name )

        # flatten the labels dict in to a single string because update
        # expects a string arg.  To avoid cases where the 'str' of labels is
        # just the object id, we explicitly create a flattened string of
        # key/value pairs
        flattened = []
        for k,v in labels.iteritems():
            flattened.append( k )
            flattened.append( v )
        md5.update( ''.join( flattened ) )

        # flatten the container names
        # see previous comment for why flattening is necessary
        md5.update( ''.join( container_names ) )

        # flatten the annotations dict in to a single string
        # see previous comment for why flattening is necessary
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
            exclude = util.value_to_bool( annotations.get('exclude', default) )

            # include will always override value of exclude if both exist
            exclude = not util.value_to_bool( annotations.get('include', not exclude) )

            return exclude

        result = exclude_status( self.annotations, default )

        if container_name and container_name in self.annotations:
            result = exclude_status( self.annotations[container_name], result )

        return result

class DaemonSetInfo( object ):
    """
        Class for cached DaemonSet objects
    """
    def __init__( self, name='', namespace='', labels={} ):
        self.name = name
        self.namespace = namespace
        self.labels = labels
        flat_labels = []
        for key, value in labels.iteritems():
            flat_labels.append( "%s=%s" % (key, value) )

        self.flat_labels = ','.join( flat_labels )

class ReplicaSetInfo( object ):
    """
        Class for cached ReplicaSet objects
    """
    def __init__( self, name='', namespace='', deployment_name=None ):
        self.name = name
        self.namespace = namespace
        self.deployment_name = deployment_name

class DeploymentInfo( object ):
    """
        Class for cached Deployment objects
    """
    def __init__( self, name='', namespace='', labels={} ):

        self.name = name
        self.namespace = namespace
        self.labels = labels
        flat_labels = []
        for key, value in labels.iteritems():
            flat_labels.append( "%s=%s" % (key, value) )

        self.flat_labels = ','.join( flat_labels )

class _K8sCache( object ):
    """
        A lazily updated cache of objects from a k8s api query

        This is a private class to this module.  See KubernetesCache which instantiates
        instances of _K8sCache for querying different k8s API objects.

        A full update of cached data occurs whenever the cache is queried and
        `cache_expiry_secs` have passed since the last full update.

        If a cache miss occurs e.g. objects were created since the last cache update but
        that is not yet reflected in the cached data, individual queries to the
        api are made that get the required data only, and no more.

        If too many cache misses occur within `cache_miss_interval` (e.g. a large
        number of objects were created since the last full cache update) this will also
        trigger a full update of the cache.

        This abstraction is thread-safe-ish, assuming objects returned
        from querying the cache are never written to.
    """

    def __init__( self, logger, processor, object_type, cache_expiry_secs=120, max_cache_misses=20, cache_miss_interval=10 ):
        """
            Initialises a Kubernees Cache
            @param: logger - a Scalyr logger
            @param: processor - a _K8sProcessor object for querying/processing the k8s api
            @param: object_type - a string containing a textual name of the objects being cached, for use in log messages
            @param: cache_expiry_secs - the number of seconds to wait before doing a full update of data from the k8s api
            @param: max_cache_misses - the maximum of number of cache misses that can occur in
                                       `cache_miss_interval` before doing a full update of data from the k8s api
            @param: cache_miss_interval - the number of seconds that `max_cache_misses` can occur in before a full
                                          update of the cache occurs
        """
        # protects self.objects
        self._lock = threading.Lock()

        # dict of object dicts.  The outer dict is hashed by namespace,
        # and the inner dict is hashed by object name
        self._objects = {}

        self._logger = logger
        self._processor = processor
        self._object_type = object_type,

        self._cache_expiry_secs = cache_expiry_secs
        self._last_full_update = time.time() - cache_expiry_secs - 1
        self._last_cache_miss_update = self._last_full_update
        self._max_cache_misses = max_cache_misses
        self._cache_miss_interval = cache_miss_interval
        self._query_cache_miss = 0

    def shallow_copy(self):
        """Returns a shallow copy of all the cached objects dict"""
        result = {}
        self._lock.acquire()
        try:
            for k, v in self._objects.iteritems():
                result[k] = v
        finally:
            self._lock.release()

        return result

    def _update( self, current_time ):
        """ do a full update of all information from the API
        """

        try:
            self._logger.log(scalyr_logging.DEBUG_LEVEL_1, 'Attempting to update k8s data from API' )
            query_result = self._processor.query_all_objects()
            objects = self._process_objects( query_result )
        except Exception, e:
            self._logger.warning( "Exception occurred when updating k8s %s cache.  Cache was not updated %s\n%s" % (self._object_type, str( e ), traceback.format_exc()) )
            # early return because we don't want to update our cache with bad data,
            # but wait at least another full cache expiry before trying again
            self._last_full_update = current_time
            return

        self._lock.acquire()
        try:
            self._objects = objects
            self._last_full_update = current_time
        finally:
            self._lock.release()


    def _update_object( self, namespace, name ):
        """ update a single object, returns the object if found, otherwise return None """
        result = None
        try:
            # query k8s api and process objects
            obj = self._processor.query_object( namespace, name )
            result = self._processor.process_object( obj )
        except K8sApiException, e:
            # Don't do anything here.  This means the object we are querying doensn't exist
            # and it's up to the caller to handle this by detecting a None result
            pass

        # update our cache if we have a result
        if result:
            self._logger.log( scalyr_logging.DEBUG_LEVEL_2, "Processing single %s: %s/%s" % (self._object_type, result.namespace, result.name) )
            self._lock.acquire()
            try:
                if result.namespace not in self._objects:
                    self._objects[result.namespace] = {}
                current = self._objects[result.namespace]
                current[result.name] = result

            finally:
                self._lock.release()

        return result

    def _process_objects( self, objects ):
        """
            Processes the dict returned from querying the objects and calls the _K8sProcessor to create relevant objects for caching,

            @param objects: The JSON object returned as a response from quering all objects.  This JSON object should contain an
                         element called 'items', which is an array of dicts

            @return: a dict keyed by namespace, whose values are a dict of objects inside that namespace, keyed by objects name
        """

        # get all objects
        items = objects.get( 'items', [] )

        # iterate over all objects, getting Info objects and storing them in the result
        # dict, hashed by namespace and object name
        result = {}
        for obj in items:
            info = self._processor.process_object( obj )
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "Processing %s: %s:%s" % (self._object_type, info.namespace, info.name) )

            if info.namespace not in result:
                result[info.namespace] = {}

            current = result[info.namespace]
            if info.name in current:
                self._logger.warning( "Duplicate %s '%s' found in namespace '%s', overwriting previous values" % (self._object_type, info.name, info.namespace),
                                      limit_once_per_x_secs=300, limit_key='duplicate-%s-%s' % (self._object_type, info.uid) )

            current[info.name] = info

        return result


    def _expired( self, current_time ):
        """ returns a boolean indicating whether the cache has expired
        """
        return self._last_full_update + self._cache_expiry_secs < current_time

    def update_if_expired( self, current_time ):
        """
        If the cache has expired, perform a full update of all object information from the API
        """
        if self._expired( current_time ):
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "k8s %s cache expired, performing full update" % self._object_type )
            self._update( current_time )


    def _update_if_cache_miss_count_exceeds_threshold( self, current_time ):
        """
            If too many cache misses happen on single object queries within a short timespan
            force an update of all objects.
            return: True if updated, False otherwise
        """

        updated = False
        if self._query_cache_miss > self._max_cache_misses:
            self._logger.log( scalyr_logging.DEBUG_LEVEL_1, "Too many k8s %s cache misses, performing full update" % self._object_type )
            self._update( current_time )
            updated = True
        return updated

    def _lookup_object( self, namespace, name, current_time ):
        """ Look to see if the object specified by the namespace and name
        exists within the cached data.

        Return the object info, or None if not found
        """
        result = None
        self._lock.acquire()
        try:
            objects = self._objects.get( namespace, {} )
            result = objects.get( name, None )

            # check for cache misses
            if result is None:
                # if we are within the last cache miss interval, increment miss count
                if current_time < self._last_cache_miss_update + self._cache_miss_interval:
                    self._query_cache_miss += 1
                else:
                    # otherwise reset the interval and miss count
                    self._query_cache_miss = 1
                    self._last_cache_miss_update = current_time

        finally:
            self._lock.release()

        return result

    def lookup( self, namespace, name, current_time=None ):
        """ returns info for the object specified by namespace and name
        or None if no object is found in the cache.

        Querying the information is thread-safe, but the returned object should
        not be written to.
        """

        # update the cache if we are expired
        if current_time is None:
            current_time = time.time()

        self.update_if_expired( current_time )

        # see if the object exists in the cache and return it if so
        result = self._lookup_object( namespace, name, current_time )
        if result:
            self._logger.log( scalyr_logging.DEBUG_LEVEL_2, "cache hit for %s %s/%s" % (self._object_type, namespace, name) )
            return result

        # do a full update if too many cache misses in a short period
        # of time
        if self._update_if_cache_miss_count_exceeds_threshold( current_time ):
            # object might exist in the cache now, so check again
            result = self._lookup_object( namespace, name, current_time )
        else:
            # otherwise query objects individually
            self._logger.log( scalyr_logging.DEBUG_LEVEL_2, "cache miss for %s %s/%s" % (self._object_type, namespace, name) )
            result = self._update_object( namespace, name )

        return result

class _K8sProcessor( object ):
    """
        An abstract interface used by _K8sCache for querying a specific type of
        object from the k8s api, and generating python objects from the queried result JSON.
    """

    def __init__( self, k8s, logger, filter=None ):
        """
            @param: k8s - a KubernetesApi object for query the k8s api
            @param: logger - a Scalyr logger object for logging
            @param: filter - a field selector filter when doing bulk query items (e.g. to limit the results to the current node)
        """
        self._k8s = k8s
        self._logger = logger
        self._filter = filter

    def _get_managing_controller( self, items, kind=None ):
        """
            Processes a list of items, searching to see if one of them
            is a 'managing controller', which is determined by the 'controller' field

            @param: items - an array containing 'ownerReferences' metadata for an object
                            returned from the k8s api
            @param: kind - a string containing the expected type of the managing controller.
                           if the managing controller is not of this type then None will also be returned

            @return: A dict containing the managing controller of type `kind` or None if no such controller exists
        """
        for i in items:
            controller = i.get( 'controller', False )
            if kind is not None:
                controller_kind = i.get( 'kind', None )
            if controller and controller_kind == kind:
                return i

        return None

    def query_all_objects( self ):
        """
        Queries the k8s api for all objects of a specific type (determined by subclasses).
        @return - a dict containing at least one element called 'items' which is an array of dicts
                  returned by the query
        """
        return { 'items': [] }

    def query_object( self, namespace, name ):
        """
        Queries the k8s api for a single object of a specific type (determined by subclasses).
        @param: namespace - the namespace to query in
        @param: name - the name of the object
        @return - a dict returned by the query
        """
        return {}

    def process_object( self, obj ):
        """
        Creates a python object based of a dict
        @param obj: A JSON dict returned as a response to querying
                    the k8s API for a specific object type.
        @return a python object relevant to the
        """
        pass

class PodProcessor( _K8sProcessor ):

    def __init__( self, k8s, logger, filter, replicasets, daemonsets ):
        super( PodProcessor, self).__init__( k8s, logger, filter )
        self._replicasets = replicasets
        self._daemonsets = daemonsets

    def query_all_objects( self ):
        """
        Queries the k8s api for all Pods that match self._filter
        @return - a dict containing an element called 'items' which is an array of Pods
                  returned by the query
        """
        return self._k8s.query_pods( filter=self._filter )

    def query_object( self, namespace, name ):
        """
        Queries the k8s api for a single pod
        @param: namespace - the namespace to query in
        @param: name - the name of the pod
        @return - a dict containing the Pod information returned by the query
        """
        return self._k8s.query_pod( namespace, name )

    def _get_deployment_name_from_owners( self, owners, namespace ):
        """
            Processes a list of owner references returned from a Pod's metadata to see
            if it is eventually owned by a Deployment, and if so, returns the name of the deployment

            @return String - the name of the deployment that owns this object
        """
        replicaset = None
        owner = self._get_managing_controller( owners, 'ReplicaSet' )

        # check if we are owned by a replicaset
        if owner:
            name = owner.get( 'name', None )
            if name is None:
                return None
            replicaset = self._replicasets.lookup( namespace, name )

        if replicaset is None:
            return None

        return replicaset.deployment_name

    def _get_daemonset_name_from_owners( self, owners, namespace ):
        """
            Processes a list of owner references returned from a Pod's metadata to see
            if it is eventually owned by a daemonset, and if so, returns the name of the daemonset

            @return String - the name of the daemonset that owns this object
        """
        daemonset = None
        owner = self._get_managing_controller( owners, 'DaemonSet' )

        # check if we are owned by a daemonset
        if owner:
            name = owner.get( 'name', None )
            if name is None:
                return None
            daemonset = self._daemonsets.lookup( namespace, name )

        if daemonset is None:
            return None

        return daemonset.name

    def process_object( self, obj ):
        """ Generate a PodInfo object from a JSON object
        @param pod: The JSON object returned as a response to querying
            a specific pod from the k8s API

        @return A PodInfo object
        """

        result = {}

        metadata = obj.get( 'metadata', {} )
        spec = obj.get( 'spec', {} )
        labels = metadata.get( 'labels', {} )
        annotations = metadata.get( 'annotations', {} )
        owners = metadata.get( 'ownerReferences', [] )

        pod_name = metadata.get( "name", '' )
        namespace = metadata.get( "namespace", '' )

        deployment_name = self._get_deployment_name_from_owners( owners, namespace )
        daemonset_name = self._get_daemonset_name_from_owners( owners, namespace )

        container_names = []
        for container in spec.get( 'containers', [] ):
            container_names.append( container.get( 'name', 'invalid-container-name' ) )

        try:
            annotations = annotation_config.process_annotations( annotations )
        except BadAnnotationConfig, e:
            self._logger.warning( "Bad Annotation config for %s/%s.  All annotations ignored. %s" % (namespace, pod_name, str( e )),
                                  limit_once_per_x_secs=300, limit_key='bad-annotation-config-%s' % info.uid )
            annotations = JsonObject()


        self._logger.log( scalyr_logging.DEBUG_LEVEL_2, "Annotations: %s" % ( str( annotations ) ) )

        # create the PodInfo
        result = PodInfo( name=pod_name,
                          namespace=namespace,
                          uid=metadata.get( "uid", '' ),
                          node_name=spec.get( "nodeName", '' ),
                          labels=labels,
                          container_names=container_names,
                          annotations=annotations,
                          deployment_name=deployment_name,
                          daemonset_name=daemonset_name)
        return result

class ReplicaSetProcessor( _K8sProcessor ):

    def __init__( self, k8s, logger, deployments ):
        super( ReplicaSetProcessor, self).__init__( k8s, logger )
        self._deployments = deployments

    def query_all_objects( self ):
        """
        Queries the k8s api for all ReplicaSets that match self._filter
        @return - a dict containing an element called 'items' which is an array of ReplicaSets
                  returned by the query
        """
        return self._k8s.query_replicasets( filter=self._filter )

    def query_object( self, namespace, name ):
        """
        Queries the k8s api for a single ReplicaSet
        @param: namespace - the namespace to query in
        @param: name - the name of the ReplicaSet
        @return - a dict containing the ReplicaSet information returned by the query
        """
        return self._k8s.query_replicaset( namespace, name )


    def process_object( self, obj ):
        """ Generate a ReplicaSetInfo object from a JSON object
        @param obj: The JSON object returned as a response to querying
            a specific replicaset from the k8s API

        @return A ReplicaSetInfo object
        """

        metadata = obj.get( 'metadata', {} )
        owners = metadata.get( 'ownerReferences', [] )
        namespace = metadata.get( "namespace", '' )
        name = metadata.get( "name", '' )
        deployment_name = None

        owner = self._get_managing_controller( owners, 'Deployment' )
        if owner is not None:
            owner_name = owner.get( 'name', None )
            if owner_name is not None:
                deployment = self._deployments.lookup( namespace, owner_name )
                if deployment:
                    deployment_name = deployment.name

        return ReplicaSetInfo( name, namespace, deployment_name )

class DeploymentProcessor( _K8sProcessor ):

    def query_all_objects( self ):
        """
        Queries the k8s api for all Deployments that match self._filter
        @return - a dict containing an element called 'items' which is an array of Deployments
                  returned by the query
        """
        return self._k8s.query_deployments( filter=self._filter )

    def query_object( self, namespace, name ):
        """
        Queries the k8s api for a single deployment
        @param: namespace - the namespace to query in
        @param: name - the name of the deployment
        @return - a dict containing the Deployment information returned by the query
        """
        return self._k8s.query_deployment( namespace, name )


    def process_object( self, obj ):
        """ Generate a DeploymentInfo object from a JSON object
        @param obj: The JSON object returned as a response to querying
            a specific deployment from the k8s API

        @return A DeploymentInfo object
        """
        metadata = obj.get( 'metadata', {} )
        namespace = metadata.get( "namespace", '' )
        name = metadata.get( "name", '' )
        labels = metadata.get( 'labels', {} )

        return DeploymentInfo( name, namespace, labels )

class DaemonSetProcessor( _K8sProcessor ):

    def query_all_objects( self ):
        """
        Queries the k8s api for all DaemonSets that match self._filter
        @return - a dict containing an element called 'items' which is an array of DaemonSets
                  returned by the query
        """
        return self._k8s.query_daemonsets( filter=self._filter )

    def query_object( self, namespace, name ):
        """
        Queries the k8s api for a single DaemonSet
        @param: namespace - the namespace to query in
        @param: name - the name of the DaemonSet
        @return - a dict containing the DaemonSet information returned by the query
        """
        return self._k8s.query_daemonset( namespace, name )


    def process_object( self, obj ):
        """ Generate a DaemonSet object from a JSON object
        @param obj: The JSON object returned as a response to querying
            a specific DaemonSet from the k8s API

        @return A DaemonSetInfo object
        """
        metadata = obj.get( 'metadata', {} )
        namespace = metadata.get( "namespace", '' )
        name = metadata.get( "name", '' )
        labels = metadata.get( 'labels', {} )

        return DaemonSetInfo( name, namespace, labels )

class KubernetesCache( object ):

    def __init__( self, k8s, logger, cache_expiry_secs=120, max_cache_misses=20, cache_miss_interval=10, filter=None ):

        # create the daemonset cache
        daemonset_processor = DaemonSetProcessor( k8s, logger )
        self._daemonsets = _K8sCache( logger, daemonset_processor, 'daemonset',
                               cache_expiry_secs=cache_expiry_secs,
                               max_cache_misses=max_cache_misses,
                               cache_miss_interval=cache_miss_interval )

        # create the deployment cache
        deployment_processor = DeploymentProcessor( k8s, logger )
        self._deployments = _K8sCache( logger, deployment_processor, 'deployment',
                               cache_expiry_secs=cache_expiry_secs,
                               max_cache_misses=max_cache_misses,
                               cache_miss_interval=cache_miss_interval )

        # create the replicaset cache
        replicaset_processor = ReplicaSetProcessor( k8s, logger, self._deployments )
        self._replicasets = _K8sCache( logger, replicaset_processor, 'replicaset',
                               cache_expiry_secs=cache_expiry_secs,
                               max_cache_misses=max_cache_misses,
                               cache_miss_interval=cache_miss_interval )

        # create the pod cache
        pod_processor = PodProcessor( k8s, logger, filter, self._replicasets, self._daemonsets )
        self._pods = _K8sCache( logger, pod_processor, 'pod',
                               cache_expiry_secs=cache_expiry_secs,
                               max_cache_misses=max_cache_misses,
                               cache_miss_interval=cache_miss_interval )

        self._k8s = k8s
        self._cluster_name = None
        self._cache_expiry_secs = cache_expiry_secs
        self._last_full_update = time.time() - cache_expiry_secs - 1

    def daemonset( self, namespace, name, current_time=None ):
        """
            Returns cached daemonset info for the daemonset specified by namespace and name
            or None if no daemonset matches.

            Querying the daemonset information is thread-safe but the returned object should
            not be written to.
        """
        return self._daemonsets.lookup( namespace, name, current_time )

    def deployment( self, namespace, name, current_time=None ):
        """
            Returns cached deployment info for the deployment specified by namespace and name
            or None if no deployment matches.

            Querying the deployment information is thread-safe but the returned object should
            not be written to.
        """
        return self._deployments.lookup( namespace, name, current_time )


    def pod( self, namespace, name, current_time=None ):
        """ returns pod info for the pod specified by namespace and name
        or None if no pad matches.

        Querying the pod information is thread-safe, but the returned object should
        not be written to.
        """
        return self._pods.lookup( namespace, name, current_time )

    def pods_shallow_copy(self):
        """Retuns a shallow copy of the pod objects"""
        return self._pods.shallow_copy()

    def get_cluster_name( self, current_time=None ):
        """Returns the cluster name"""
        if current_time is None:
            current_time = time.time()

        if self._last_full_update + self._cache_expiry_secs < current_time:
            self._cluster_name = self._k8s.get_cluster_name()
            self._last_full_update = current_time

        return self._cluster_name

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

    def get_cluster_name( self ):
        """ Returns the name of the cluster running this agent.

        There is no way to get this from the k8s API so we check the following:

        If the environment variable SCALYR_K8S_CLUSTER_NAME is set, then use that.

        Otherwise query the api for the pod running the agent container and check to see
        if it has an annotation: agent.config.scalyr.com/cluster_name, and if so, use that.

        Otherwise return None
        """

        cluster = os.environ.get( 'SCALYR_K8S_CLUSTER_NAME' )
        if cluster:
            return cluster

        pod_name = self.get_pod_name()
        pod = self.query_pod( self.namespace, pod_name )

        if pod is None:
            return None

        metadata = pod.get( 'metadata', {} )
        annotations = metadata.get( 'annotations', {} )

        if 'agent.config.scalyr.com/cluster_name' in annotations:
            return annotations['agent.config.scalyr.com/cluster_name']

        # If the user did not specify any cluster name, we need to supply a default that will be the same for all
        # other scalyr agents connected to the same cluster.  Unfortunately, k8s does not actually supply the cluster
        # name via any API, so we must make one up.
        # We create a random string using the creation timestamp of the default timestamp as a seed.  The idea is that
        # that creation timestamp should never change and all agents connected to the cluster will see the same value
        # for that seed.
        namespaces = self.query_namespaces()

        # Get the creation timestamp from the default namespace.  We try to be very defensive in case the API changes.
        if namespaces and 'items' in namespaces:
            for item in namespaces['items']:
                if 'metadata' in item and 'name' in item['metadata'] and item['metadata']['name'] == 'default':
                    if 'creationTimestamp' in item['metadata']:
                        return 'k8s-cluster-%s' % self.__create_random_string(item['metadata']['creationTimestamp'], 6)
        return None

    def __create_random_string(self, seed_string, num_chars):
        """
        Return a random string of num_char characters, composed of uppercase characters and digits.

        @param seed_string: The seed to use when creating the psrng
        @param num_chars: The desired size of the string.

        @type seed_string: str
        @type num_chars: int
        @return: A random string
        @rtype: str
        """
        prng = random.Random(abs(hash(seed_string)))
        return ''.join(prng.choice(string.ascii_lowercase + string.digits) for _ in range(num_chars))



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

        return util.json_decode( response.text )

    def query_pod( self, namespace, pod ):
        """Wrapper to query a pod in a namespace"""
        if not pod or not namespace:
            return {}

        query = '/api/v1/namespaces/%s/pods/%s' % (namespace, pod)
        return self.query_api( query )

    def query_pods( self, namespace=None, filter=None ):
        """Wrapper to query all pods in a namespace, or across the entire cluster
           A value of None for namespace will search for the pod across the entire cluster.
           This is handled in the 'query_objects' method.  This method is just a convenience
           wrapper that passes in the appropriate urls for pod objects
        """
        return self.query_objects( '/api/v1/pods', '/api/v1/namespaces/%s/pods', namespace, filter )

    def query_replicaset( self, namespace, name ):
        """Wrapper to query a replicaset in a namespace"""
        if not name or not namespace:
            return {}

        query = '/apis/apps/v1/namespaces/%s/replicasets/%s' % (namespace, name)
        return self.query_api( query )

    def query_replicasets( self, namespace=None, filter=None ):
        """Wrapper to query all replicasets in a namespace, or across the entire cluster
           A value of None for namespace will search for the replicaset across the entire cluster.
           This is handled in the 'query_objects' method.  This method is just a convenience
           wrapper that passes in the appropriate urls for the replicaset objects
        """
        return self.query_objects( '/apis/apps/v1/replicasets', '/apis/apps/v1/namespaces/%s/replicasets', namespace, filter )

    def query_deployment( self, namespace, name ):
        """Wrapper to query a deployment in a namespace"""
        if not name or not namespace:
            return {}

        query = '/apis/apps/v1/namespaces/%s/deployments/%s' % (namespace, name)
        return self.query_api( query )

    def query_deployments( self, namespace=None, filter=None ):
        """Wrapper to query all deployments in a namespace, or across the entire cluster
           A value of None for namespace will search for the deployment across the entire cluster.
           This is handled in the 'query_objects' method.  This method is just a convenience
           wrapper that passes in the appropriate urls for the deployment objects
        """
        return self.query_objects( '/apis/apps/v1/deployments', '/apis/apps/v1/namespaces/%s/deployments', namespace, filter )

    def query_daemonset( self, namespace, name ):
        """Wrapper to query a daemonset in a namespace"""
        if not name or not namespace:
            return {}

        query = '/apis/apps/v1/namespaces/%s/daemonsets/%s' % (namespace, name)
        return self.query_api( query )

    def query_daemonsets( self, namespace=None, filter=None ):
        """Wrapper to query all daemonsets in a namespace, or across the entire cluster
           A value of None for namespace will search for the daemonset across the entire cluster.
           This is handled in the 'query_objects' method.  This method is just a convenience
           wrapper that passes in the appropriate urls for the daemonset objects
        """
        return self.query_objects( '/apis/apps/v1/daemonsets', '/apis/apps/v1/namespaces/%s/daemonsets', namespace, filter )

    def query_objects( self, url, namespaced_url, namespace=None, filter=None ):
        """Wrapper to query all objects at a url in a namespace, or across the entire cluster"""
        query = url
        if namespace:
            query = namespaced_url % (namespace)

        if filter:
            query = "%s?fieldSelector=%s" % (query, urllib.quote( filter ))

        return self.query_api( query )

    def query_namespaces( self ):
        """Wrapper to query all namespaces"""
        return self.query_api( '/api/v1/namespaces' )

class KubeletApi( object ):
    """
        A class for querying the kubelet API
    """

    def __init__( self, k8s, port=10255 ):
        """
        @param k8s - a KubernetesApi object
        """
        pod_name = k8s.get_pod_name()
        pod = k8s.query_pod( k8s.namespace, pod_name )
        spec = pod.get( 'spec', {} )
        status = pod.get( 'status', {} )

        host_ip = status.get( 'hostIP', None )

        if host_ip is None:
            raise KubeletApiException( "Unable to get host IP for pod: %s/%s" % (k8s.namespace, pod_name) )

        self._session = requests.Session()
        headers = {
            'Accept': 'application/json',
        }
        self._session.headers.update( headers )

        self._http_host = "http://%s:%d" % ( host_ip, port )
        self._timeout = 10.0

    def query_api( self, path ):
        """ Queries the kubelet API at 'path', and converts OK responses to JSON objects
        """
        url = self._http_host + path
        response = self._session.get( url, timeout=self._timeout )
        if response.status_code != 200:
            global_log.log(scalyr_logging.DEBUG_LEVEL_3, "Invalid response from Kubelet API.\n\turl: %s\n\tstatus: %d\n\tresponse length: %d"
                % ( url, response.status_code, len(response.text)), limit_once_per_x_secs=300, limit_key='kubelet_api_query' )
            raise KubeletApiException( "Invalid response from Kubelet API when querying '%s': %s" %( path, str( response ) ) )

        return util.json_decode( response.text )

    def query_stats( self ):
        return self.query_api( '/stats/summary')

