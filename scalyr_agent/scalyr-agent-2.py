import os
import sys
import win32serviceutil

from scalyr_agent.platform_controller import PlatformController
from scalyr_agent.agent_main import ScalyrAgent, create_commandline_parser

from scalyr_agent.platform_windows import ScalyrAgentService

from scalyr_agent.builtin_monitors import windows_process_metrics, windows_system_metrics, test_monitor


if __name__ == '__main__':
    my_controller = PlatformController.new_platform()
    parser = create_commandline_parser()
    my_controller.add_options(parser)

    (options, args) = parser.parse_args()

    my_controller.consume_options(options)
    if len(args) < 1:
        print >> sys.stderr, 'You must specify a command, such as "start", "stop", or "status".'
        parser.print_help(sys.stderr)
        sys.exit(1)
    elif len(args) > 1:
        print >> sys.stderr, 'Too many commands specified.  Only specify one of "start", "stop", "status".'
        parser.print_help(sys.stderr)
        sys.exit(1)
    elif  args[0].lower() in ('install', 'remove', 'debug'):
        sys.exit(win32serviceutil.HandleCommandLine(ScalyrAgentService))
    elif args[0].lower() in ('update'):
        #sys.exit(update_product())
        raise NotImplementedError, "Functionality not yet implemented"
    elif args[0] not in ('start', 'stop', 'status', 'restart', 'condrestart', 'version'):
        print >> sys.stderr, 'Unknown command given: "%s"' % args[0]
        parser.print_help(sys.stderr)
        sys.exit(1)

    if options.config_filename is not None and not os.path.isabs(options.config_filename):
        options.config_filename = os.path.abspath(options.config_filename)
    sys.exit(ScalyrAgent(my_controller).main(options.config_filename, args[0], options))
