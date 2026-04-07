FROM scalyr-agent-testings-monitor-base

COPY nginx-config /etc/nginx/sites-available/default
COPY init.sql /init.sql
COPY dummy-flask-server.py /dummy-flask-server.py
COPY agent_source /agent_source

WORKDIR /
