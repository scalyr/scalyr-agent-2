from __future__ import unicode_literals
from __future__ import absolute_import

import fnmatch
import hashlib
import os
import random
import re
import warnings
from string import Template
import sys
import threading
import time
from time import strftime, gmtime
import traceback
from io import open

import six
import six.moves.urllib.request
import six.moves.urllib.parse
import six.moves.urllib.error
from six.moves import range

import scalyr_agent.monitor_utils.annotation_config as annotation_config
from scalyr_agent.monitor_utils.annotation_config import BadAnnotationConfig
from scalyr_agent.monitor_utils.blocking_rate_limiter import BlockingRateLimiter
import scalyr_agent.third_party.requests as requests
from scalyr_agent.util import StoppableThread
from scalyr_agent.json_lib import JsonObject

import scalyr_agent.scalyr_logging as scalyr_logging
import scalyr_agent.util as util
from scalyr_agent.compat import os_environ_unicode
from scalyr_agent.configuration import Configuration

global_log = scalyr_logging.getLogger(__name__)


# A regex for splitting a container id and runtime
_CID_RE = re.compile("^(.+)://(.+)$")

# endpoints used by the agent for querying the k8s api.  Having this mapping allows
# us to avoid special casing the logic for each different object type.  We can just
# look up the appropriate endpoint in this dict and query objects however we need.
#
# The dict is keyed by object kind, and or each object kind, there are 3 endpoints:
#       single, list and list all.
#
# `single` is for querying a single object of a specific type
# `list` is for querying all objects of a given type in a specific namespace
# `list-all` is for querying all objects of a given type in the entire cluster
#
# the `single` and `list` endpoints are Templates that require the caller to substitute
# in the appropriate values for ${namespace} and ${name}
_OBJECT_ENDPOINTS = {
    "CronJob": {
        "single": Template(
            "/apis/batch/v1beta1/namespaces/${namespace}/cronjobs/${name}"
        ),
        "list": Template("/apis/batch/v1beta1/namespaces/${namespace}/cronjobs"),
        "list-all": "/apis/batch/v1beta1/cronjobs",
    },
    "DaemonSet": {
        "single": Template("/apis/apps/v1/namespaces/${namespace}/daemonsets/${name}"),
        "list": Template("/apis/apps/v1/namespaces/${namespace}/daemonsets"),
        "list-all": "/apis/apps/v1/daemonsets",
    },
    "Deployment": {
        "single": Template("/apis/apps/v1/namespaces/${namespace}/deployments/${name}"),
        "list": Template("/apis/apps/v1/namespaces/${namespace}/deployments"),
        "list-all": "/apis/apps/v1/deployments",
    },
    "Job": {
        "single": Template("/apis/batch/v1/namespaces/${namespace}/jobs/${name}"),
        "list": Template("/apis/batch/v1/namespaces/${namespace}/jobs"),
        "list-all": "/apis/batch/v1/jobs",
    },
    "Pod": {
        "single": Template("/api/v1/namespaces/${namespace}/pods/${name}"),
        "list": Template("/api/v1/namespaces/${namespace}/pods"),
        "list-all": "/api/v1/pods",
    },
    "ReplicaSet": {
        "single": Template("/apis/apps/v1/namespaces/${namespace}/replicasets/${name}"),
        "list": Template("/apis/apps/v1/namespaces/${namespace}/replicasets"),
        "list-all": "/apis/apps/v1/replicasets",
    },
    "ReplicationController": {
        "single": Template(
            "/api/v1/namespaces/${namespace}/replicationcontrollers/${name}"
        ),
        "list": Template("/api/v1/namespaces/${namespace}/replicationcontrollers"),
        "list-all": "/api/v1/replicationcontrollers",
    },
    "StatefulSet": {
        "single": Template(
            "/apis/apps/v1/namespaces/${namespace}/statefulsets/${name}"
        ),
        "list": Template("/apis/apps/v1/namespaces/${namespace}/statefulsets"),
        "list-all": "/apis/apps/v1/statefulsets",
    },
}

# Template for an older kubelet endpoint that we may want to fall back to if the new one is unavailable due to an
# older kubernetes version
FALLBACK_KUBELET_URL_TEMPLATE = Template("http://${host_ip}:10255")


def cache(global_config):
    """
        Returns the global k8s cache, configured using the options in `config`
        @param config: The configuration
        @type config: A Scalyr Configuration object
    """
    cache_config = _CacheConfig(
        api_url=global_config.k8s_api_url,
        verify_api_queries=global_config.k8s_verify_api_queries,
        cache_expiry_secs=global_config.k8s_cache_expiry_secs,
        cache_expiry_fuzz_secs=global_config.k8s_cache_expiry_fuzz_secs,
        cache_start_fuzz_secs=global_config.k8s_cache_start_fuzz_secs,
        cache_purge_secs=global_config.k8s_cache_purge_secs,
        query_timeout=global_config.k8s_cache_query_timeout_secs,
        global_config=global_config,
    )

    # update the config and return current cache
    _k8s_cache.update_config(cache_config)
    return _k8s_cache


def terminate_agent_process(reason):
    """Terminate this agent process, causing the pod running the agent to restart the agent container.

    :param reason: The termination reason which will be written in the K8s termination log and crash report.
    :type reason: six.text_type
    """
    try:
        with open("/dev/termination-log", "w") as fp:
            fp.write(reason)
    finally:
        sys.exit(1)


class K8sApiException(Exception):
    """A wrapper around Exception that makes it easier to catch k8s specific
    exceptions
    """

    def __init__(self, message, status_code=0):
        super(K8sApiException, self).__init__(message)
        self.status_code = status_code


class K8sApiTemporaryError(K8sApiException):
    """The base class for all temporary errors where a retry may result in success (timeouts, too many requests,
    etc) returned when issuing requests to the K8s API server
    """

    def __init__(self, message, status_code=0):
        super(K8sApiTemporaryError, self).__init__(message, status_code=status_code)


class K8sApiPermanentError(K8sApiException):
    """The base class for all permanent errors where a retry will always fail until human action is taken
    (authorization errors, object not found) returned when issuing requests to the K8s API server
    """

    def __init__(self, message, status_code=0):
        super(K8sApiPermanentError, self).__init__(message, status_code=status_code)


class K8sApiAuthorizationException(K8sApiPermanentError):
    """A wrapper around Exception that makes it easier to catch k8s authorization
    exceptions
    """

    def __init__(self, path, status_code=0):
        super(K8sApiAuthorizationException, self).__init__(
            "You don't have permission to access %s.  Please ensure you have correctly configured the RBAC permissions for the scalyr-agent's service account"
            % path,
            status_code=status_code,
        )


# K8sApiNotFoundException needs to be a TemporaryError because there are cases
# when a pod is starting up that querying the pods endpoint will return 404 Not Found
# but then the same query a few seconds later (once the pod is up and running) will return
# 200 - Ok.  Having it derive from PermanentError would put it on a blacklist, when all we
# might want is to back off for a few seconds and try again
class K8sApiNotFoundException(K8sApiTemporaryError):
    """
    A wrapper around Exception that makes it easier to catch not found errors when querying the k8s api
    """

    def __init__(self, path, status_code=0):
        super(K8sApiNotFoundException, self).__init__(
            "The resource at location `%s` was not found" % path,
            status_code=status_code,
        )


class KubeletApiException(Exception):
    """A wrapper around Exception that makes it easier to catch k8s specific
    exceptions
    """

    pass


class K8sNamespaceFilter(object):
    """
    Represents a filter on Kubernetes namespaces.  This filter can be be created via both whitelists and
    blacklists.  This abstraction will then return True or False given a namespace to indicate if it
    passes the filter (i.e., is included in the whitelist and not included in the blacklist).

    For legacy reasons, it also has logic in it to differiente between global and local blacklist.  This
    is to provide backward compatibility for when the blacklist was just an option on the Kubernetes monitor
    (local) and not an option on the global configuration file (global).
    """

    def __init__(self, global_include, global_ignore, local_ignore=None):
        """Constructs a filter given the different whitelist (include list) and blacklists (exclude lists).
        Note, for convenience, all namespaces are stripped of trailing and leading whitespace.  (Whitespace
        could be introduced via customers putting spaces between commas in the comma separate list.)

        :param global_include: The list of namespaces to include.  If the list is empty or a single element of "*",
            then all namespaces will pass the filter except for those in the blacklist (if any).
        :param global_ignore: The list of namespaces to exclude, as specified at the global level.  If this
            list is the same as the default list and `local_ignore` is not None, then the local_ignore list will
            be used.
        :param local_ignore: The list of namespaces to exclude, as specified at the local level.  This list is only
            used if the `global_ignore` list is not the same as the default.
        :type global_include: [six.text_type]
        :type global_ignore: [six.text_type]
        :type local_ignore: [six.text_type]
        """

        default_blacklist = self.__namespace_set(
            Configuration.DEFAULT_K8S_IGNORE_NAMESPACES
        )
        blacklist = self.__namespace_set(global_ignore)
        # If the global list is the same as the default one, it probably means the customer has not changed
        # this value at the global level.  In that case, we defer to the local one if it exits.
        if blacklist == default_blacklist and local_ignore is not None:
            blacklist = self.__namespace_set(local_ignore)

        # Only one of __whitelist or __blacklist will be None.  If __whitelist is not None, then that means
        # we are filtering from a whitelist and only the specified namespaces should be allowed.  Otherwise, by
        # default, we allow all namespaces except those specifically blacklisted.
        whitelist = self.__namespace_set(global_include)
        if not whitelist or whitelist == set("*"):
            self.__whitelist = None
            self.__blacklist = blacklist
        else:
            self.__whitelist = whitelist - blacklist
            self.__blacklist = None

    def passes(self, namespace):
        """Returns true if the given namespace passes the filter.  This means the namespace is in the whitelist
        (or the whitelist is *) and does not appear in the blacklist.
        :param namespace: The namespace to test
        :type namespace: six.text_type
        :return: True if the namespace passes the filter.
        :rtype: bool
        """
        return namespace in self

    @staticmethod
    def include_all():
        """
        :return: A filter that will pass all namespaces.
        :rtype: K8sNamespaceFilter
        """
        return K8sNamespaceFilter(global_include=["*"], global_ignore=[])

    @staticmethod
    def default_value():
        """Returns the filter created by the configuration when all the defaults are used.
        :return: The default filter.
        :rtype: K8sNamespaceFilter
        """
        return K8sNamespaceFilter(
            global_include=Configuration.DEFAULT_K8S_INCLUDE_NAMESPACES,
            global_ignore=Configuration.DEFAULT_K8S_IGNORE_NAMESPACES,
        )

    @staticmethod
    def from_config(global_config=None, local_config=None):
        """Convenience method for created a filter object based on the global configuration file and
        a monitor's configuration.

        :param global_config: The global configuraiton object.  This is used to retrieve the global include and ignore
            list.
        :param local_config: The local configuration object, if any.  If not None, this is used to retrieve the
            local ignore list.
        :type global_config: Configuration
        :type local_config: MonitorConfiguration
        :return: The filter.
        :rtype: K8sNamespaceFilter
        """
        global_ignore = global_config.k8s_ignore_namespaces
        global_include = global_config.k8s_include_namespaces

        if local_config is not None:
            local_ignore = local_config.get("k8s_ignore_namespaces")
        else:
            local_ignore = None
        return K8sNamespaceFilter(
            global_include=global_include,
            global_ignore=global_ignore,
            local_ignore=local_ignore,
        )

    @staticmethod
    def __namespace_set(namespace_list):
        """Creates a set containing the names in the specified list.  This also (for convenience) strips out
        leading and trailing whitespace.

        :param namespace_list: The list of namespaces
        :type namespace_list: [six.text_type]
        :return: The set
        :rtype: set
        """
        result = set()
        if namespace_list is None:
            return result

        for x in namespace_list:
            result.add(x.strip())

        return result

    def __contains__(self, key):
        """Returns true if the given namespace passes the filter.  This means the namespace is in the whitelist
        (or the whitelist is *) and does not appear in the blacklist.

        :param key: The namespace to test
        :type key: six.text_type
        :return: True if the namespace passes the filter.
        :rtype: bool
        """
        if self.__whitelist is not None:
            return key in self.__whitelist
        else:
            return key not in self.__blacklist

    def __str__(self):
        if self.__whitelist is not None:
            return "include_only=%s" % ",".join(sorted(self.__whitelist))
        else:
            return "exclude=%s" % ",".join(sorted(self.__blacklist))

    def __eq__(self, other):
        if self.__whitelist is not None:
            return self.__whitelist == other.__whitelist
        else:
            return self.__blacklist == other.__blacklist

    def __ne__(self, other):
        return not self == other


class QualifiedName(object):
    """
    Represents a fully qualified name for a Kubernetes object using both its name and namespace.
    """

    __slots__ = ("namespace", "name")

    def __init__(self, namespace, name):
        self.namespace = namespace
        self.name = name

    def __eq__(self, other):
        return self.namespace == other.namespace and self.name == other.name

    def __ne__(self, other):
        return not self.__eq__(other)

    def is_valid(self):
        return self.namespace is not None and self.name is not None


class PodInfo(object):
    """
        A collection class that stores label and other information about a kubernetes pod
    """

    def __init__(
        self,
        name="",
        namespace="",
        uid="",
        node_name="",
        labels={},
        container_names=[],
        annotations={},
        controller=None,
    ):

        self.name = name
        self.namespace = namespace
        self.uid = uid
        self.node_name = node_name
        self.labels = labels
        self.container_names = container_names
        self.annotations = annotations

        self.controller = controller  # controller can't change for the life of the object so we don't include it in hash

        # generate a hash we can use to compare whether or not
        # any of the pod info has changed
        md5 = hashlib.md5()
        md5.update(name)
        md5.update(namespace)
        md5.update(uid)
        md5.update(node_name)

        # flatten the labels dict in to a single string because update
        # expects a string arg.  To avoid cases where the 'str' of labels is
        # just the object id, we explicitly create a flattened string of
        # key/value pairs
        flattened = []
        for k, v in six.iteritems(labels):
            flattened.append(k)
            flattened.append(v)
        md5.update("".join(flattened))

        # flatten the container names
        # see previous comment for why flattening is necessary
        md5.update("".join(container_names))

        # flatten the annotations dict in to a single string
        # see previous comment for why flattening is necessary
        flattened = []
        for k, v in six.iteritems(annotations):
            flattened.append(k)
            flattened.append(six.text_type(v))

        md5.update("".join(flattened))

        self.digest = md5.digest()

    def exclude_pod(self, container_name=None, default=False):
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

        def exclude_status(annotations, default):
            exclude = util.value_to_bool(annotations.get("exclude", default))

            # include will always override value of exclude if both exist
            exclude = not util.value_to_bool(annotations.get("include", not exclude))

            return exclude

        result = exclude_status(self.annotations, default)

        if container_name and container_name in self.annotations:
            result = exclude_status(self.annotations[container_name], result)

        return result


class Controller(object):
    """
        General class for all cached Controller objects
    """

    def __init__(
        self,
        name="",
        namespace="",
        kind="",
        parent_name=None,
        parent_kind=None,
        labels={},
    ):
        self.name = name
        self.namespace = namespace
        self.kind = kind
        self.access_time = None
        self.parent_name = parent_name
        self.parent_kind = parent_kind
        flat_labels = []
        for key, value in six.iteritems(labels):
            flat_labels.append("%s=%s" % (key, value))

        self.flat_labels = ",".join(flat_labels)


class ApiQueryOptions(object):
    """Options to use when querying the K8s Api server.
    """

    def __init__(self, max_retries=3, return_temp_errors=True, rate_limiter=None):
        """
        @param max_retries:  The number of times we will retry a query if it receives a temporary error before failing.
        @param return_temp_errors:  If true, all non-known errors will automatically be categorized as temporary errors.
        @param rate_limiter:  Rate limiter for api calls
        """
        self.max_retries = max_retries
        self.return_temp_errors = return_temp_errors
        self.rate_limiter = rate_limiter

    def __repr__(self):
        return (
            "ApiQueryOptions\n\tmax_retries=%s\n\treturn_temp_errors=%s\n\trate_limiter=%s\n"
            % (self.max_retries, self.return_temp_errors, self.rate_limiter)
        )


class _K8sCache(object):
    """
        A cached store of objects from a k8s api query

        This is a private class to this module.  See KubernetesCache which instantiates
        instances of _K8sCache for querying different k8s API objects.

        This abstraction is thread-safe-ish, assuming objects returned
        from querying the cache are never written to.
    """

    def __init__(self, processor, object_type):
        """
            Initialises a Kubernetes Cache
            @param processor: a _K8sProcessor object for querying/processing the k8s api
            @param object_type: a string containing a textual name of the objects being cached, for use in log messages
        """
        # protects self._objects and self._objects_expired
        self._lock = threading.Lock()

        # dict of object dicts.  The outer dict is hashed by namespace,
        # and the inner dict is hashed by object name
        self._objects = {}

        # Identical to self._objects but contains optional expired booleans for corresponding object
        # New object won't have an entry.  Only older objects that have been "soft purged" will be marked
        # with a boolean (True).
        # Note:
        #   Expirations should ideally be stored in the _objects dict itself alongside objects.  However,
        #   the long-term direction for this feature is uncertain and so this is a temporary implementation
        #   needed to support the notion of a "soft purge".
        self._objects_expired = {}
        self._processor = processor
        self._object_type = object_type

    def shallow_copy(self):
        """Returns a shallow copy of all the cached objects dict"""
        result = {}
        self._lock.acquire()
        try:
            for k, v in six.iteritems(self._objects):
                result[k] = v
        finally:
            self._lock.release()

        return result

    def __get_stale_objects(self, access_time):
        """Get all stale objects.  Caller should first obtain lock on self._objects"""
        stale = []
        for namespace, objs in six.iteritems(self._objects):
            for obj_name, obj in six.iteritems(objs):
                if hasattr(obj, "access_time"):
                    if obj.access_time is None or obj.access_time < access_time:
                        stale.append((namespace, obj_name))
        return stale

    def mark_as_expired(self, access_time):
        """Mark all stale cache objects as expired

        @param access_time:  Any objects last accessed before access_time will be purged
        """
        self._lock.acquire()
        try:
            stale = self.__get_stale_objects(access_time)
            for (namespace, obj_name) in stale:
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "Mark object %s/%s as expired in cache" % (namespace, obj_name),
                )
                expired_set = self._objects_expired.setdefault(namespace, {})
                expired_set.setdefault(obj_name, True)
        finally:
            self._lock.release()

    def purge_unused(self, access_time):
        """Removes any items from the store who haven't been accessed since `access_time`

        @param access_time:  Any objects last accessed before access_time will be purged
        """
        self._lock.acquire()
        try:
            stale = self.__get_stale_objects(access_time)
            for (namespace, obj_name) in stale:
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "Removing object %s/%s from cache" % (namespace, obj_name),
                )
                self._objects[namespace].pop(obj_name, None)
                self._objects_expired.get(namespace, {}).pop(obj_name, None)
        finally:
            self._lock.release()

    def _update_object(
        self, k8s, kind, namespace, name, current_time, query_options=None
    ):
        """update a single object, returns the object if found, otherwise return None

        This method will always raise a K8SApiException upon k8s api response failure.  It is the responsibility of the
        caller to handle exceptions.
        """
        result = None
        # query k8s api and process objects
        obj = k8s.query_object(kind, namespace, name, query_options=query_options)
        result = self._processor.process_object(k8s, obj, query_options=query_options)
        self._add_to_cache(result)
        return result

    def _add_to_cache(self, obj):
        """
        Adds the object `obj` to the cache.
        """
        # update our cache if we have an obj
        if obj:
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_2,
                "Processing single %s: %s/%s"
                % (self._object_type, obj.namespace, obj.name),
            )
            self._lock.acquire()
            try:
                # update the object
                objects = self._objects.setdefault(obj.namespace, {})
                objects[obj.name] = obj

                # remove expired flag
                expired_dict = self._objects_expired.setdefault(obj.namespace, {})
                expired_dict.pop(obj.name, None)
            finally:
                self._lock.release()

    def _lookup_object(
        self, namespace, name, current_time, allow_expired=True, query_options=None
    ):
        """ Look to see if the object specified by the namespace and name exists within the cached data.

        Note: current_time should be provided (otherwise, access_time-based revalidation of cache won't work correctly,
        for example, manifesting as unnecessary re-queries of controller metadata)

        Return the object info, or None if not found

        @param namespace: The object's namespace
        @param name: The object's name
        @param current_time last access time for the object to this value.
        @param allow_expired: If true, return the object if it exists in the cache even if expired.
            If false, return None if the object exists but is expired.

        @type namespace: six.text_type
        @type name: six.text_type
        @type current_time: epoch seconds
        @type allow_expired: bool
        """
        result = None
        self._lock.acquire()
        try:
            # Optionally check if the object has been marked as expired. If so, return None.
            if not allow_expired:
                expired = self._objects_expired.setdefault(namespace, {}).get(
                    name, False
                )
                if expired:
                    return None

            objects = self._objects.get(namespace, {})
            result = objects.get(name, None)

            # update access time
            if result is not None and current_time is not None:
                result.access_time = current_time

        finally:
            self._lock.release()

        return result

    def is_cached(self, namespace, name, allow_expired):
        """Returns true if the specified object is in the cache and (optionally) not expired.

        @param namespace: The object's namespace
        @param name: The object's name
        @param allow_expired: If True, an object is considered present in cache even if it is expired.

        @type namespace: six.text_type
        @type name: six.text_type
        @type allow_expired: bool

        @return: True if the object is cached.  If check_expiration is True and an expiration
            time exists for the object, then return True only if not expired
        @rtype: bool
        """
        # TODO: Look at passing down a consistent time from layers above
        return (
            self._lookup_object(
                namespace, name, time.time(), allow_expired=allow_expired
            )
            is not None
        )

    def lookup(
        self,
        k8s,
        current_time,
        namespace,
        name,
        kind=None,
        allow_expired=True,
        query_options=None,
        ignore_k8s_api_exception=False,
    ):
        """Returns info for the object specified by namespace and name or None if no object is found in the cache.

        Querying the information is thread-safe, but the returned object should not be written to.

        This method will propagate upwards K8SApiExceptions generated by k8s api response failure.
        It is the responsibility of the caller to handle exceptions.

        @param allow_expired: If True, an object is considered present in cache even if it is expired.
        @type allow_expired: bool
        """
        if kind is None:
            kind = self._object_type

        # see if the object exists in the cache and return it if so
        result = self._lookup_object(
            namespace,
            name,
            current_time,
            allow_expired=allow_expired,
            query_options=None,
        )
        if result:
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_2,
                "cache hit for %s %s/%s" % (kind, namespace, name),
            )
            return result

        # we have a cache miss so query the object individually
        global_log.log(
            scalyr_logging.DEBUG_LEVEL_2,
            "cache miss for %s %s/%s" % (kind, namespace, name),
        )

        result = None
        try:
            result = self._update_object(
                k8s, kind, namespace, name, current_time, query_options=query_options
            )
        except K8sApiException:
            if ignore_k8s_api_exception:
                pass
            else:
                raise

        return result


class _K8sProcessor(object):
    """
        An abstract interface used by _K8sCache for querying a specific type of
        object from the k8s api, and generating python objects from the queried result JSON.
    """

    def _get_managing_controller(self, items):
        """
            Processes a list of items, searching to see if one of them
            is a 'managing controller', which is determined by the 'controller' field

            @param items: an array containing 'ownerReferences' metadata for an object
                            returned from the k8s api

            @return: A dict containing the managing controller of type `kind` or None if no such controller exists
        """
        for i in items:
            controller = i.get("controller", False)
            if controller:
                return i

        return None

    def process_object(self, k8s, obj, query_options=None):
        """
        Creates a python object based of a dict
        @param k8s: a KubernetesApi object
        @param obj: A JSON dict returned as a response to querying
                    the k8s API for a specific object type.
        @return a python object relevant to the
        """
        raise NotImplementedError("process_object not implemented for _K8sProcessor")


class PodProcessor(_K8sProcessor):
    def __init__(self, controllers):
        super(PodProcessor, self).__init__()
        self._controllers = controllers

    def _get_controller_from_owners(self, k8s, owners, namespace, query_options=None):
        """
            Processes a list of owner references returned from a Pod's metadata to see
            if it is eventually owned by a Controller, and if so, returns the Controller object

            @return Controller - a Controller object
        """
        controller = None

        # check if we are owned by another controller
        owner = self._get_managing_controller(owners)
        if owner is None:
            return None

        # make sure owner has a name field and a kind field
        name = owner.get("name", None)
        if name is None:
            return None

        kind = owner.get("kind", None)
        if kind is None:
            return None

        # walk the parent until we get to the root controller
        # Note: Parent controllers will always be in the same namespace as the child
        current_time = time.time()
        controller = self._controllers.lookup(
            k8s,
            current_time,
            namespace,
            name,
            kind=kind,
            query_options=query_options,
            ignore_k8s_api_exception=True,
        )

        while controller:
            if controller.parent_name is None:
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "controller %s has no parent name" % controller.name,
                )
                break

            if controller.parent_kind is None:
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "controller %s has no parent kind" % controller.name,
                )
                break

            # get the parent controller
            parent_controller = self._controllers.lookup(
                k8s,
                current_time,
                namespace,
                controller.parent_name,
                kind=controller.parent_kind,
                query_options=query_options,
            )
            # if the parent controller doesn't exist, assume the current controller
            # is the root controller
            if parent_controller is None:
                break

            # walk up the chain
            controller = parent_controller

        return controller

    def process_object(self, k8s, obj, query_options=None):
        """ Generate a PodInfo object from a JSON object
        @param k8s: a KubernetesApi object
        @param pod: The JSON object returned as a response to querying
            a specific pod from the k8s API

        @return A PodInfo object
        """

        result = {}

        metadata = obj.get("metadata", {})
        spec = obj.get("spec", {})
        labels = metadata.get("labels", {})
        annotations = metadata.get("annotations", {})
        owners = metadata.get("ownerReferences", [])

        pod_name = metadata.get("name", "")
        namespace = metadata.get("namespace", "")

        controller = self._get_controller_from_owners(
            k8s, owners, namespace, query_options=query_options
        )

        container_names = []
        for container in spec.get("containers", []):
            container_names.append(container.get("name", "invalid-container-name"))

        try:
            annotations = annotation_config.process_annotations(annotations)
        except BadAnnotationConfig as e:
            global_log.warning(
                "Bad Annotation config for %s/%s.  All annotations ignored. %s"
                % (namespace, pod_name, six.text_type(e)),
                limit_once_per_x_secs=300,
                limit_key="bad-annotation-config-%s"
                % metadata.get("uid", "invalid-uid"),
            )
            annotations = JsonObject()

        global_log.log(
            scalyr_logging.DEBUG_LEVEL_2,
            "Annotations: %s" % (six.text_type(annotations)),
        )

        # create the PodInfo
        result = PodInfo(
            name=pod_name,
            namespace=namespace,
            uid=metadata.get("uid", ""),
            node_name=spec.get("nodeName", ""),
            labels=labels,
            container_names=container_names,
            annotations=annotations,
            controller=controller,
        )
        return result


class ControllerProcessor(_K8sProcessor):
    def process_object(self, k8s, obj, query_options=None):
        """ Generate a Controller object from a JSON object
        @param k8s: a KubernetesApi object
        @param obj: The JSON object returned as a response to querying
            a specific controller from the k8s API

        @return A Controller object
        """

        metadata = obj.get("metadata", {})
        kind = obj.get("kind", "")
        owners = metadata.get("ownerReferences", [])
        namespace = metadata.get("namespace", "")
        name = metadata.get("name", "")
        labels = metadata.get("labels", {})
        parent_name = None
        parent_kind = None

        parent = self._get_managing_controller(owners)
        if parent is not None:
            parent_name = parent.get("name", None)
            parent_kind = parent.get("kind", None)

        return Controller(name, namespace, kind, parent_name, parent_kind, labels)


class _CacheConfig(object):
    """
    Internal configuration options for the Kubernetes cache
    """

    def __init__(
        self,
        api_url="https://kubernetes.default",
        verify_api_queries=True,
        cache_expiry_secs=30,
        cache_purge_secs=300,
        cache_expiry_fuzz_secs=0,
        cache_start_fuzz_secs=0,
        query_timeout=20,
        global_config=None,
    ):
        """
        @param api_url: the url for querying the k8s api
        @param verify_api_queries: whether to verify queries to the k8s api
        @param cache_expiry_secs: the number of secs to wait before updating the cache
        @param cache_expiry_fuzz_secs: if greater than zero, the number of seconds to fuzz the expiration time to avoid query stampede
        @param cache_start_fuzz_secs: if greater than zero, the number of seconds to fuzz the start time to avoid query stampede
        @param cache_purge_secs: the number of seconds to wait before purging old controllers from the cache
        @param query_timeout: The number of seconds to wait before a query to the API server times out
        @param global_config: Global configuration object

        @type api_url: str
        @type verify_api_queries: bool
        @type cache_expiry_secs: int or float
        @type cache_expiry_fuzz_secs: int or float
        @type cache_start_fuzz_secs: int or float
        @type cache_purge_secs: int or float
        @type query_timeout: int
        @type global_config: Configurtion
        """

        # NOTE: current implementations of __eq__ expects that fields set in contructor are only true state
        # fields that affect equality. If this is ever changed, be sure to modify __eq__ accordingly
        self.api_url = api_url
        self.verify_api_queries = verify_api_queries
        self.cache_expiry_secs = cache_expiry_secs
        self.cache_expiry_fuzz_secs = cache_expiry_fuzz_secs
        self.cache_start_fuzz_secs = cache_start_fuzz_secs
        self.cache_purge_secs = cache_purge_secs
        self.query_timeout = query_timeout
        self.global_config = global_config

    def __eq__(self, other):
        """Equivalence method for _CacheConfig objects so == testing works """
        for key, val in self.__dict__.items():
            if val != getattr(other, key):
                return False
        return True

    def __ne__(self, other):
        """Non-Equivalence method for _CacheConfig objects because Python 2 doesn't
        automatically generate != if == is defined
        """
        # return result based on negation of `==` rather than negation of `__eq__`
        return not (self == other)

    def __repr__(self):
        s = ""
        for key, val in self.__dict__.items():
            s += "\n\t%s: %s" % (key, val)
        return s + "\n"

    def need_new_k8s_object(self, new_config):
        """
        Determines if a new KubernetesApi object needs to created for the cache based on the new config
        @param new_config: The new config options
        @type new_config: _CacheConfig
        @return: True if a new KubernetesApi object should be created based on the differences between the
                 current and the new config.  False otherwise.
        """
        relevant_fields = ["api_url", "verify_api_queries", "query_timeout"]
        relevant_global_config_fields = [
            "agent_log_path",
            "k8s_log_api_responses",
            "k8s_log_api_exclude_200s",
            "k8s_log_api_min_response_len",
            "k8s_log_api_min_latency",
            "k8s_log_api_ratelimit_interval",
        ]

        # Verify the relevant CacheConfig fields are equal
        for field in relevant_fields:
            if getattr(self, field) != getattr(new_config, field):
                return True

        # If one of the sub global-config is null and the other isn't, return True
        if bool(self.global_config) ^ bool(new_config.global_config):
            return True

        # If both sub global-configs are present, verify their relevant fields are equal
        if self.global_config and new_config:
            for field in relevant_global_config_fields:
                if getattr(self.global_config, field) != getattr(
                    new_config.global_config, field
                ):
                    return True
        return False


class _CacheConfigState(object):
    """
    Class holding cache config related state
    """

    class LocalState(object):
        """
        Helper class containing copies of state information so that it can be used on
        separate threads without worry of being changed by another thread.
        """

        def __init__(self, state):
            """
            Create a copy of the relevant parts of `state`
            The caller should lock `state` before calling this method
            @param state: the cache state
            @type state: _CacheConfigState
            """
            self.k8s = state.k8s
            self.cache_expiry_secs = state.cache_config.cache_expiry_secs
            self.cache_purge_secs = state.cache_config.cache_purge_secs
            self.cache_expiry_fuzz_secs = state.cache_config.cache_expiry_fuzz_secs
            self.cache_start_fuzz_secs = state.cache_config.cache_start_fuzz_secs

    def __init__(self, cache_config, global_config):
        """Set default values"""
        self._lock = threading.Lock()
        self.k8s = None
        self.cache_config = _CacheConfig(api_url="", global_config=global_config)
        self._pending_config = None
        self.configure(cache_config)

    def copy_state(self):
        """
        Get a copy of the relevant cache state in a thread-safe manner
        @return: a copy of various state information, useful for the main processing thread
        @rtype: LocalState
        """
        self._lock.acquire()
        try:
            return self.LocalState(self)
        finally:
            self._lock.release()

    def configure(self, new_cache_config):
        """
        Configures the state based on any changes in the configuration.

        Whenever a new configuration is detected, a new instance of KubernetesApi will be created.
        The KubernetesApi however, will reference a named BlockingRateLimiter since we need to share
        BlockingRateLimiters across monitors.

        @param new_cache_config: the new configuration
        @param global_config: global configuration object
        @type new_cache_config: _CacheConfig
        @type global_config: Configuration object
        """
        # get old state values
        old_state = self.copy_state()
        need_new_k8s = False
        self._lock.acquire()
        try:
            if self.cache_config == new_cache_config:
                return

            self._pending_config = new_cache_config
            need_new_k8s = (
                old_state.k8s is None
                or self.cache_config.need_new_k8s_object(new_cache_config)
            )
        finally:
            self._lock.release()

        # create a new k8s api object if we need one
        k8s = old_state.k8s
        if need_new_k8s:
            k8s = KubernetesApi.create_instance(
                new_cache_config.global_config,
                k8s_api_url=new_cache_config.api_url,
                query_timeout=new_cache_config.query_timeout,
                verify_api_queries=new_cache_config.verify_api_queries,
            )

        # update with new values
        self._lock.acquire()
        try:
            # if new_config is not self._pending_config then it means a newer config
            # came through on another thread before we finished this call and therefore
            # we should avoid updating because we only want the most recent update to succeed.
            # use 'is' rather than == because we want to see if they are the same object
            # not if the objects are semantically identical
            if new_cache_config is self._pending_config:
                self.k8s = k8s
                self.k8s.query_timeout = new_cache_config.query_timeout
                self.cache_config = new_cache_config
                self._pending_config = None

                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_1,
                    "Got new config %s",
                    six.text_type(self.cache_config),
                )

        finally:
            self._lock.release()


class AgentPodNotReadyException(Exception):
    """Raised when the agent pod is not fully ready according to the K8s API server."""

    pass


class KubernetesCache(object):
    def __init__(
        self,
        api_url="https://kubernetes.default",
        verify_api_queries=True,
        cache_expiry_secs=30,
        cache_expiry_fuzz_secs=0,
        cache_start_fuzz_secs=0,
        cache_purge_secs=300,
        start_caching=True,
        global_config=None,
    ):

        self._lock = threading.Lock()

        new_cache_config = _CacheConfig(
            api_url=api_url,
            verify_api_queries=verify_api_queries,
            cache_expiry_secs=cache_expiry_secs,
            cache_expiry_fuzz_secs=cache_expiry_fuzz_secs,
            cache_start_fuzz_secs=cache_start_fuzz_secs,
            cache_purge_secs=cache_purge_secs,
            global_config=global_config,
        )

        # set the initial state
        self._state = _CacheConfigState(new_cache_config, global_config)

        # create the controller cache
        self._controller_processor = ControllerProcessor()
        self._controllers = _K8sCache(self._controller_processor, "<controller>")

        # create the pod cache
        self._pod_processor = PodProcessor(self._controllers)
        self._pods_cache = _K8sCache(self._pod_processor, "Pod")

        self._cluster_name = None
        self._api_server_version = None
        # The last time (in seconds since epoch) we updated the K8s version number via a query
        self._last_api_server_version_update = 0

        self._container_runtime = None
        self._initialized = False
        self._last_initialization_error = "Initialization not started"

        self._thread = None

        self._rate_limiter = None

        if start_caching:
            self.start()

    def stop(self):
        """Stops the cache, specifically stopping the background thread that refreshes the cache"""
        self._thread.stop()

    def start(self):
        """
            Starts the background thread that reads from the k8s cache
        """
        if self._thread is None:
            self._thread = StoppableThread(target=self.update_cache, name="K8S Cache")
            self._thread.start()

    def local_state(self):
        """
        Returns a local copy of the current state
        """
        return self._state.copy_state()

    def update_config(self, new_cache_config):
        """
        Updates the cache config
        """
        self._state.configure(new_cache_config)

        self._lock.acquire()
        try:
            if self._thread is None:
                self.start()
        finally:
            self._lock.release()

    def is_initialized(self):
        """Returns whether or not the k8s cache has been initialized with the full pod list"""
        result = False
        self._lock.acquire()
        try:
            result = self._initialized
        finally:
            self._lock.release()

        return result

    def last_initialization_error(self):
        """Returns the last error experienced while initializing the cache.
        Returns None if it is initialized."""
        self._lock.acquire()
        try:
            if self._initialized:
                return None
            else:
                return self._last_initialization_error
        finally:
            self._lock.release()

    def _update_initialization_error(self, component, message):
        """Updates the last initialization error message experienced.

        :param component: The component of the cache being initialized when the error occurred
        :param message: The error message

        :type component: six.text_type
        :type message: six.text_type
        """
        self._lock.acquire()
        try:
            self._last_initialization_error = (
                'Unable to initialize %s in K8s cache due to "%s"'
                % (component, message)
            )
        finally:
            self._lock.release()

    def _update_cluster_name(self, k8s):
        """Updates the cluster name"""
        cluster_name = k8s.get_cluster_name()
        self._lock.acquire()
        try:
            self._cluster_name = cluster_name
        finally:
            self._lock.release()

    def _update_api_server_version_if_necessary(self, k8s, current_time=None):
        """Update the API server version if it has not been successfully update in the last hour.
        The version number is determined by querying the K8s API server."""

        if current_time is None:
            current_time = time.time()

        # Check if we have the version set and what time we set it.
        self._lock.acquire()
        try:
            is_version_set = self._api_server_version is not None
            last_check_time = self._last_api_server_version_update
        finally:
            self._lock.release()

        # We only update if we haven't updated it in the last hour.
        if not is_version_set or current_time - last_check_time > 3600:
            # Query the API server to get version.
            gitver = k8s.get_api_server_version()

            self._lock.acquire()
            try:
                self._api_server_version = gitver
                self._last_api_server_version_update = current_time
            finally:
                self._lock.release()

    def _get_runtime(self, k8s):
        pod_name = k8s.get_pod_name()
        pod = k8s.query_pod(k8s.namespace, pod_name)
        if pod is None:
            global_log.warning(
                "Coud not determine K8s CRI because could not find agent pod: %s"
                % pod_name,
                limit_once_per_x_secs=300,
                limit_key="k8s_cri_no_pod",
            )
            return None

        status = pod.get("status", {})
        containers = status.get("containerStatuses", [])
        for container in containers:
            name = container.get("name")
            if name and name == "scalyr-agent":
                # If the agent container is not ready (according the API server) we cannot get the containerID
                # and therefore cannot determine the container runtime.  We need to wait a little bit for the
                # API server to catch up.  We raise this exception which triggers the right things.
                if not container.get("ready", False):
                    raise AgentPodNotReadyException()

                containerId = container.get("containerID", "")
                m = _CID_RE.match(containerId)
                if m:
                    return m.group(1)
                else:
                    global_log.warning(
                        "Coud not determine K8s CRI because agent container id did not match: %s"
                        % containerId,
                        limit_once_per_x_secs=300,
                        limit_key="k8s_cri_unmatched_container_id",
                    )

                    return None

        global_log.warning(
            "Coud not determine K8s CRI because could not find agent container in pod.",
            limit_once_per_x_secs=300,
            limit_key="k8s_cri_no_agent_container",
        )
        return None

    def update_cache(self, run_state):
        """
            Main thread for updating the k8s cache
        """

        start_time = time.time()
        retry_delay_secs = None
        while run_state.is_running() and not self.is_initialized():
            # get cache state values that will be consistent for the duration of the loop iteration
            local_state = self._state.copy_state()

            # Delay the start of this cache if we have fuzzing turned on.  This will reduce the stampede of
            # agents all querying the API master at the same time on large clusters (when the agents are started
            # at the same time.)
            if local_state.cache_start_fuzz_secs > 0:
                run_state.sleep_but_awaken_if_stopped(
                    random.uniform(0, local_state.cache_start_fuzz_secs)
                )
            # Delay before reattempting to initialize the cache if we had an error last time.
            if retry_delay_secs is not None:
                run_state.sleep_but_awaken_if_stopped(retry_delay_secs)

            if not run_state.is_running() or self.is_initialized():
                continue

            # Records which component is being initialized.  Used in error messages below.
            component = "cluster name"
            try:
                self._update_cluster_name(local_state.k8s)
                component = "api version"
                self._update_api_server_version_if_necessary(local_state.k8s)
                component = "runtime"
                runtime = self._get_runtime(local_state.k8s)

                self._lock.acquire()
                try:
                    self._container_runtime = runtime
                    self._initialized = True
                    self._last_initialization_error = None
                finally:
                    self._lock.release()
            except K8sApiException as e:
                global_log.warn(
                    "K8s API exception while updating %s in K8s cache (will retry) - %s"
                    % (component, six.text_type(e)),
                    limit_once_per_x_secs=300,
                    limit_key="k8s_api_init_cache",
                )
                self._update_initialization_error(
                    component, "K8s API error %s" % six.text_type(e)
                )
                # Delay a fixed amount.  TODO: Maybe do exponential backoff here?
                retry_delay_secs = 0.5
            except AgentPodNotReadyException:
                global_log.info(
                    "Agent container not ready while initializing cache (will retry)",
                    limit_once_per_x_secs=60,
                    limit_key="k8s_agent_pod_not_ready",
                )
                self._update_initialization_error(
                    component, "Agent container not ready"
                )
                retry_delay_secs = 1.0
            except Exception as e:
                global_log.warn(
                    "Exception occurred when updating %s in K8s cache (will retry) - %s\n%s"
                    % (component, six.text_type(e), traceback.format_exc()),
                    limit_once_per_x_secs=60,
                    limit_key="k8s_init_generic_error",
                )
                self._update_initialization_error(
                    component, "Unhandled error %s" % six.text_type(e)
                )
                # Unknown error.  TODO: Maybe do exponential backoff here?
                retry_delay_secs = 0.5

        current_time = time.time()
        elapsed = current_time - start_time

        global_log.info("Kubernetes cache initialized in %.2f seconds" % elapsed)

        local_state = self._state.copy_state()

        # go back to sleep if we haven't taken longer than the expiry time
        if elapsed < local_state.cache_expiry_secs:
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_1,
                "sleeping for %.2f seconds" % (local_state.cache_expiry_secs - elapsed),
            )
            run_state.sleep_but_awaken_if_stopped(
                local_state.cache_expiry_secs - elapsed
            )

        # start the main update loop
        last_purge = time.time()
        while run_state.is_running():
            # get cache state values that will be consistent for the duration of the loop iteration
            local_state = self._state.copy_state()

            try:
                current_time = time.time()

                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_1, "Marking unused pods as expired"
                )
                self._pods_cache.mark_as_expired(current_time)

                self._update_cluster_name(local_state.k8s)
                self._update_api_server_version_if_necessary(
                    local_state.k8s, current_time=current_time
                )

                if last_purge + local_state.cache_purge_secs < current_time:
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_1,
                        "Purging unused controllers last_purge=%s cache_purge_secs=%s current_time=%s"
                        % (last_purge, local_state.cache_purge_secs, current_time),
                    )
                    self._controllers.purge_unused(last_purge)
                    # purge any pods that haven't been queried within the cache_purge_secs
                    global_log.log(scalyr_logging.DEBUG_LEVEL_1, "Purging stale pods")
                    self._pods_cache.purge_unused(last_purge)
                    last_purge = current_time

            except K8sApiException as e:
                global_log.warn(
                    "Exception occurred when updating k8s cache - %s"
                    % (six.text_type(e)),
                    limit_once_per_x_secs=300,
                    limit_key="k8s_api_update_cache",
                )
            except Exception as e:
                global_log.warn(
                    "Exception occurred when updating k8s cache - %s\n%s"
                    % (six.text_type(e), traceback.format_exc())
                )

            # Fuzz how much time we spend until the next cycle.  This should spread out when the agents query the
            # API master over time in clusters with a larger number of agents.
            if local_state.cache_expiry_fuzz_secs > 0:
                fuzz_factor = max(
                    random.uniform(0, local_state.cache_expiry_fuzz_secs), 0
                )
            else:
                fuzz_factor = 0
            run_state.sleep_but_awaken_if_stopped(
                local_state.cache_expiry_secs - fuzz_factor
            )

    def pod(
        self,
        namespace,
        name,
        current_time=None,
        allow_expired=True,
        query_options=None,
        ignore_k8s_api_exception=False,
    ):
        """Returns pod info for the pod specified by namespace and name or None if no pad matches.

        Warning: Failure to pass current_time leads to incorrect recording of last access times, which will
        lead to these objects being refreshed prematurely (potential source of bugs)

        Querying the pod information is thread-safe, but the returned object should
        not be written to.

        @param allow_expired: If True, an object is considered present in cache even if it is expired.
        @type allow_expired: bool
        """
        local_state = self._state.copy_state()

        if local_state.k8s is None:
            return

        return self._pods_cache.lookup(
            local_state.k8s,
            current_time,
            namespace,
            name,
            kind="Pod",
            allow_expired=allow_expired,
            query_options=query_options,
            ignore_k8s_api_exception=ignore_k8s_api_exception,
        )

    def is_pod_cached(self, namespace, name, allow_expired):
        """Returns true if the specified pod is in the cache and isn't expired.

        Warning: Failure to pass current_time leads to incorrect recording of last access times, which will
        lead to these objects being refreshed prematurely (potential source of bugs)

        @param namespace: The pod's namespace
        @param name: The pod's name
        @param allow_expired: If True, an object is considered present in cache even if it is expired.

        @type namespace: str
        @type name: str
        @type allow_expired: bool

        @return: True if the pod is cached.
        @rtype: bool
        """
        return self._pods_cache.is_cached(namespace, name, allow_expired)

    def controller(self, namespace, name, kind, current_time=None, query_options=None):
        """Returns controller info for the controller specified by namespace and name
        or None if no controller matches.

        Warning: Failure to pass current_time leads to incorrect recording of last access times, which will
        lead to these objects being refreshed prematurely (potential source of bugs)

        Querying the controller information is thread-safe, but the returned object should
        not be written to.
        """
        local_state = self._state.copy_state()

        if local_state.k8s is None:
            return

        return self._controllers.lookup(
            local_state.k8s,
            current_time,
            namespace,
            name,
            kind=kind,
            query_options=query_options,
            ignore_k8s_api_exception=True,
        )

    def pods_shallow_copy(self):
        """Retuns a shallow copy of the pod objects"""
        return self._pods_cache.shallow_copy()

    def get_cluster_name(self):
        """Returns the cluster name"""
        result = None
        self._lock.acquire()
        try:
            result = self._cluster_name
        finally:
            self._lock.release()

        return result

    def get_container_runtime(self):
        """Returns the k8s container runtime currently being used"""
        result = None
        self._lock.acquire()
        try:
            result = self._container_runtime
        finally:
            self._lock.release()

        return result

    def get_api_server_version(self):
        """Returns API server version"""
        result = None
        self._lock.acquire()
        try:
            result = self._api_server_version
        finally:
            self._lock.release()
        return result


class KubernetesApi(object):
    """Simple wrapper class for querying the k8s api
    """

    @staticmethod
    def create_instance(
        global_config,
        k8s_api_url=None,
        query_timeout=None,
        verify_api_queries=None,
        rate_limiter_key="K8S_CACHE_MAIN_RATELIMITER",
    ):
        """
        @param global_config: Global configuration
        @param k8s_api_url: overrides global config api url
        @param query_timeout: overrides global config query timeout
        @param verify_api_queries: overrides global config verify_api_queries
        @param rate_limiter_key: Allow overriding of rate limiter key, otherwise, uses the "main" k8s cache ratelimiter
        """
        if k8s_api_url is None:
            k8s_api_url = global_config.k8s_api_url
        if query_timeout is None:
            query_timeout = global_config.k8s_cache_query_timeout_secs
        if verify_api_queries is None:
            verify_api_queries = global_config.k8s_verify_api_queries

        kwargs = {
            "k8s_api_url": k8s_api_url,
            "query_timeout": query_timeout,
        }

        if not verify_api_queries:
            kwargs["ca_file"] = None
        elif global_config:
            kwargs["ca_file"] = global_config.k8s_service_account_cert

        if global_config:
            kwargs.update(
                {
                    "log_api_responses": global_config.k8s_log_api_responses,
                    "log_api_exclude_200s": global_config.k8s_log_api_exclude_200s,
                    "log_api_min_response_len": global_config.k8s_log_api_min_response_len,
                    "log_api_min_latency": global_config.k8s_log_api_min_latency,
                    "log_api_ratelimit_interval": global_config.k8s_log_api_ratelimit_interval,
                    "agent_log_path": global_config.agent_log_path,
                    "query_options_max_retries": global_config.k8s_controlled_warmer_max_query_retries,
                    "rate_limiter": BlockingRateLimiter.get_instance(
                        rate_limiter_key, global_config, logger=global_log
                    ),
                    "token_file": global_config.k8s_service_account_token,
                    "namespace_file": global_config.k8s_service_account_namespace,
                }
            )
        return KubernetesApi(**kwargs)

    def __init__(
        self,
        ca_file="/run/secrets/kubernetes.io/serviceaccount/ca.crt",
        k8s_api_url="https://kubernetes.default",
        query_timeout=20,
        log_api_responses=False,
        log_api_exclude_200s=False,
        log_api_min_response_len=False,
        log_api_min_latency=0.0,
        log_api_ratelimit_interval=300,
        agent_log_path=None,
        query_options_max_retries=3,
        rate_limiter=None,
        token_file="/var/run/secrets/kubernetes.io/serviceaccount/token",
        namespace_file="/var/run/secrets/kubernetes.io/serviceaccount/namespace",
    ):
        """Init the kubernetes object"""
        self.log_api_responses = log_api_responses
        self.log_api_exclude_200s = log_api_exclude_200s
        self.log_api_min_response_len = log_api_min_response_len
        self.log_api_min_latency = log_api_min_latency
        self.log_api_ratelimit_interval = log_api_ratelimit_interval

        self.agent_log_path = agent_log_path

        self._http_host = k8s_api_url

        global_log.log(
            scalyr_logging.DEBUG_LEVEL_1, "Kubernetes API host: %s", self._http_host
        )

        self.query_timeout = query_timeout

        self._session = None

        self._ca_file = ca_file

        # We create a few headers ahead of time so that we don't have to recreate them each time we need them.
        self._standard_headers = {
            "Connection": "Keep-Alive",
            "Accept": "application/json",
        }

        # The k8s API requires us to pass in an authentication token
        # which we can obtain from a token file in a 'well known' location
        self.token = ""

        try:
            # using with is ok here, because we need to be running
            # a recent version of python for various 3rd party libs
            f = open(token_file, "r")
            try:
                self.token = f.read()
            finally:
                f.close()
        except IOError:
            pass

        # get the namespace this pod is running on
        self.namespace = "default"
        try:
            # using with is ok here, because we need to be running
            # a recent version of python for various 3rd party libs
            f = open(namespace_file, "r")
            try:
                self.namespace = f.read()
            finally:
                f.close()
        except IOError:
            pass

        self._standard_headers["Authorization"] = "Bearer %s" % (self.token)

        # A rate limiter should normally be passed unless no rate limiting is desired.
        self._query_options_max_retries = query_options_max_retries
        self._rate_limiter = rate_limiter

    @property
    def default_query_options(self):
        if not self._rate_limiter:
            return None
        return ApiQueryOptions(
            max_retries=self._query_options_max_retries, rate_limiter=self._rate_limiter
        )

    def _verify_connection(self):
        """ Return whether or not to use SSL verification
        """
        if self._ca_file:
            return self._ca_file
        return False

    def _ensure_session(self):
        """Create the session if it doesn't exist, otherwise do nothing
        """
        if not self._session:
            self._session = requests.Session()
            self._session.headers.update(self._standard_headers)

    def get_pod_name(self):
        """ Gets the pod name of the pod running the scalyr-agent """
        # 2->TODO in python2 os.environ returns 'str' type. Convert it to unicode.
        return os_environ_unicode.get("SCALYR_K8S_POD_NAME") or os_environ_unicode.get(
            "HOSTNAME"
        )

    def get_node_name(self, pod_name):
        """ Gets the node name of the node running the agent """
        # 2->TODO in python2 os.environ returns 'str' type. Convert it to unicode.
        node = os_environ_unicode.get("SCALYR_K8S_NODE_NAME")
        if not node:
            pod = self.query_pod(self.namespace, pod_name)
            spec = pod.get("spec", {})
            node = spec.get("nodeName")
        return node

    def get_api_server_version(self):
        """Get the API server version (specifically the server gitVersion)

        @return: The gitVersion extracted from /version JSON
        @rtype: str
        """
        version_map = self.query_api_with_retries(
            "/version",
            retry_error_context="get_api_server_version",
            retry_error_limit_key="get_api_server_version",
        )
        return version_map.get("gitVersion")

    def get_cluster_name(self):
        """ Returns the name of the cluster running this agent.

        There is no way to get this from the k8s API so we check the following:

        If the environment variable SCALYR_K8S_CLUSTER_NAME is set, then use that.

        Otherwise query the api for the pod running the agent container and check to see
        if it has an annotation: agent.config.scalyr.com/cluster_name, and if so, use that.

        Otherwise return None
        """

        # 2->TODO in python2 os.environ returns 'str' type. Convert it to unicode.
        cluster = os_environ_unicode.get("SCALYR_K8S_CLUSTER_NAME", "")
        if cluster:
            return cluster

        pod_name = self.get_pod_name()
        pod = self.query_pod(self.namespace, pod_name)

        if pod is None:
            return None

        metadata = pod.get("metadata", {})
        annotations = metadata.get("annotations", {})

        if "agent.config.scalyr.com/cluster_name" in annotations:
            return annotations["agent.config.scalyr.com/cluster_name"]

        return None

    def query_api_with_retries(
        self,
        query,
        query_options="not-set",
        retry_error_context=None,
        retry_error_limit_key=None,
    ):
        """Invoke query api through rate limiter with retries

        @param query: Query string
        @param query_options: ApiQueryOptions containing retries and rate_limiter.
            Explicit None signifies no rate limiting.
            Default 'not-set' signifies "use k8s-instance specific rate limiter and query options
        @param retry_error_context: context object whose string representation is logged upon failure (if None)
        @param retry_error_limit_key: key for limiting retry logging

        @type query: str
        @type query_options: ApiQueryOptions
        @type retry_error_context: object
        @type retry_error_limit_key: str

        @return: json-decoded response of the query api call
        @rtype: dict or a scalyr_agent.json_lib.objects.JsonObject
        """
        if not query_options:
            return self.query_api(query)

        if query_options == "not-set":
            query_options = self.default_query_options

        retries_left = query_options.max_retries
        rate_limiter = query_options.rate_limiter
        while True:
            t = time.time()
            token = rate_limiter.acquire_token()
            rate_limit_outcome = False
            try:
                result = self.query_api(
                    query,
                    return_temp_errors=query_options.return_temp_errors,
                    rate_limited=True,
                )
                rate_limit_outcome = True
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_3,
                    "Rate limited k8s api query took %s seconds" % (time.time() - t),
                )
                return result
            except K8sApiNotFoundException:
                # catch and re-raise this before any other temporary errors, because we need to
                # handle this one separately.  Rather than immediately retrying, we won't do anything,
                # rather, if the agent wants to query this endpoint again later then it will.
                # This is useful for when a pod hasn't fully started up yet and querying its endpoint
                # will return a 404.  Then if you query again a few seconds later everything works.
                rate_limit_outcome = True
                raise
            except K8sApiTemporaryError as e:
                rate_limit_outcome = False
                if retries_left <= 0:
                    raise e
                retries_left -= 1
                if retry_error_context:
                    global_log.warn(
                        "k8s API - retrying temporary error: %s" % retry_error_context,
                        limit_once_per_x_secs=300,
                        limit_key="k8s_api_retry-%s" % retry_error_limit_key,
                    )
            finally:
                # Any uncaught exceptions will result in an outcome of False
                rate_limiter.release_token(token, rate_limit_outcome)

    def __open_api_response_log(self, path, rate_limited):
        """Opens a file for logging the api response

        The file will be located in agent_log_dir/kapi/(limited/not_limited) depending on whether the
        api call is rate limited or not.

        @param path: The URL path to be queried (also embedded in the filename)
        @param rate_limited: Whether the response is rate limited or not

        @type path: str
        @type rate_limited: bool

        @returns File handle to the api response log file or None upon failure.
        @rtype: file handle
        """
        # try to open the logged_response_file
        try:
            kapi = os.path.join(self.agent_log_path, "kapi")
            if not os.path.exists(kapi):
                os.mkdir(kapi, 0o755)
            if rate_limited:
                kapi = os.path.join(kapi, "limited")
            else:
                kapi = os.path.join(kapi, "not_limited")
            if not os.path.exists(kapi):
                os.mkdir(kapi, 0o755)
            fname = "%s_%.20f_%s_%s" % (
                strftime("%Y%m%d-%H-%M-%S", gmtime()),
                time.time(),
                random.randint(1, 100),
                path.replace("/", "--"),
            )

            # if logging responses to disk, always prepend the stack trace for easier debugging
            return open(os.path.join(kapi, fname), "w")
        except IOError:
            pass

    def __check_for_fake_response(self, logged_response_file):
        """Helper method that checks for a well known file on disk and simulates timeouts from API master

        If successfully logging responses, we can also check for a local "simfile" to simulate API master timeout.
        The simfile is a textfile that contains the HTTP error code we want to simulate.

        This method should only be called during development.

        @param logged_response_file: Logged-response logfile
        @type logged_response_file: file handle

        @raises K8sApiTemporaryError: if the simfile contains one of the following http error codes that we consider
            as a temporary error.
        """
        fake_response_file = os.path.join(self.agent_log_path, "simfile")
        if os.path.isfile(fake_response_file):
            fake_response_code = None
            try:
                fake_f = open(fake_response_file, "r")
                try:
                    fake_response_code = fake_f.read().strip()
                finally:
                    fake_f.close()
            except Exception:
                if logged_response_file:
                    logged_response_file.write(
                        "Error encountered while attempting to fake a response code:\n%s\n\n"
                        % traceback.format_exc()
                    )
            if fake_response_code in ["404", "503", "429"]:
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_3,
                    "Faking api master temporary error (%s) for url: %s",
                    limit_once_per_x_secs=300,
                    limit_key="k8s_api_query_fake_temporary_error",
                )
                raise K8sApiTemporaryError("Fake %s" % fake_response_code)

    def query_api(self, path, pretty=0, return_temp_errors=False, rate_limited=False):
        """ Queries the k8s API at 'path', and converts OK responses to JSON objects
        """
        self._ensure_session()
        pretty = "pretty=%d" % pretty
        if "?" in path:
            pretty = "&%s" % pretty
        else:
            pretty = "?%s" % pretty

        url = self._http_host + path + pretty

        response = None

        # Various state used logging of responses
        log_responses = self.log_api_responses
        logged_response = []
        response_status_code = -1
        response_len = 0

        try:
            # Optionally prepend stack trace into logged response
            if log_responses:
                limited_txt = ""
                if rate_limited:
                    limited_txt = " (rate limited)"
                logged_response.append("k8s.query_api%s: %s" % (limited_txt, path))
                stack_trace = "".join(traceback.format_stack())
                logged_response.append("\\n%s" % stack_trace.replace("\n", "\\n"))

            # Make actual API call
            latency = float("inf")
            examine_latency = log_responses and self.log_api_min_latency > 0
            if examine_latency:
                t1 = time.time()
            try:
                response = self._session.get(
                    url, verify=self._verify_connection(), timeout=self.query_timeout
                )
                response.encoding = "utf-8"
            except Exception as e:
                if return_temp_errors:
                    raise K8sApiTemporaryError(
                        "Temporary error seen while accessing api: %s"
                        % six.text_type(e)
                    )
                else:
                    raise
            finally:
                # conditionally record latency regardless of exception
                if examine_latency:
                    latency = time.time() - t1

            # No exception case: record response status code and length
            response_status_code = response.status_code
            if response.text:
                response_len = len(response.text)

            if response.status_code != 200:
                if response.status_code == 401 or response.status_code == 403:
                    raise K8sApiAuthorizationException(
                        path, status_code=response.status_code
                    )
                elif response.status_code == 404:
                    raise K8sApiNotFoundException(
                        path, status_code=response.status_code
                    )

                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_3,
                    "Invalid response from K8S API.\n\turl: %s\n\tstatus: %d\n\tresponse length: %d"
                    % (url, response.status_code, len(response.text)),
                    limit_once_per_x_secs=300,
                    limit_key="k8s_api_query",
                )
                if return_temp_errors:
                    raise K8sApiTemporaryError(
                        "Invalid response from Kubernetes API when querying '%s': %s"
                        % (path, six.text_type(response)),
                        status_code=response.status_code,
                    )
                else:
                    raise K8sApiException(
                        "Invalid response from Kubernetes API when querying '%s': %s"
                        % (path, six.text_type(response)),
                        status_code=response.status_code,
                    )

            # Optionally prepend stack trace into logged response
            # newlines should become literal '\n' so that the entire response is a single line
            if log_responses and response.text:
                logged_response.append(response.text.replace("\n", "\\n"))

            return util.json_decode(response.text)

        finally:
            # Only debug-log the response if all criteria (status code, latency, response len) are satisfied
            if log_responses:
                # Always log non-200 responses (using integer division to inspect first digit.
                # For 200 responses, only log if log_api_exclude_200s is False.
                if (response_status_code // 100) != 2 or not self.log_api_exclude_200s:
                    if (
                        response_len >= self.log_api_min_response_len
                        and latency >= self.log_api_min_latency
                    ):
                        # Log the url, stacktrace and response text as a single line of text
                        global_log.log(
                            scalyr_logging.DEBUG_LEVEL_1,
                            "\\n\\n".join(logged_response),
                            limit_once_per_x_secs=self.log_api_ratelimit_interval,
                            limit_key="query-api-log-resp-%s"
                            % util.md5_hexdigest(path),
                        )

    def query_object(self, kind, namespace, name, query_options=None):
        """ Queries a single object from the k8s api based on an object kind, a namespace and a name
            An empty dict is returned if the object kind is unknown, or if there is an error generating
            an appropriate query string
            @param kind: the kind of the object
            @param namespace: the namespace to query in
            @param name: the name of the object
            @return - a dict returned by the query
        """
        if kind not in _OBJECT_ENDPOINTS:
            global_log.warn(
                "k8s API - tried to query invalid object type: %s, %s, %s.  Creating dummy object"
                % (kind, namespace, name),
                limit_once_per_x_secs=300,
                limit_key="k8s_api_query-%s" % kind,
            )
            if kind is None:
                kind = "<invalid>"

            # return a dummy object with valid kind, namespace and name members
            return {"kind": kind, "metadata": {"namespace": namespace, "name": name}}

        query = None
        try:
            query = _OBJECT_ENDPOINTS[kind]["single"].substitute(
                name=name, namespace=namespace
            )
        except Exception as e:
            global_log.warn(
                "k8s API - failed to build query string - %s" % (six.text_type(e)),
                limit_once_per_x_secs=300,
                limit_key="k8s_api_build_query-%s" % kind,
            )
            return {}

        return self.query_api_with_retries(
            query,
            query_options=query_options,
            retry_error_context="%s, %s, %s" % (kind, namespace, name),
            retry_error_limit_key="query_object-%s" % kind,
        )

    def query_objects(self, kind, namespace=None, filter=None):
        """ Queries a list of objects from the k8s api based on an object kind, optionally limited by
            a namespace and a filter
            A dict containing an empty 'items' array is returned if the object kind is unknown, or if there is an error generating
            an appropriate query string
        """
        if kind not in _OBJECT_ENDPOINTS:
            global_log.warn(
                "k8s API - tried to list invalid object type: %s, %s"
                % (kind, namespace),
                limit_once_per_x_secs=300,
                limit_key="k8s_api_list_query-%s" % kind,
            )
            return {"items": []}

        query = _OBJECT_ENDPOINTS[kind]["list-all"]
        if namespace:
            try:
                query = _OBJECT_ENDPOINTS[kind]["list"].substitute(namespace=namespace)
            except Exception as e:
                global_log.warn(
                    "k8s API - failed to build namespaced query list string - %s"
                    % (six.text_type(e)),
                    limit_once_per_x_secs=300,
                    limit_key="k8s_api_build_list_query-%s" % kind,
                )

        if filter:
            query = "%s?fieldSelector=%s" % (
                query,
                six.moves.urllib.parse.quote(filter),
            )

        return self.query_api_with_retries(
            query,
            retry_error_context="%s, %s" % (kind, namespace),
            retry_error_limit_key="query_objects-%s" % kind,
        )

    def query_pod(self, namespace, name):
        """Convenience method for query a single pod"""
        return self.query_object("Pod", namespace, name)

    def query_pods(self, namespace=None, filter=None):
        """Convenience method for query a single pod"""
        return self.query_objects("Pod", namespace, filter)

    def query_namespaces(self):
        """Wrapper to query all namespaces"""
        return self.query_api_with_retries(
            "/api/v1/namespaces",
            retry_error_context="query_pods",
            retry_error_limit_key="query_pods",
        )

    def stream_events(self, path="/api/v1/watch/events", last_event=None):
        """Streams k8s events from location specified at path"""
        self._ensure_session()
        url = self._http_host + path

        if last_event:
            resource = "resourceVersion=%s" % six.text_type(last_event)
            if "?" in url:
                resource = "&%s" % resource
            else:
                resource = "?%s" % resource

            url += resource

        response = self._session.get(
            url,
            verify=self._verify_connection(),
            timeout=self.query_timeout,
            stream=True,
        )
        if response.status_code != 200:
            global_log.log(
                scalyr_logging.DEBUG_LEVEL_0,
                "Invalid response from K8S API.\n\turl: %s\n\tstatus: %d\n\tresponse length: %d"
                % (url, response.status_code, len(response.text)),
                limit_once_per_x_secs=300,
                limit_key="k8s_stream_events",
            )
            raise K8sApiException(
                "Invalid response from Kubernetes API when querying %d - '%s': %s"
                % (response.status_code, path, six.text_type(response)),
                status_code=response.status_code,
            )

        for line in response.iter_lines():
            if line:
                yield line


class KubeletApi(object):
    """
        A class for querying the kubelet API
    """

    def __init__(
        self,
        k8s,
        host_ip=None,
        node_name=None,
        verify_https=True,
        kubelet_url_template=Template("https://${host_ip}:10250"),
        ca_file="/run/secrets/kubernetes.io/serviceaccount/ca.crt",
    ):
        """
        @param k8s - a KubernetesApi object
        """
        self._ca_file = ca_file
        self._host_ip = host_ip
        self._verify_https = verify_https
        if self._host_ip is None:
            try:
                pod_name = k8s.get_pod_name()
                pod = k8s.query_pod(k8s.namespace, pod_name)
                status = pod.get("status", {})
                self._host_ip = status.get("hostIP", None)
                # Don't raise exception for now
                # if host_ip is None:
                #     raise KubeletApiException( "Unable to get host IP for pod: %s/%s" % (k8s.namespace, pod_name) )
            except Exception:
                global_log.exception("couldn't get host ip")
                pass

        self._session = requests.Session()
        headers = {
            "Accept": "application/json",
            "Authorization": "Bearer %s" % k8s.token,
        }
        self._session.headers.update(headers)

        global_log.info("KubeletApi host ip = %s" % self._host_ip)
        self._kubelet_url = self._build_kubelet_url(
            kubelet_url_template, host_ip, node_name
        )
        self._fallback_kubelet_url = self._build_kubelet_url(
            FALLBACK_KUBELET_URL_TEMPLATE, host_ip, node_name
        )
        self._timeout = 20.0

    @staticmethod
    def _build_kubelet_url(kubelet_url, host_ip, node_name):
        if node_name and host_ip:
            return kubelet_url.substitute(node_name=node_name, host_ip=host_ip)
        return None

    def _switch_to_fallback(self):
        self._kubelet_url = self._fallback_kubelet_url

    def _verify_connection(self):
        """ Return whether or not to use SSL verification
        """
        if self._verify_https and self._ca_file:
            return self._ca_file
        return False

    def _get(self, url, verify):
        return self._session.get(url, timeout=self._timeout, verify=verify)

    def query_api(self, path):
        """ Queries the kubelet API at 'path', and converts OK responses to JSON objects
        """
        while True:
            url = self._kubelet_url + path
            # We suppress warnings here to avoid spam about an unverified connection going to stderr.
            # This method of warning suppression is not thread safe and has a small chance of suppressing warnings from
            # other threads if they are emitted while this request is going.
            verify_connection = self._verify_connection()
            if not verify_connection:
                with warnings.catch_warnings():
                    warnings.simplefilter(
                        "ignore",
                        category=requests.packages.urllib3.exceptions.InsecureRequestWarning,
                    )
                    response = self._get(url, False)
                if self._kubelet_url.startswith("https://"):
                    global_log.warn(
                        "Accessing Kubelet with an unverified HTTPS request.",
                        limit_once_per_x_secs=3600,
                        limit_key="unverified-kubelet-request",
                    )
            else:
                response = self._get(url, verify_connection)
            response.encoding = "utf-8"
            if response.status_code != 200:
                if (
                    response.status_code == 403
                    and self._kubelet_url != self._fallback_kubelet_url
                ):
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_3,
                        "Invalid response while querying the Kubelet API: %d. Falling back to older endpoint."
                        % response.status_code,
                    )
                    self._switch_to_fallback()
                    continue
                else:
                    global_log.log(
                        scalyr_logging.DEBUG_LEVEL_3,
                        "Invalid response from Kubelet API.\n\turl: %s\n\tstatus: %d\n\tresponse length: %d"
                        % (url, response.status_code, len(response.text)),
                        limit_once_per_x_secs=300,
                        limit_key="kubelet_api_query",
                    )
                    raise KubeletApiException(
                        "Invalid response from Kubelet API when querying '%s': %s"
                        % (path, six.text_type(response))
                    )

            return util.json_decode(response.text)

    def query_pods(self):
        return self.query_api("/pods")

    def query_stats(self):
        return self.query_api("/stats/summary")


class K8sConfigBuilder(object):
    """Builds log configs for containers based on config snippets found in the `k8s_logs` field of
    the config file.
    """

    def __init__(
        self,
        k8s_log_configs,
        logger,
        rename_no_original,
        rename_logfile=None,
        parse_format="json",
    ):
        """
        @param k8s_log_configs: The config snippets from the configuration
        @param logger: A scalyr logger
        @param rename_no_original: A bool, used to prevent the original log file name from being added to the attributes.
        @param rename_logfile: A value for renaming a logfile - can contain variable substitutions
        @param parse_format: The parse format of this log config
        """

        if rename_logfile is None:
            rename_logfile = "/${container_runtime}/${container_name}.log"

        self.__k8s_log_configs = k8s_log_configs
        self._logger = logger
        self.__rename_logfile = rename_logfile
        self.__rename_no_original = rename_no_original
        self.__parse_format = parse_format

    def _check_match(self, element, name, value, glob):
        """
        Checks to see if we have a match against the glob for a certain value
        @param element: The index number of the element in the k8s_config list
        @param name: A string containing the name of the field we are evaluating (used for debug log purposes)
        @param value: The value of the field to evaluate the glob against
        @param glob: A string containing a glob to evaluate
        """
        result = False
        if glob is not None and value is not None:
            # ignore this config if value doesn't match the glob
            if fnmatch.fnmatch(value, glob):
                result = True
            else:
                self._logger.log(
                    scalyr_logging.DEBUG_LEVEL_2,
                    "Ignoring k8s_log item %d because %s '%s' doesn't match '%s'"
                    % (element, name, value, glob,),
                )
        return result

    def get_log_config(self, info, k8s_info, parser):
        """
        Creates a log_config from various attributes and then applies any `k8s_logs` configs that
        might apply to this log
        @param info: A dict containing docker information about the container we are creating a config for
        @param k8s_info: A dict containing k8s information about the container we are creating a config for
        @param parser: A string containing the name of the parser to use for this log config
        @return: A dict containing a log_config, or None if we couldn't create a valid config (i.e. log_path was empty)
        """

        # Make sure we have a log_path for the log config
        path = info.get("log_path", None)
        if not path:
            return None

        # Build up the default config that we will use
        result = {
            "parser": parser,
            "path": path,
            "parse_format": self.__parse_format,
            "rename_logfile": self.__rename_logfile,
            "rename_no_original": self.__rename_no_original,
        }

        # If we don't have any k8s information then we don't match against k8s_log_configs
        if k8s_info is None:
            return result

        # Now apply log configs
        for i, config in enumerate(self.__k8s_log_configs):
            # We check for glob matches against `k8s_pod_glob`, `k8s_namespace_glob` and `k8s_container_glob`

            # Check for the pod glob
            pod_glob = config.get("k8s_pod_glob", None)
            pod_name = k8s_info.get("pod_name", None)
            if not self._check_match(i, "pod_name", pod_name, pod_glob):
                continue

            # Check for the namespace glob
            namespace_glob = config.get("k8s_namespace_glob", None)
            pod_namespace = k8s_info.get("pod_namespace", None)
            if not self._check_match(i, "pod_namespace", pod_namespace, namespace_glob):
                continue

            # Check for the k8s container name glob
            container_glob = config.get("k8s_container_glob", None)
            k8s_container = k8s_info.get("k8s_container_name", None)
            if not self._check_match(
                i, "k8s_container_name", k8s_container, container_glob
            ):
                continue

            self._logger.log(
                scalyr_logging.DEBUG_LEVEL_2,
                "Applying k8s_log config item %d.  Matched pod_name ('%s', '%s'), pod_namespace ('%s', '%s'),  k8s_container_name ('%s', '%s')"
                % (
                    i,
                    pod_name,
                    pod_glob,
                    pod_namespace,
                    namespace_glob,
                    k8s_container,
                    container_glob,
                ),
            )
            # We have the first matching config.  Apply the log config and break
            # Note, we can't just .update() because we may need to exclude `path`
            for key, value in six.iteritems(config):
                # Ignore `path` so people can't override it
                if key == "path":
                    continue
                else:
                    result[key] = value

            # Done
            break

        return result


class DockerMetricFetcher(object):
    """Allows for parallel fetching of container metrics from Docker.  Typically, one instance of this object
    will be created per monitor (Docker or Kubernetes).  This current implementation relies on threads to
    issue multiple `stats` requests in parallel.

    This approach is necessary because the `stats` Docker command blocks for 2 seconds while it gathers
    cpu measures over the interval.  If we had 40 containers whose metrics we were trying to retrieve, we would
    have to wait for a total of 80 seconds if we issued the `stats` request one at a time.

    To get the benefit of this approach, you must first invoke `prefetch_metrics` for each container whose metrics
    you wish to retrieve, and then invoke `get_metrics` to actually get the metrics.
    """

    def __init__(self, docker_client, concurrency):
        """

        @param docker_client:  The docker client object to use for issuing `stats` requests.
        @param concurrency:  The maximum number of `stats` requests to issue in parallel.  This controls the maximum
            number of threads that will be created.
        @type docker_client: k8s_test.MetricFaker
        @type concurrency: int
        """
        self.__docker_client = docker_client
        self.__concurrency = concurrency

        # A sentinel value used in the `__container_scoreboard` to indicate the container is in the queue to be fetched.
        self.__PENDING = dict()
        # A sentinel value used in the `__container_scoreboard` to indicate the `stats` call for a container has been
        # issued but no response has been received.
        self.__IN_FLIGHT = dict()

        # The lock that must be held for all other state variables in this class.
        self.__lock = threading.Lock()
        # Records the state of requesting metrics for all containers.  Maps the container name to its state or
        # metric value.  If the value is __PENDING, then the `stats` request for the request has not been issued.
        # If it is __IN_FLIGHT, it has been requested.  If it is None, an error occurred.  Otherwise, the value
        # is the result of the `stats` request.
        self.__container_scoreboard = dict()

        # Whether or not `stop` has been invoked.
        self.__is_stopped = False

        # The conditional variable that can be waited on to be notified of any changes to the state of this object,
        # such as whether it has been stopped or if a stats results has been added in to `__container_scoreboard`.
        self.__cv = threading.Condition(self.__lock)

        # The number of worker threads (to perform `stats` calls) that have been created.  This will always be
        # less than `concurrency`.
        self.__num_worker_threads = 0

        # A list of containers whose metrics should be fetched.  This is the same as all entries in
        # `__container_scoreboard` whose value is `__PENDING`.
        self.__pending_fetches = []
        # The total number of containers in `__container_scoreboard` with value either `__PENDING` or `__IN_FLIGHT`.
        self.__remaining_metrics_count = 0
        # The number of worker threads blocked, waiting for a container to fetch its metrics.
        self.__idle_workers_count = 0

    def prefetch_metrics(self, container_id):
        """Initiates requesting invoking `stats` for the specified container.  If you invoke this, you must
        also eventually invoke `get_metrics` with the same container.  By invoking this first, the `get_metrics`
        call will take less time when issuing many `stats` requests.

        Whenever possible, you should first invoke this method for all containers whose metrics you wish to request
        before any call to `get_metrics`.

        The behavior is not well defined if you invoke `prefetch_metrics` multiple times for a container before
        invoking `get_metrics` for it.

        @param container_id: The id of the container to fetch.
        @type container_id: str
        """
        self.__lock.acquire()
        try:
            if container_id not in self.__container_scoreboard:
                self._add_fetch_task(container_id)
        finally:
            self.__lock.release()

    def get_metrics(self, container_id):
        """Blocks until the `stats` call for the specified container is received.  If `prefetch_metrics` was not
        invoked already for this container, then the `stats` request will be issued.

        @param container_id:  The container whose metrics should be fetched.
        @type container_id: str
        @return The metrics for the container, or None if there was an error or if `stop` was invoked on this object.
        @rtype JSON
        """
        self.__lock.acquire()
        try:
            while True:
                if self.__is_stopped:
                    return None

                # Fetch the result if it was prefetched.
                if container_id not in self.__container_scoreboard:
                    self._add_fetch_task(container_id)

                status = self.__container_scoreboard[container_id]
                if status is not self.__PENDING and status is not self.__IN_FLIGHT:
                    result = self.__container_scoreboard[container_id]
                    del self.__container_scoreboard[container_id]
                    return result
                # Otherwise no result has been received yet.. wait..
                self.__cv.wait()
        finally:
            self.__lock.release()

    def stop(self):
        """Stops the fetcher.  Any calls blocking on `get_metrics` will finish and return `None`.  All threads
        started by this instance will be stopped (though, this method does not wait on them to terminate).
        """
        self.__lock.acquire()
        try:
            self.__is_stopped = True
            # Notify all threads that may be waiting on a new container or waiting on a metric result that we have
            # been stopped.
            self.__cv.notifyAll()
        finally:
            self.__lock.release()

    def idle_workers(self):
        """
        Used for testing.

        @return:  The number of worker threads currently blocking, waiting for a container whose metrics need fetching.
        @rtype: int
        """
        self.__lock.acquire()
        try:
            return self.__idle_workers_count
        finally:
            self.__lock.release()

    def _get_fetch_task(self):
        """Blocks until either there is a new container whose metrics need to be fetched or until this instance
        is stopped.
        @return:  A tuple containing the container whose metrics should be fetched and a boolean indicating if the
            instance has been stopped.  If it has been stopped, the container will be None.
        @rtype: (str, bool)
        """
        self.__lock.acquire()
        try:
            while True:
                if self.__is_stopped:
                    return None, True
                if len(self.__pending_fetches) > 0:
                    container = self.__pending_fetches.pop(0)
                    self.__container_scoreboard[container] = self.__PENDING
                    self.__idle_workers_count -= 1
                    return container, False
                self.__cv.wait()
        finally:
            self.__lock.release()

    def __start_workers(self, count):
        """Start `count` worker threads that will fetch metrics results.

        @param count:  The number of threads to start.
        @type count: int
        """
        new_number_workers = min(self.__concurrency, count + self.__num_worker_threads)
        for i in range(self.__num_worker_threads, new_number_workers):
            x = threading.Thread(target=self.__worker)
            # Set daemon so this thread does not need to be finished for the overall process to stop.  This allows
            # the process to terminate even if a `stats` request is still in-flight.
            x.setDaemon(True)
            x.start()
            self.__num_worker_threads += 1
            # For accounting purposes,we consider the thread idle until it actually has a container it is fetching.
            self.__idle_workers_count += 1

    def __worker(self):
        """The body for the worker threads.
        """
        while True:
            # Get the next container to fetch if there is one.
            container_id, is_stopped = self._get_fetch_task()
            if is_stopped:
                return

            result = None
            try:
                global_log.log(
                    scalyr_logging.DEBUG_LEVEL_3,
                    "Attempting to retrieve metrics for cid=%s" % container_id,
                )
                result = self.__docker_client.stats(
                    container=container_id, stream=False
                )
            except Exception as e:
                global_log.error(
                    "Error readings stats for '%s': %s\n%s"
                    % (container_id, six.text_type(e), traceback.format_exc()),
                    limit_once_per_x_secs=300,
                    limit_key="api-stats-%s" % container_id,
                )
            self._record_fetch_result(container_id, result)

    def _add_fetch_task(self, container_id):
        """Adds the specified container to the list of containers whose metrics will be fetched.  Eventually, a worker
        thread will grab this container and fetch its metrics.

        IMPORTANT: callers must hold `__lock` when invoking this method.

        @param container_id:  The container whose metrics should be fetched.
        @type container_id: str
        """
        self.__remaining_metrics_count += 1
        self.__container_scoreboard[container_id] = self.__PENDING
        self.__pending_fetches.append(container_id)
        # Notify any worker threads waiting for a container.
        self.__cv.notifyAll()

        # We need to spin up new worker threads if the amount of remaining metrics (PENDING or IN-FLIGHT) is greater
        # than the number of threads we already have.
        if (
            self.__remaining_metrics_count > self.__num_worker_threads
            and self.__num_worker_threads < self.__concurrency
        ):
            self.__start_workers(
                self.__remaining_metrics_count - self.__num_worker_threads
            )

    def _record_fetch_result(self, container_id, result):
        """Record that the `stats` result for the specified container.  If there was an error, result should be
        None.
        @type container_id: str
        @type result: JsonObject
        """
        self.__lock.acquire()
        try:
            self.__container_scoreboard[container_id] = result
            self.__remaining_metrics_count -= 1
            # Since this is only invoked by a worker once their stats call is done, we know they are now idle.
            self.__idle_workers_count += 1
            # Wake up any thread that was waiting on this result.
            self.__cv.notifyAll()
        finally:
            self.__lock.release()


def _create_k8s_cache():
    """
        creates a new k8s cache object
    """

    return KubernetesCache(start_caching=False)


# global cache object - the module loading system guarantees this is only ever
# initialized once, regardless of how many modules import k8s.py
_k8s_cache = _create_k8s_cache()
