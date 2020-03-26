FROM scalyr-agent-testings-monitor-base

WORKDIR /

CMD service mysql start && mysql < /agent_source/tests/images_builder/monitors/mysql/init.sql && sleep 99999