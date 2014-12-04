import sys
from scalyr_agent import run_monitor

test_cmdline = [
    '-c',
    '{ pid: "$$" }',
    'scalyr_agent.builtin_monitors.windows_system_metrics',
    #'scalyr_agent.builtin_monitors.windows_process_metrics'
]


cmdline = sys.argv[1:] or test_cmdline
parser = run_monitor.create_parser()
options, args = parser.parse_args(cmdline)
print '-' * 78
print options
print args
print '-' * 78

rc = -1
sys.exit( 
    run_monitor.run_standalone_monitor(
        args[0], 
        options.monitor_python_path, 
        options.monitor_config, 
        options.monitor_sample_interval
    )
)
