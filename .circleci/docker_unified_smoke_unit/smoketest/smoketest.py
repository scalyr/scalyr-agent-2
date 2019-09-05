"""
Agent smoketest code.

This python script is meant to be invoked within a docker image in which the proper python version is activated (e.g.
via pyenv).  In this way, the agent can be validated against different python versions.

Concept:
    This code serves as a common code-base for different types of smoketest "processes" (i.e. same code runs in
    different modes). Examples of modes are (uploader, verifier).

    Uploader (a.k.a Producer):
        Waits for Scalyr agent to be up and running (by querying scalyr backend).
        Produces 1000 lines of dummy data very quickly, then produces one additional line of data every second.
        If the agent is working correctly, this data will be correctly ingested and uploaded to Scalyr (by the agent)
        and can subsequently be verified (by the Verifier).

    Verifier:
        Waits for Scalyr agent to be up and running.
        Keeps polling until max_wait for the expected uploader data.

Usage:
    smoketest.py ${process_name} ${max_wait} \
    --mode verifier \
    --scalyr_server ${SCALYR_SERVER} \
    --read_api_key ${READ_API_KEY} \
    --agent_hostname ${agent_hostname} \
    --uploader_hostname ${uploader_hostname} \
    --debug true"

where:
    process_name: A means by which the invoker script can inform this script what the current process name is.
        The process_name is important as it is parsed/modified to construct verifying queries.
        E.g. process_name is used to construct a logfile to be queried such as "/docker/<process_name>-uploader.log".
        Moreover, any given CI build should not conflict with other builds and therefore should have a unique
        process name (e.g. /docker/ci-agent-docker-json-5986-uploader.log where "ci-agent-docker-json-5986" is a unique
        identifier specific to a CI build.

        Additionally, the process name determines which class to instantiate (see
        CONTAINER_PREFIX_2_VERIFIER_CLASS). The invoker can choose different implementations (e.g. for LogStash)
        by using on of the prefixes defined CONTAINER_PREFIX_2_VERIFIER_CLASS. An object of that class is then
        instantiated and begins running in the specified mode (either as an Uploader or Verifier).

    max_wait: Maximum time to run until exiting with failure.

    mode: Operational mode which determines what this process does. Must be one of (uploader, verifier, agent).

    scalyr_server: Scalyr backend server to connect to (typically qatesting.scalyr.com when testing)

    monitored_logfile: Absolute path of the data file to write which the agent then ingests.  Logstash producers also
        write to this file which is then configured to as an input into the Logstash aggregator.

    python_version: Python version that the agent is running on (becomes part of the Uploader data)

    read_api_key: Read API key to use when querying the Scalyr backend to verify expected data has been uploaded.

    agent_hostname: Uploaders and Verifiers need to know the agent_hostname of the agent process in order to construct
        a proper verifying query (because they query for a log line uploaded by the agent in order to know when it has
        successfully started.  This agent_hostname is typically passed in by the invoker script that starts the Uploader
        or Verifier.

    uploader_hostname: Similar to agent_hostname, Verifiers need to wait for Uploaders to finish uploading before
        performing their verifying queries. The uploader_hostname is a necessary piece of information typically passed
        in by the invoker script that starts the Uploader and Verifier.

    debug: true|false . If true, prints out all Scalyr api queries (useful for debugging)


Note:
    This test code require python 3 with specific packages installed (i.e. requests)
"""

__author__ = 'echee@scalyr.com'


import argparse
import os
import json
import time
import requests
import socket
import sys
import threading
import urllib


NAME_SUFFIX_UPLOADER = 'uploader'
NAME_SUFFIX_VERIFIER = 'verifier'
# no actual Actor will run as the this name but the constant is needed for logic that checks on the Agent container
NAME_SUFFIX_AGENT = 'agent'

NAME_SUFFIXES = [
    NAME_SUFFIX_UPLOADER,
    NAME_SUFFIX_VERIFIER,
    NAME_SUFFIX_AGENT
]


def _pretty_print(header='', message='', file=sys.stdout):
    if header:
        print('', file=file)
        print("="*79, file=file)
        print(header, file=file)
        print("="*79, file=file)
    if len(message) > 0:  # message can be spaces
        print(message, file=file)


def _exit(code, show_agent_status=True, header='', message=''):
    """Prints agent status before exiting"""
    file = sys.stdout if code==0 else sys.stderr
    if show_agent_status:
        _pretty_print(header='BEGIN AGENT STATUS')
        # TODO fix this to work under python 3
        print('TODO: Scalyr agent status does not work under python 3 yet')
        # agent_exec = '/usr/share/scalyr-agent-2/bin/scalyr-agent-2'
        # if os.path.isfile(agent_exec):
        #     os.system('{} status -v'.format(agent_exec))
        _pretty_print(header='END AGENT STATUS')
        _pretty_print(message=' ')
    _pretty_print(header, message, file=file)
    # exit even if other threads are running
    os._exit(code)


class SmokeTestActor(object):
    """
    Abstract base class for all verifiers.
    Some objects may only upload.
    Others may only verify.
    Some may do both, in which case we may need a barrier
    """
    DEFAULT_POLL_INTERVAL_SEC = 10

    def __init__(self, **kwargs):
        self._process_name = kwargs.get('process_name')
        self._scalyr_server = kwargs.get('scalyr_server')
        self._read_api_key = kwargs.get('read_api_key')
        self._max_wait = float(kwargs.get('max_wait'))
        self._localhostname = socket.gethostname()
        self._barrier = None
        self._barrier_lock = threading.Lock()
        self._lines_to_upload = 1000
        self.__init_time = time.time()
        self._agent_started_lock = threading.Lock()
        self._agent_started = False

        self._debug = (kwargs.get('debug') or '').lower() in ('true', 'y', 'yes', 't', '1')

    def _get_uploader_output_streams(self):
        """Returns list of streams to write log data"""
        raise NotImplementedError

    def _get_uploader_stream_names(self):
        """Returns list of streams to write log data"""
        raise NotImplementedError

    def _get_stream_name_from_stream(self, stream):
        return stream.name[1:-1]

    def get_hard_kill_time(self):
        """Returns time in epoch seconds for when this process must terminate"""
        return self.__init_time + self._max_wait

    def verifier_type(self):
        raise NotImplementedError

    def is_verifier(self):
        raise NotImplementedError

    def is_uploader(self):
        raise NotImplementedError

    def _get_barrier(self, parties=2):
        """Lazy-instantiate a barrier"""
        with self._barrier_lock:
            if not self._barrier:
                self._barrier = threading.Barrier(parties, timeout=self._max_wait)
            return self._barrier

    def __wait_at_barrier(self):
        """
        For coordinating processes.  
        Currently only used to prevent uploader OR verifier from proceeding until agent is verified up and running.
        Note: uploader and verifier do not block each other, regardless of whether they 
        run within same process or in different processes.
        """
        barrier = self._get_barrier()
        if barrier:
            print('... Blocking at barrier')
            barrier.wait()
            print('... Unblocked')

    def exit(self, code, **kwargs):
        _exit(code, **kwargs)

    def verify_logs_uploaded(self):
        """Query scalyr to verify presence of uploaded data"""
        raise NotImplementedError

    def verify_agent_started_or_die(self):
        """Verify state or processes that should be present or running if agent is running"""
        raise NotImplementedError

    def wait_for_agent_to_start(self):
        """Both upload or verification should not begin until agent is confirmed started"""
        with self._agent_started_lock:
            if not self._agent_started:
                self.verify_agent_started_or_die()
            self._agent_started = True

    def verify_or_die(self):
        """
        Query the Scalyr backend in search for what we know we uploaded.
        Error out after a certain time limit.

        Returns:
            Nothing.  Exits with status 0 or 1
        """
        self.wait_for_agent_to_start()
        self.verify_logs_uploaded()

    def _make_log_line(self, count, stream):
        """Return a line of text to be written to the log.  Don't include trailing newline
        Args:
            count: line number (concrete class may choose to incorporate into line content for verification)
            stream: output stream (concrete class may choose to incorporate into line content for verification)
        """
        raise NotImplementedError

    def trigger_log_upload(self):
        self.wait_for_agent_to_start()
        streams = self._get_uploader_output_streams()
        count = 0
        while time.time() < self.get_hard_kill_time():
            for stream in streams:
                stream.write(self._make_log_line(count, stream))
                stream.write('\n')
                stream.flush()
                if count >= self._lines_to_upload:
                    time.sleep(1)  # slow down if threshold is reached
            # Write to all streams for a given count
            count += 1

    def _make_query_url(self, filter_dict=None, message='', override_serverHost=None,
                        override_log=None, override_log_regex=None):
        """
        Make url for querying Scalyr server.  Any str filter values will be url-encoded
        """

        base_params = self._get_base_query_params()

        url = 'https://' if not self._scalyr_server.startswith('http') else ''
        url += '{}/api/query?queryType=log&{}'.format(
            self._scalyr_server,
            urllib.parse.urlencode(base_params)
        )

        # Set serverHost/logfile from object state if not overridden
        if not filter_dict:
            filter_dict = {}
        filter_dict['$serverHost'] = (override_serverHost or self._process_name)

        # only if no log regex is provided do we then add an exact logfile match
        if not override_log_regex:
            filter_dict['$logfile'] = (override_log or self._logfile)

        filter_frags = []
        for k, v in filter_dict.items():
            if type(v) == str:
                v = '"{}"'.format(urllib.parse.quote_plus(v))
            filter_frags.append('{}=={}'.format(k, v))

        # If log regex is provided, add a regex matches clause
        if override_log_regex:
            filter_frags.append('{} matches "{}"'.format('$logfile', override_log_regex))

        # Add message
        if message:
            filter_frags.append('$message{}'.format(urllib.parse.quote_plus(' contains "{}"'.format(message))))

        url += '&filter={}'.format('+and+'.join(filter_frags))
        if self._debug:
            print('\nURL quoted = {}'.format(url))
            print('  unquoted = {}'.format(urllib.parse.unquote_plus(url)))
        return url

    def _get_base_query_params(self):
        """Get base query params (not including filter)"""
        params = {
            'maxCount': 1,
            'startTime': '10m',
            'token': self._read_api_key,
        }
        return params

    def poll_until_max_wait(self, verify_func, description, success_mesg, fail_mesg,
                            exit_on_success=False, exit_on_fail=False, poll_interval=None):
        """
        Template design pattern method for polling until a maximum time.  Each poll executes the provided verify_func().
        fail/success messages are parameterized, as well as whether to exit.

        Args:
            verify_func: Function to execute for each check.  Must return True/False
            description: Text to print at beginning of check
            success_mesg: Text to print on success
            fail_mesg: Text to print on failure
            exit_on_success: If success, exit (with code 0)
            exit_on_fail: If fail, exit (with code 1)
        """
        _pretty_print(description)
        verified = False
        prev = time.time()
        while time.time() < self.get_hard_kill_time():

            # Try to verify upload by querying Scalyr server
            sys.stdout.write('. ')
            sys.stdout.flush()
            verified = verify_func()

            # query backend to confirm.
            if verified:
                success_mesg = '\nSUCCESS !!. ' + success_mesg
                if exit_on_success:
                    self.exit(0, message=success_mesg)
                else:
                    _pretty_print(message=success_mesg, file=sys.stdout)
                    break

            # Sleep a bit before trying again
            time.sleep(poll_interval or SmokeTestActor.DEFAULT_POLL_INTERVAL_SEC)
            cur = time.time()
            if cur - prev > 10:
                print('{} seconds remaining'.format(int(self.get_hard_kill_time() - cur)))
                prev = cur
        else:
            fail_mesg = 'FAILED. Time limit reached. ' + fail_mesg
            if exit_on_fail:
                self.exit(1, message=fail_mesg)
            else:
                _pretty_print(message=fail_mesg, file=sys.stderr)


class StandaloneSmokeTestActor(SmokeTestActor):
    """
    Standalone agent verifier.

    A single process performs both Uploader and Verifier tasks.
    Therefore, the logfile that we Upload to is the same file that is verified (filename queried for verification).

    Waits for same-host Agent to be up and running (by watching for local agent.pid/log files).
    Then writes to a Json file which is picked up by Agent.
    Finally, queries Scalyr backend to condfirm Json file was uploaded.
    """
    VERIFIER_TYPE = 'Standalone'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._logfile = kwargs.get('monitored_logfile')
        self._python_version = kwargs.get('python_version')

    def is_verifier(self):
        return True

    def is_uploader(self):
        return True

    def _get_uploader_output_streams(self):
        """Returns stream to write log data into"""
        return [open(self._logfile, 'w+')]

    def _get_uploader_stream_names(self):
        """Returns stream to read log data from"""
        return [self._logfile]

    def _make_log_line(self, count, stream):
        """Return a line of JSON for data.json (which is uploaded by the Agent)"""
        obj = {
            "verifier_type": self.VERIFIER_TYPE,
            "count": count,
            "hostname": self._localhostname,
            "python_version": 'python{}'.format(self._python_version),
            "line_stream": stream.name
        }
        return json.dumps(obj)

    def verify_agent_started_or_die(self):
        """Poll for agent pid and log file"""
        def _check_agent_pid_and_log_files():
            # If agent is not started, print agent.log if it exists
            agent_logfile = '/var/log/scalyr-agent-2/agent.log'
            agent_pid_file = '/var/log/scalyr-agent-2/agent.pid'
            if not os.path.isfile(agent_pid_file) or not os.path.isfile(agent_logfile):
                return False
            return True
        self.poll_until_max_wait(
            _check_agent_pid_and_log_files,
            'Checking for agent pid and log files',
            'Agent is running.',
            'No agent running.',
            poll_interval=1
        )

    def verify_logs_uploaded(self):
        """
        For standalone agent, confirmation of log upload impinges on successful poll
        of a single matching row as follows:

        python_version matches the standalone agent python version
        hostname matches the docker container hostname running the standalone agent
        """
        def _query_scalyr_for_monitored_log_upload():

            # TODO: This should be self._lines_to_upload (i.e. 1000, but it doesn't work
            # for logstash where for some reason only 300-600 lines are uploaded most
            # of the time.  Once that bug is fixed, change this back to self._lines_to_upload
            expected_count = 1000

            resp = requests.get(self._make_query_url({
                '$verifier_type': self.VERIFIER_TYPE,
                '$python_version': 'python{}'.format(self._python_version),
                '$hostname': self._localhostname,
                '$count': expected_count,
            }))

            if resp.ok:
                data = json.loads(resp.content)
                if not 'matches' in data:
                    return False
                matches = data['matches']
                if len(matches) == 0:
                    return False
                att = matches[0]['attributes']
                verifier_type = att['verifier_type']
                python_version = att['python_version']
                hostname = att['hostname']
                cnt = att['count']
                if all([
                    verifier_type == self.VERIFIER_TYPE,
                    python_version == 'python{}'.format(self._python_version),
                    hostname == self._localhostname,
                    cnt == expected_count
                ]):
                    return True
            return False

        self.poll_until_max_wait(
            _query_scalyr_for_monitored_log_upload,
            'Querying server to verify monitored logfile was uploaded.',
            'Monitored logfile upload verified',
            'Monitored logfile upload not verified',
            exit_on_success=True,
            exit_on_fail=True,
        )


class DockerSmokeTestActor(SmokeTestActor):
    """
    Base Docker actor.

    Some containers will write logs to Scalyr but only one container will verify.
    (The current setup has only one uploader + one verifier)

    Because there are multiple processes (containers) running, it is necessary to synchronize them for the Smoketest
    to correctly work.

    Upload / Verify will not begin until the remote agent is confirmed to be up and running.  This is done by querying
    Scalyr.

    For clarity/maintainability of the Upload/Verifier code, an actor should only upload or verify, not both.  (This is
    different from the Standalone actor where a single process runs both upload and verify and checks the local agent
    via file system).
    """
    def __init__(self, **kwargs):
        """
        :param max_wait: Max seconds before exiting
        :param mode: One of 'query', 'upload_and_ verify'
        """
        super().__init__(**kwargs)
        self.mode = kwargs.get('mode')
        self._logfile = '/docker/{}.log'.format(self._process_name)
        self._agent_hostname = kwargs.get('agent_hostname')
        self._uploader_hostname = kwargs.get('uploader_hostname')
        _pretty_print('Agent hostname="{}"'.format(self._agent_hostname))
        _pretty_print('Uploader hostname="{}"'.format(self._uploader_hostname))

    def is_verifier(self):
        return self.mode == NAME_SUFFIX_VERIFIER

    def is_uploader(self):
        return self.mode == NAME_SUFFIX_UPLOADER

    def _serialize_row(self, obj):
        """Write a single row of key=value, separated by commas. Standardize by sorting keys"""
        keyvals = [(key, obj.get(key)) for key in sorted(obj.keys())]
        return ','.join(['{}={}'.format(k, v) for k, v in keyvals])

    def _make_log_line(self, count, stream):
        return self._serialize_row({
            "verifier_type": self.VERIFIER_TYPE,
            "count": count,
            "line_stream": self._get_stream_name_from_stream(stream),
            # No need hostname in logline. The agent_container_id & remote-container-logfile name uniquely identify the
            # correct log.
            # "hostname": self._localhostname,
        })

    def _get_process_name_for_suffix(self, suffix):
        assert suffix in [
            NAME_SUFFIX_AGENT,
            NAME_SUFFIX_UPLOADER,
            NAME_SUFFIX_VERIFIER,
        ]
        parts = self._process_name.split('-')[:-1]
        parts.append(suffix)
        return '-'.join(parts)

    def _get_stream_name_from_stream(self, stream):
        return stream.name[1:-1]

    def _get_uploader_output_streams(self):
        return [sys.stderr, sys.stdout]

    def _get_uploader_stream_names(self):
        """Docker and k8s subclasses all verify by querying stream names of 'stderr' and 'stdout'"""
        return [stream.name[1:-1] for stream in [sys.stderr, sys.stdout]]

    def verify_agent_started_or_die(self):
        """
        Docker agent is not running in same container as Verifier.
        Verifier must query Scalyr to determine presence of these 2 files:
        serverHost=<agent_short_container_id>, logfile=/var/log/scalyr-agent-2/agent.log
        serverHost=<agent_short_container_id>, logfile=/var/log/scalyr-agent-2/docker_monitor.log
        filter="Starting monitor docker_monitor()"
        """
        def _query_scalyr_for_agent_logfile(logfile):
            def _func():
                resp = requests.get(self._make_query_url(
                    override_serverHost=self._agent_hostname,
                    override_log=logfile,
                ))
                if resp.ok:
                    data = json.loads(resp.content)
                    if not 'matches' in data:
                        return False
                    matches = data['matches']
                    if len(matches) == 0:
                        return False
                    return True
                return False
            return _func

        for filename in self._get_expected_agent_logfiles():
            self.poll_until_max_wait(
                _query_scalyr_for_agent_logfile(filename),
                'Check if Agent is running: query scalyr for agent container file: {}'.format(filename),
                '{} found'.format(filename),
                'Time limit reached.  Could not verify liveness of Agent Docker Container.',
                exit_on_success=False,
                exit_on_fail=True,
            )

    def _get_expected_agent_logfiles(self):
        return ['/var/log/scalyr-agent-2/agent.log', '/var/log/scalyr-agent-2/docker_monitor.log']

    def _get_uploader_override_logfilename_regex(self, process_name):
        """All logfile filters are exact and therefore we return None in the general case"""
        return None

    def _get_mapped_logfile_prefix(self):
        raise NotImplementedError

    def _get_extra_query_attributes(self, stream_name, process_name):
        """Dictionary of query field key-vals (besides serverHost, logfile, filters)"""
        raise NotImplementedError

    def _verify_queried_attributes(self, att, stream_name, process_name):
        if att.get('containerName') != process_name:
            return False
        return True

    def verify_logs_uploaded(self):
        """
        For docker agent, confirmation requires verification that all uploaders were able to uploaded.
        There are 2 separate types of containers.
         1. uploader: uploads data to Scalyr (can easily support multiple but for now, just 1)
         2. verifier: verifies data was uploaded by uploader
        """
        def _query_scalyr_for_upload_activity(contname_suffix, stream_name):
            def _func():
                process_name = self._get_process_name_for_suffix(contname_suffix)
                resp = requests.get(self._make_query_url(
                    self._get_extra_query_attributes(stream_name, process_name),
                    override_serverHost=self._agent_hostname,
                    override_log='{}/{}.log'.format(self._get_mapped_logfile_prefix(), process_name),
                    override_log_regex=self._get_uploader_override_logfilename_regex(process_name),
                    message=self._serialize_row({
                        "verifier_type": self.VERIFIER_TYPE,
                        "count": self._lines_to_upload,
                        "line_stream": stream_name,
                    }),
                ))
                if resp.ok:
                    data = json.loads(resp.content)
                    if not 'matches' in data:
                        return False
                    matches = data['matches']
                    if len(matches) == 0:
                        return False
                    att = matches[0]['attributes']
                    return self._verify_queried_attributes(att, stream_name, process_name)

                return False  # Non-ok response
            return _func

        suffixes_to_check = [NAME_SUFFIX_UPLOADER]
        for count, suffix in enumerate(suffixes_to_check):
            for stream_name in self._get_uploader_stream_names():
                self.poll_until_max_wait(
                    _query_scalyr_for_upload_activity(suffix, stream_name),
                    "Querying server to verify upload: container[stream]='{}[{}].".format(
                        self._get_process_name_for_suffix(suffix), stream_name
                    ),
                    'Upload verified for {}[{}].'.format(suffix, stream_name),
                    'Upload not verified for {}[{}].'.format(suffix, stream_name),
                    exit_on_success = count == len(suffixes_to_check),
                    exit_on_fail = True,
                )


class DockerJsonActor(DockerSmokeTestActor):
    """These subclasses capture differences between JSON and Syslog implementations"""

    VERIFIER_TYPE = 'Docker JSON'

    def _get_mapped_logfile_prefix(self):
        return '/docker'

    def _get_extra_query_attributes(self, stream_name, process_name):
        return {'$stream': stream_name}

    def _verify_queried_attributes(self, att, stream_name, process_name):
        if not super()._verify_queried_attributes(att, stream_name, process_name):
            return False
        if not all([
            att.get('stream') in stream_name,
            att.get('monitor') == 'agentDocker'
        ]):
            return False
        return True


class DockerSyslogActor(DockerSmokeTestActor):

    VERIFIER_TYPE = 'Docker Syslog'

    def _get_extra_query_attributes(self, stream_name, process_name):
        return {}

    def _get_mapped_logfile_prefix(self):
        return '/var/log/scalyr-agent-2/containers'

    def _verify_queried_attributes(self, att, stream_name, process_name):
        if not super()._verify_queried_attributes(att, stream_name, process_name):
            return False
        if not all([
            att.get('monitor') == 'agentSyslog',
            att.get('parser') == 'agentSyslogDocker'
        ]):
            return False
        return True


class K8sActor(DockerSmokeTestActor):
    """
    Uploaders write to std output/error
    Verifiers query for 'stdout', 'stderr'
    """

    VERIFIER_TYPE = 'Kubernetes'

    def _get_expected_agent_logfiles(self):
        return ['/var/log/scalyr-agent-2/agent.log', '/var/log/scalyr-agent-2/kubernetes_monitor.log']

    def _get_mapped_logfile_prefix(self):
        return '/docker'

    def _get_extra_query_attributes(self, stream_name, process_name):
        return {'$stream': stream_name}

    def _verify_queried_attributes(self, att, stream_name, process_name):
        """
        Here's example JSON response for k8s

        "matches": [
            {
                "severity": 3,
                "session": "log_session_5645060384390470634",
                "attributes": {
                    "pod_namespace": "default",
                    "scalyr-category": "log",
                    "stream": "stderr",
                    "pod_uid": "f2d1d738-9a0c-11e9-9b04-080027029126",
                    "pod-template-hash": "76bcb9cf9",
                    "run": "ci-agent-k8s-7777-uploader",
                    "monitor": "agentKubernetes",
                    "k8s_node": "minikube",
                    "serverHost": "scalyr-agent-2-z5c8l",
                    "container_id": "6eb4215ac1589de13089419e90cdfe08c01262e6cfb821f18061a63ab4188a87",
                    "raw_timestamp": "2019-06-29T03:16:28.058676421Z",
                    "pod_name": "ci-agent-k8s-7777-uploader-76bcb9cf9-cb96t"
                },
                "thread": "default",
                "message": "count=1000,line_stream=<stderr>,verifier_type=Kubernetes\n",
                "timestamp": "1561778193736899060"
            }
        ],
        """
        if not all([
            att.get('stream') in stream_name,
            att.get('monitor') == 'agentKubernetes',
            process_name in att.get('pod_name'),
        ]):
            return False
        return True

    def _get_uploader_override_logfilename_regex(self, process_name):
        """For k8s, return a logfile regex because it too difficult to construct an exact logfile filter.

        The regex clause becomes: $logfile+matches+"/docker/k8s_ci-agent-k8s-7777-uploader.*"
        """
        return '{}/k8s_{}*'.format(self._get_mapped_logfile_prefix(), process_name)



class LogstashActor(DockerSmokeTestActor):
    """
    Uploader writes to a common shared logfile that is bind-mounted in a shared volume (not local disk)
    Verifier reads from common shareed logfile
    """

    VERIFIER_TYPE = 'Logstash'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._monitored_logfile = kwargs.get('monitored_logfile')

    def _get_uploader_output_streams(self):
        """Returns stream for Uploader to write log data into"""
        return [open(self._monitored_logfile, 'w+')]

    def _get_uploader_stream_names(self):
        """Returns stream to read log data from"""
        return [self._monitored_logfile]

    def _get_stream_name_from_stream(self, stream):
        return stream.name

    def _get_expected_agent_logfiles(self):
        return ['scalyr_logstash.log']

    def _get_mapped_logfile_prefix(self):
        return '/logstash'

    def _get_extra_query_attributes(self, stream_name, process_name):
        # {'$stream': stream.name}
        # no server-side parser has been defined so cannot filter on $stream
        return {}

    def _verify_queried_attributes(self, att, stream_name, process_name):
        if not all([
            # att.get('stream') in stream.name,  # we haven't setup server-side parser so $stream is not available
            # Since the input streams are locally mounted, the event origins are all the same as the agent hostname
            att.get('origin') == self._agent_hostname,
            # the following fields are added on in the logstash pipeline config
            # and should appear in every event
            att.get('output_attribute1') == 'output_value1',
            att.get('output_attribute2') == 'output_value2',
            att.get('output_attribute3') == 'output_value3',
            # TODO: adjust if these are eventually split into "booleans"a
            att.get('tags') == '[tag_t1, tag_t2]',
        ]):
            return False
        return True

    def _get_uploader_override_logfilename_regex(self, process_name):
        """For logstash setup, the input is a local file mounted to the logstash container, hence the fields are
        host=container_id, path=/tmp/ci-plugin-logstash-7778-uploader.log
        host/path are mapped to origin/logfile
        """
        return self._monitored_logfile


# Select verifier class based on containers name (prefix)
CONTAINER_PREFIX_2_VERIFIER_CLASS = {
    'ci-agent-standalone': StandaloneSmokeTestActor,
    'ci-agent-docker-json': DockerJsonActor,
    'ci-agent-docker-syslog': DockerSyslogActor,
    'ci-agent-k8s': K8sActor,
    'ci-plugin-logstash': LogstashActor,
}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('process_name', type=str,
                        help="name of process running this instance of test code. Prefix should be a key in "
                             "CONTAINER_PREFIX_2_VERIFIER_CLASS so that the correct verifier can be chosen.")
    parser.add_argument('max_wait', type=int, help="max seconds this test will run (will force-quit)")

    # Generic param that can be used by any test as needed
    parser.add_argument('--mode', type=str, help="mode switch", choices=NAME_SUFFIXES)

    # For connecting to Scalyr.  Note that we need not supply SCALYR_API_KEY as the Agent gets it from it's own config
    # or the environment.
    parser.add_argument('--scalyr_server', type=str,
                        help="Scalyr backend server (required by Agent or Verifier containers)")
    parser.add_argument('--read_api_key', type=str, help="read api key (required all Verifier containers)")

    # For Standalone testing
    parser.add_argument('--monitored_logfile', type=str,
                        help="absolute path of data file to write to (must match Agent config).  "
                             "Logstash producers also write to this, which are then picked up by the Logstash agent.")
    parser.add_argument('--python_version', type=str,
                        help="python version agent is running on (will be added into generated test data)")

    # For Docker testing
    parser.add_argument('--agent_hostname', type=str,
                        help="hostname of Agent container (required by Docker/k8s Verifier containers")
    parser.add_argument('--uploader_hostname', type=str,
                        help="hostname of Uploader container (required by Docker/k8s Verifier containers")
    parser.add_argument('--debug', type=str, help="turn on debugging")
    args = parser.parse_args()

    klass = None
    for key, val in CONTAINER_PREFIX_2_VERIFIER_CLASS.items():
        if args.process_name.startswith(key):
            klass = CONTAINER_PREFIX_2_VERIFIER_CLASS.get(key)
            break

    # Display args to stdout, redacting sensitive keys
    _pretty_print('Launching actor', message='Class={}'.format(klass))
    if not klass:
        _exit(1, message='Bad test config: process_name must start with one of {}'.format(
            CONTAINER_PREFIX_2_VERIFIER_CLASS.keys())
        )

    actor = klass(**vars(args))

    # Optionally start upload in a separate thread.  Verifiers should not upload.
    uploader_thread = None
    if actor.is_uploader():
        _pretty_print('START UPLOAD', actor._process_name)
        uploader_thread = threading.Thread(target=actor.trigger_log_upload, args=())
        uploader_thread.start()

    if actor.is_verifier():
        _pretty_print('START VERIFIER', actor._process_name)
        actor.verify_or_die()

    # If verify_or_die hasn't force-killed the program, wait for uploader to finish
    if uploader_thread:
        uploader_thread.join()
