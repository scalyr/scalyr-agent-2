<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->

# GarbageMonitor

The garbage monitor outputs statistics returned by python's builtin garbage collection module.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file (``/etc/scalyr/agent.json``).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).

By default it outputs a list of types and a count of objects of that type that cannot be reclaimed
by the garbage collector.

It can also be configured to dump a string representation of unreachable objects of specific types.

## Sample Configuration

This sample will configure the garbage monitor to output the top 10 types with the most unreachable objects.

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.garbage_monitor",
        max_type_dump: 10
      }
    ]

This sample will configure the garbage monitor to output the top 10 types with the most unreachable objects,
along with dumping up to 20 objects of the types 'list' and 'dict'.

    monitors: [
      {
        module: "scalyr_agent.builtin_monitors.garbage_monitor",
        max_type_dump: 10,
        object_dump_types: [ "list", "dict" ],
        max_object_dump: 20
      }
    ]
## Configuration Reference

|||# Option                                    ||| Usage
|||# ``module``                                ||| Always ``scalyr_agent.builtin_monitors.garbage_monitor``
|||# ``disable_garbage_collection_before_dump``||| Optional (defaults to False). By default the garbage_monitor will \
                                                   perform a garbage collection before it dumps the list of \
                                                   unreachable objects to ensure that objects are actually leaking.  \
                                                   If this flag is set to True then then garbage monitor will not \
                                                   perform this collection.  This is useful when trying to find \
                                                   objects with cyclic references that are not being readily collected \
                                                   by the garbage collector, but that would eventually be collected.
|||# ``max_type_dump``                         ||| Optional (defaults to 20). The maximum number of unreachable types \
                                                   to output each gather_sample
|||# ``max_object_dump``                       ||| Optional (defaults to 0). The maximum number of unreachable objects \
                                                   to dump for each type on the ``object_dump_types`` list. Set to -1 \
                                                   to include all objects
|||# ``monitor_garbage_objects``               ||| Optional (defaults to True).  If False, garbage objects are not \
                                                   dumped.
|||# ``monitor_live_objects``                  ||| Optional (defaults to False).  If True, monitors live objects - \
                                                   i.e. those still in use and not read for garbage collection.
|||# ``monitor_all_unreachable_objects``       ||| Optional (defaults to False).  If True, monitors all unreachable \
                                                   objects, not just ones that have circular __del__ dependencies. See \
                                                   the python gc documentation for details: \
                                                   https://docs.python.org/2/library/gc.html#gc.garbage
|||# ``object_dump_types``                     ||| Optional.  A list of type names as strings.  For all types on this \
                                                   list, the garbage_monitor will dump a string representation of \
                                                   unreachable objects of this type, up to ``max_object_dump`` \
                                                   objects. The strings should match the type names printed out in the \
                                                   normal output of the garbage_monitor.
