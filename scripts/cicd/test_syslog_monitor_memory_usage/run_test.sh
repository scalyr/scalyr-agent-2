#! /bin/bash

TCP_SERVERS=$1
UDP_SERVERS=$2
INTERVAL=$3

echo_with_date() {
    date +"[%Y-%m-%d %H:%M:%S] $*"
}

function generate_config() {
  TCP_SERVERS=$1
  UDP_SERVERS=$2

  echo "{" > agent.json

  echo '
"import_vars": ["SCALYR_API_KEY"],
"scalyr_server": "agent.scalyr.com",
"api_key": "$SCALYR_API_KEY",
"log_rotation_max_bytes": "1073741824",
"syslog_udp_socket_request_queue_size": "100000",

"server_attributes": {
   "serverHost": "github-action-memory-test"

},' >> agent.json

echo "\"monitors\": [" >> agent.json

for N in `seq $TCP_SERVERS`;
do
  echo "{
      \"module\":                    \"scalyr_agent.builtin_monitors.syslog_monitor\",
      \"protocols\":                 \"tcp:$(($N+1600))\",
      \"accept_remote_connections\": \"true\",
      \"message_log\": \"tcp_$N.log\"
    }," >> agent.json
done

for N in `seq $UDP_SERVERS`;
do
  echo "{
      \"module\":                    \"scalyr_agent.builtin_monitors.syslog_monitor\",
      \"protocols\":                 \"udp:$(($N+1500))\",
      \"accept_remote_connections\": \"true\",
      \"message_log\": \"udp_$N.log\"
    }," >> agent.json
done

echo "]" >> agent.json

  echo "}" >> agent.json
}

generate_config $TCP_SERVERS $UDP_SERVERS

CONFIG_FILE=agent.json
python scalyr_agent/agent_main.py --config $CONFIG_FILE start


RATE=2000
MONITOR_INTERVAL=5
MEM_ALLOWED=$((256*1024*$UDP_SERVERS)) # 256Mb per UDP server

pids=()
for N in `seq $TCP_SERVERS`;
do
	loggen --rate $(($RATE/$TCP_SERVERS)) --interval $INTERVAL --stream --active-connections=5 -Q localhost $(($N+1600)) &
	pids+=($!)
done

for N in `seq $UDP_SERVERS`;
do
	loggen --rate $(($RATE/$UDP_SERVERS)) --interval $INTERVAL --dgram --active-connections=5 -Q localhost $(($N+1500)) &
	pids+=($!)
done

PID=`cat ~/scalyr-agent-dev/log/agent.pid`

while ps -p $pids > /dev/null; do
  MEM_USED=`cat /proc/$PID/status | grep VmRSS | awk '{print $2}'`
  if [ $MEM_USED -gt $MEM_ALLOWED ]
  then
    echo_with_date "Mem used: $MEM_USED kB > $MEM_ALLOWED kB => FAIL!"
    exit 1
  else
    echo_with_date "Mem used: $MEM_USED kB <= $MEM_ALLOWED kB => OK"
  fi
  sleep $MONITOR_INTERVAL
done

echo Waiting for loggen processes to finish ...
for pid in ${pids[*]}; do
  wait $pid
done


