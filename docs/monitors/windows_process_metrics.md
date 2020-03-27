/// DECLARE path=/help/monitors/windows-process-metrics
/// DECLARE title=Windows Process Metrics
/// DECLARE section=help
/// DECLARE subsection=monitors

# Windows Process Metrics

This agent monitor plugin records CPU consumption, memory usage, and other metrics for a specified process
on a Windows system.  You can use this plugin to record resource usage for a web server, database, or other application.

@class=bg-warning docInfoPanel: An *agent monitor plugin* is a component of the Scalyr Agent. To use a plugin,
simply add it to the ``monitors`` section of the Scalyr Agent configuration file
(``C:\Program Files (x86)\Scalyr\config\agent.json`).
For more information, see [Agent Plugins](/help/scalyr-agent#plugins).


## Sample Configuration

Here is a simple configuration fragment showing use of the windows_process_metrics plugin. This sample will record
resource usage for any process whose command line contains a match for the regular expression ``java.*tomcat6``:

    monitors: [
      {
         module:      "scalyr_agent.builtin_monitors.windows_process_metrics",
         id:          "tomcat",
         commandline: "java.*tomcat6",
      }
    ]

To record information for more than one process, use several copies of the windows_process_metrics plugin in
your configuration.


## Viewing Data

After adding this plugin to the agent configuration file, wait one minute for data to begin recording. Then
click the {{menuRef:Dashboards}} menu and select {{menuRef:Windows Process Metrics}}. (The dashboard will not be
listed until the agent begins sending data.)

You'll have to edit the dashboard file for each ``id`` value you've used. From the dashboard page, click the
{{menuRef:Edit Dashboard}} link. Look for the following bit of code, near the top of the file:

      // On the next line, list each "id" that you've used in a windows_process_metrics
      // clause in the Scalyr Agent configuration file (agent.json).
      values: [ "agent" ]

Edit the ``values`` list according to the list of ids you've used. For instance, if you've used "tomcat"
(as in the example above), the list would look like this:

      values: [ "agent", "tomcat" ]

The "agent" ID is used to report metrics for the Scalyr Agent itself.

You can now return to the dashboard. Use the dropdowns near the top of the page to select the host and process
you'd like to view.

<!-- Auto generated content below. DO NOT edit manually, but run tox -egenerate-monitor-docs command instead -->
