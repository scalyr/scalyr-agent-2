/// DECLARE path=/help/monitors/apache
/// DECLARE title=Apache Monitor
/// DECLARE section=help
/// DECLARE subsection=monitors

# Apache Monitor

The Apache monitor allows you to collect data about the usage and performance of your Apache server.

Each monitor can be configured to monitor a specific Apache instance, thus allowing you to configure alerts and the
dashboard entries independently (if desired) for each instance.

## Configuring Apache

This plugin monitor uses the Apache server status module to gather its metrics.  Therefore, your Apache server must be
configured to enable the module and serve requests to it.  In this section, we will give you some instructions on
how to do this.  You may also consult 
[Apache's instructions on how to use the status module](http://httpd.apache.org/docs/2.2/mod/mod_status.html) for
further information.

First, you must verify that the module is enabled for your Apache server.  How you verify this will vary based on the
operating system the server is running on and the version of Apache being used.  For example, for Linux systems, you
can check to see if the module is enabled by invoking this command:

    ls /etc/apache2/mods-enabled

If you see ``status.conf`` and ``status.load`` present, the module is enabled.  If it is not enabled, you
can enabled it for Linux systems by executing the following command:

    sudo /usr/sbin/a2enmod status

Note, that you must restart your Apache server for any changes to the modules to take affect.

The process for enabling the module will vary from platform to
platform.  Additionally, if Apache was compiled manually, the module may or may not be available.  Consult the
documentation for your particular platform.  As some examples, here are links to the documentation for
[CentOS 5/RHEL 5](https://www.centos.org/docs/5/html/5.1/Deployment_Guide/s1-apache-addmods.html), 
[Ubuntu 14.04](https://help.ubuntu.com/14.04/serverguide/httpd.html),
[Windows](http://httpd.apache.org/docs/2.0/platform/windows.html#cust).

After the module is enabled, the next step is to configure a URL from which the server status will be served.
In general, this means updating the ``VirtualHost`` configuration section of your Apache server.  How you determine
which file contains this configuration will depend on your system and your site's individual set up.  For
example, for Linux systems, the ``/etc/apache2/sites-available`` directory typically contains the file with the
necessary configuration.

To enable the status module, add the following to the ``VirtualHost`` configuration section (between ``<VirtualHost>``
 and ``</VirtualHost>``):

    <Location /server-status>
       SetHandler server-status
       Order deny,allow
       Deny from all
       Allow from 127.0.0.1
    </Location>

This block does a couple of very important things.  First, it specifies that the status page will be exposed on the
local server at ``http://<address>/server-status``.  The next three statements work together and are probably the most
important for security purposes.  ``Order allow,deny`` tells Apache how to check things to grant access.
``Deny from all`` is a blanket statement to disallow access by everyone.  ``Allow from 127.0.0.1`` tells Apache to
allow access to the page from localhost.

Once you make the configuration change, you will need to restart Apache.  For Linux systems, you may do this by
executing:

    sudo service apache2 restart

## Configuring the Scalyr Apache Monitor

The Apache monitor is included with the Scalyr agent.  In order to configure it, you will need to add its monitor
configuration to the Scalyr agent config file.

A basic Apache monitor configuration entry might resemble:

    monitors: [
      {
          module: "scalyr_agent.builtin_monitors.apache_monitor",
      }
    ]

If you were running an instances of Apache on a non-standard port (say 8080), your config might resemble:

    monitors: [
      {
          module: "scalyr_agent.builtin_monitors.apache_monitor",
          status_url: "http://localhost:8080/server-status"
          id: "customers"
      }
    ]

Note the "id" field in the configurations.  This is an optional field that allows you to specify an identifier specific
to a particular instance of Apache and will make it easier to filter on metrics specific to that instance.
    
## Configuration reference

The table below describes the options that can be used to configure the Apache monitor.

|||# Option            ||| Usage
|||# ``module``        ||| Always ``scalyr_agent.builtin_monitors.apache_monitor``
|||# ``status_url``    ||| Optional (defaults to 'http://localhost/server-status/?auto').  The URL the monitor will \
                           fetchto retrieve the Apache status information.
|||# ``source_address``||| Optional (defaults to '127.0.0.1'). The IP address to be used as the source address when \
                           fetching the status URL.  Many servers require this to be 127.0.0.1 because they only \
                           server the status page to requests from localhost.
|||# ``id``            ||| Optional (defaults to empty string).  Included in each log message generated by this \
                           monitor, as a field named ``instance``. Allows you to distinguish between different Apache \
                           instances running on the same server.

## Log reference

Each event recorded by this plugin will have the following fields:

|||# Field       ||| Meaning
|||# ``monitor`` ||| Always ``apache_monitor``.
|||# ``metric``  ||| The metric name.  See the metric tables for more information.
|||# ``value``   ||| The value of the metric.
|||# ``instance``||| The ``id`` value from the monitor configuration.

## Metric reference

The table below describes the metrics recorded by the Apache monitor.

|||# Metric                         ||| Description
|||# ``apache.connections.active``  ||| The number of connections currently opened to the server.
|||# ``apache.connections.writing`` ||| The number of connections currently writing to the clients.
|||# ``apache.connections.idle``    ||| The number of connections currently idle/sending keep alives.
|||# ``apache.connections.closing`` ||| The number of connections currently closing.
|||# ``apache.workers.active``      ||| How many workers are currently active.
|||# ``apache.workers.idle``        ||| How many of the workers are currently idle.
