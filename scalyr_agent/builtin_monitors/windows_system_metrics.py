#!/usr/bin/env python
"""{ShortDescription}

{ExtendedDescription}


# QuickStart

Use the ``run_monitor`` test harness to drive this basic modules and begin your
plugin development cycle.

    $ python -m scalyr_agent.run_monitor -p /path/to/scalyr_agent/builtin_monitors

# Credits & License
Author: Supermassive Blackhole '<OnTheEdge@TheEventHorizon.com>'
License: Apache 2.0

------------------------------------------------------------------------
Copyright 2014 Scalyr Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
------------------------------------------------------------------------
"""

__author__ = "Supermassive Blackhole '<OnTheEdge@TheEventHorizon.com>'"
__version__ = "0.0.1"
__monitor__ = __name__


import sys

try:
    import scalyr_agent
except ImportError:
    # pylint: disable=bad-continuation
    msg = ["This monitor requires the scalyr_agent module to be installed or on the PYTHONPATH",
            "If you are not a developer, but are seeing this message - you probably want to be using",
            "one of the install scripts to deploy the ScalyrAgent to your system.  If you have intentionally",
            "not used the installer(s), then the next best way to deploy the ScalyrAgent into your system is",
            "to:"
            "\tNOTICE: The setup module (standard python distribution framework stuff) provides help for those",
            "\t\tthat are interested in modifyting the default installation parameters - the various install schemes",
            "are notable and useful particularly if you are having permission issues installing to the system-wide",
            "directories on your machine",
            "",
            "python setup.py install",
            "\t... or...",
            "pip install -e /path/to/scalyr-agent-2/",
    ]
    # pylint: enable=bad-continuation
    sys.stderr.write(msg)
    sys.exit(1)
else:
    from scalyr_agent import ScalyrMonitor, BadMonitorConfiguration
    from scalyr_agent import define_config_option, define_metric, define_log_field
    from scalyr_agent import scalyr_logging



import psutil



#
# Monitor Configuration - defines the runtime environment and resources available
#
CONFIG_OPTIONS = [
    dict(
        option_name='module',
        option_description='A ScalyrAgent plugin monitor module',
        convert_to=str,
        required_option=True,
        default='linux_process_metrics'
    ),
    dict(
        option_name='commandline',
        option_description='A regular expression which will match the command line of the process you\'re interested '
        'in, as shown in the output of ``ps aux``. (If multiple processes match the same command line pattern, '
        'only one will be monitored.)',
        default=None,
        convert_to=str
    ),
    dict(
        option_name='pid',
        option_description='The pid of the process from which the monitor instance will collect metrics.  This is '
        'ignored if the ``commandline`` is specified.',
        default='$$',
        convert_to=str
    ),
    dict(
        option_name='id',
        option_description='Included in each log message generated by this monitor, as a field named ``instance``. '
        'Allows you to distinguish between values recorded by different monitors.',
        required_option=True,
        convert_to=str
    )
]

_ = [define_config_option(__monitor__, **option) for option in CONFIG_OPTIONS] # pylint: disable=star-args
## End Monitor Configuration
# #########################################################################################




# #########################################################################################
# #########################################################################################
# ## Process's Metrics / Dimensions -
# ##
# ##    Metrics define the capibilities of this monitor.  These some utility functions
# ##    along with the list(s) of metrics themselves.
# ##
def _gather_metric(method, attribute=None):
    """Curry arbitrary process metric extraction

    @param method: a callable member of the process object interface
    @param attribute: an optional data member, of the data structure returned by ``method``

    @type method callable
    @type attribute str
    """
    doc = "Extract the {} attribute from the given process object".format
    if attribute:
        doc = "Extract the {}().{} attribute from the given process object".format

    def gather_metric():
        """Dynamically Generated """

        #assert type(process) is psutil.Process, "Only the 'psutil.Process' interface is supported currently; not {}".format(type(process))
        metric = methodcaller(method)   # pylint: disable=redefined-outer-name
        return attribute and attrgetter(attribute)(metric(psutil)) or metric(psutil)

    gather_metric.__doc__ = doc(method, attribute)
    return gather_metric


def uptime(start_time):
    """Calculate the difference between now() and the given create_time.

    @param start_time: milliseconds passed since 'event' (not since epoc)
    @type float
    """
    from datetime import datetime
    return datetime.now() - datetime.fromtimestamp(start_time)


try:
    from operator import methodcaller, attrgetter
except ImportError:
    def methodcaller(name, *args, **kwargs):
        def caller(obj):
            return getattr(obj, name)(*args, **kwargs)
        return caller

try:
    from collections import namedtuple
    METRIC = namedtuple('METRIC', 'config dispatch')
except ImportError:

    class NamedTupleHack(object):
        def __init__(self, *args):
            self._typename = args[0]
            self._fieldnames = args[1:]
        def __str__(self):
            return "<{typename}: ({fieldnames})...>".format(self._typename, self._fieldnames[0])
    METRIC = NamedTupleHack('Metric', 'config dispatch')


METRIC_CONFIG = dict    # pylint: disable=invalid-name
GATHER_METRIC = _gather_metric


# pylint: disable=bad-whitespace
# =================================================================================
# ============================    System CPU    ===================================
# =================================================================================
_SYSTEM_CPU_METRICS = [
    METRIC( ## ------------------  User CPU ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winsys.cpu',
            description     = 'The seconds the cpu has spent in the given mode.',
            category        = 'general',
            unit            = 'secs:1.00',
            cumulative      = True,
            extra_fields    = {
                'type': 'User'
            },
        ),
        GATHER_METRIC('cpu_times', 'user')
    ),
    METRIC( ## ------------------  System CPU ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winsys.cpu',
            description     = 'The seconds the cpu has spent in the given mode.',
            category        = 'general',
            unit            = 'secs:1.00',
            cumulative      = True,
            extra_fields    = {
                'type': 'system'
            },
        ),
        GATHER_METRIC('cpu_times', 'system')
    ),
    METRIC( ## ------------------  Idle CPU ----------------------------
        METRIC_CONFIG(
            metric_name     = 'winsys.cpu',
            description     = 'The seconds the cpu has spent in the given mode.',
            category        = 'general',
            unit            = 'secs:1.00',
            cumulative      = True,
            extra_fields    = {
                'type': 'idle'
            },
        ),
        GATHER_METRIC('cpu_times', 'idle')
    ),

    # TODO: Additional attributes for this section
    #  * ...
]


# =================================================================================
# ========================    UPTIME METRICS     ===============================
# =================================================================================
_UPTIME_METRICS = [

    METRIC( ## ------------------  System Boot Time   ----------------------------
        METRIC_CONFIG(
            metric_name     = 'proc.uptime',
            description     = 'System boot time in seconds since the epoch.',
            category        = 'general',
            unit            = 'sec',
            cumulative      = True,
            extra_fields    = {}
        ),
        GATHER_METRIC('boot_time', None)
    ),

    # TODO: Additional attributes for this section
    #  * ...
]

# =================================================================================
# ========================    Virtual Memory    ===============================
# =================================================================================
_VIRTUAL_MEMORY_METRICS = [

    METRIC( ## ------------------    Total Virtual Memory    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'memory.virtual',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            #cumulative      = {cumulative},
            extra_fields    = {
                'type': 'total',
                }
        ),
        GATHER_METRIC('virtual_memory', 'total')
    ),
    METRIC( ## ------------------    Used Virtual Memory    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'memory.virtual',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            #cumulative      = {cumulative},
            extra_fields    = {
                'type': 'used',
                }
        ),
        GATHER_METRIC('virtual_memory', 'used')
    ),
    METRIC( ## ------------------    Free Virtual Memory    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'memory.virtual',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            #cumulative      = {cumulative},
            extra_fields    = {
                'type': 'free',
                }
        ),
        GATHER_METRIC('virtual_memory', 'free')
    ),


    # TODO: Additional attributes for this section
    #  * ...
]

# =================================================================================
# ========================    Physical Memory    ===============================
# =================================================================================
_PHYSICAL_MEMORY_METRICS = [

    METRIC( ## ------------------    Total Physical Memory    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'memory.physical',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            #cumulative      = {cumulative},
            extra_fields    = {
                'type': 'total',
                }
        ),
        GATHER_METRIC('virtual_memory', 'total')
    ),
    METRIC( ## ------------------    Used Physical Memory    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'memory.physical',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            #cumulative      = {cumulative},
            extra_fields    = {
                'type': 'used',
                }
        ),
        GATHER_METRIC('virtual_memory', 'used')
    ),
    METRIC( ## ------------------    Free Physical Memory    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'memory.physical',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            #cumulative      = {cumulative},
            extra_fields    = {
                'type': 'free',
                }
        ),
        GATHER_METRIC('virtual_memory', 'free')
    ),


    # TODO: Additional attributes for this section
    #  * ...
]


# =================================================================================
# ========================    Network IO Counters   ===============================
# =================================================================================
_NETWORK_IO_METRICS = [

    METRIC( ## ------------------   Bytes Sent  ----------------------------
        METRIC_CONFIG(
            metric_name     = 'network.io',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            cumulative      = True,
            extra_fields    = {
                'type': 'sent',
                }
        ),
        GATHER_METRIC('network_io_counters', 'bytes_sent')
    ),
    METRIC( ## ------------------   Bytes Recv  ----------------------------
        METRIC_CONFIG(
            metric_name     = 'network.io',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            cumulative      = True,
            extra_fields    = {
                'type': 'recv',
                }
        ),
        GATHER_METRIC('network_io_counters', 'bytes_recv')
    ),
    METRIC( ## ------------------   Packets Sent  ----------------------------
        METRIC_CONFIG(
            metric_name     = 'network.io',
            description     = '{description}',
            category        = 'general',
            unit            = 'packets',
            cumulative      = True,
            extra_fields    = {
                'type': 'sent',
                }
        ),
        GATHER_METRIC('network_io_counters', 'packets_sent')
    ),
    METRIC( ## ------------------   Packets Recv  ----------------------------
        METRIC_CONFIG(
            metric_name     = 'network.io',
            description     = '{description}',
            category        = 'general',
            unit            = 'packets',
            cumulative      = True,
            extra_fields    = {
                'type': 'recv',
                }
        ),
        GATHER_METRIC('network_io_counters', 'packets_recv')
    ),


    # TODO: Additional attributes for this section
    #  * dropped packets in/out
    #  * error packets in/out
    #  * various interfaces
]


# =================================================================================
# ========================     Disk IO Counters     ===============================
# =================================================================================
_DISK_IO_METRICS = [

    METRIC( ## ------------------   Disk Bytes Read    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'disk.io',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            cumulative      = True,
            extra_fields    = {
                'type': 'read'
                }
        ),
        GATHER_METRIC('disk_io_counters', 'read_bytes')
    ),
    METRIC( ## ------------------  Disk Bytes Written  ----------------------------
        METRIC_CONFIG(
            metric_name     = 'disk.io',
            description     = '{description}',
            category        = 'general',
            unit            = 'bytes',
            cumulative      = True,
            extra_fields    = {
                'type': 'write'
                }
        ),
        GATHER_METRIC('disk_io_counters', 'write_bytes')
    ),
    METRIC( ## ------------------   Disk Read Count    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'disk.io',
            description     = '{description}',
            category        = 'general',
            unit            = 'count',
            cumulative      = True,
            extra_fields    = {
                'type': 'read'
                }
        ),
        GATHER_METRIC('disk_io_counters', 'read_count')
    ),
    METRIC( ## ------------------   Disk Write Count    ----------------------------
        METRIC_CONFIG(
            metric_name     = 'disk.io',
            description     = '{description}',
            category        = 'general',
            unit            = 'count',
            cumulative      = True,
            extra_fields    = {
                'type': 'write'
                }
        ),
        GATHER_METRIC('disk_io_counters', 'write_count')
    ),


    # TODO: Additional attributes for this section
    #  * ...
]

section_template = """
# =================================================================================
# ========================    {section_title}     ===============================
# =================================================================================
_{section_title}_METRICS = [

    METRIC( ## ------------------    {metric_title}    ----------------------------
        METRIC_CONFIG(
            metric_name     = '{module}.{group}',
            description     = '{description}',
            category        = '{category}',
            unit            = '{unit}',
            cumulative      = {cumulative},
            extra_fields    = {
                'type': '{extra_fields[type]]}'
                }
        ),
        GATHER_METRIC('{dispatch[method]}', '{dispatch[attribute]}')
    ),

    # TODO: Additional attributes for this section
    #  * ...
]
"""

# pylint: enable=bad-whitespace

METRICS = _SYSTEM_CPU_METRICS + _UPTIME_METRICS + _VIRTUAL_MEMORY_METRICS + _PHYSICAL_MEMORY_METRICS + _NETWORK_IO_METRICS + _DISK_IO_METRICS
_ = [define_metric(__monitor__, **metric.config) for metric in METRICS]     # pylint: disable=star-args




#
# Logging / Reporting - defines the method and content in which the metrics are reported.
#
define_log_field(__monitor__, 'monitor', 'Always ``linux_process_metrics``.')
define_log_field(__monitor__, 'instance', 'The ``id`` value from the monitor configuration, e.g. ``tomcat``.')
define_log_field(__monitor__, 'app', 'Same as ``instance``; provided for compatibility with the original Scalyr Agent.')
define_log_field(__monitor__, 'metric', 'The name of a metric being measured, e.g. "app.cpu".')
define_log_field(__monitor__, 'value', 'The metric value.')




import itertools

class SystemMonitor(ScalyrMonitor):
    """Windows System Metrics"""

    def __init__(self, config, logger, **kwargs):
        sampling_rate = kwargs.get('sampling_rate', 30)
        super(SystemMonitor, self).__init__(config, logger, sampling_rate)
        self.__debug = {
            'counter': itertools.count()
        }


    def gather_sample(self):
        counter = self.__debug['counter']
        sample_id = counter.next()
        applog.debug('Sampling metrics (Iteration %03d)', sample_id)

        try:
            applog.info(
                "Enumerating and emitting {} metrics".format(len(METRICS))
            )
            for idx, metric in enumerate(METRICS):
                #print '-' * 70
                #print idx, metric

                metric_name = metric.config['metric_name']
                metric_value = metric.dispatch()

                #print metric_name
                #print metric_value
                #print '-' * 70

                logmsg = "Sampled %s at %s %d-%d".format
                applog.debug(logmsg(metric_name, metric_value, sample_id, idx))
                self._logger.emit_value(
                    metric_name,
                    metric_value,
                    extra_fields=metric.config['extra_fields']
                )
            applog.debug('Sampling complete (Iteration %s)', sample_id)
        except:
            self.__process = None
            exc_type, exc_value, traceback = sys.exc_info()
            print exc_type, exc_value
            import traceback
            traceback.print_exc()


def create_application_logger(name=None, level=scalyr_logging.DEBUG_LEVEL_0, parent=None, **config):
    """Configure a logging interface for the monitor plugin module to use.

    The monitor, separate from emitting it's metrics, needs to communicate it's health, activities,
    and journalling unexpected or repeated errors.

    """
    if not name:
        name = "{}.application".format(__name__)
    logger = parent and parent.getChild(name) or scalyr_logging.getLogger(name)
    scalyr_logging.set_log_level(level)

    #slc = collections.defaultdict(lambda k: '<Uninitialized>', use_stdout=True, use_disk=False, )
    scalyr_logging.set_log_destination(use_stdout=True)
    return logger




applog = create_application_logger()  # pylint: disable=invalid-name

if __name__ == "__main__":
    parser = create_commandline_parser()        # pylint: disable=invalid-name
    options, command = parser.parse_args()      # pylint: disable=invalid-name

    MSG = "** Log Level Active **"
    applog.critical(MSG)
    applog.warn(MSG)
    applog.info(MSG)
    applog.debug(MSG)
    applog.info('Module loading...')
