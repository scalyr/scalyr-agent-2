FROM scalyr-agent-testings-monitor-base

ADD nginx-config /etc/nginx/sites-available/default
ADD init.sql /init.sql
ADD dummy-flask-server.py /dummy-flask-server.py
ADD agent_source /agent_source

WORKDIR /
