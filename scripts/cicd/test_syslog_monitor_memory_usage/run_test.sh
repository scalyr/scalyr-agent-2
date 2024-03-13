#! /bin/bash

echo_with_date() {
    date +"[%Y-%m-%d %H:%M:%S] $*"
}

cat scripts/cicd/test_syslog_monitor_memory_usage/agent.json | envsubst > agent.json
python scalyr_agent/agent_main.py --config agent.json start

INTERVAL=120
MEM_ALLOWED=$((1*1024*1024)) #1Gb

pids=()
for PORT in 1601 1602 1603 1604;
do
	loggen --rate 1000 --interval $INTERVAL --stream --active-connections=5 -Q localhost $PORT &
	pids+=($!)
done

PID=`cat ~/scalyr-agent-dev/log/agent.pid`

for A in `seq $INTERVAL`; do
  MEM_USED=`cat /proc/$PID/status | grep VmRSS | awk '{print $2}'`
  if [ $MEM_USED -gt $MEM_ALLOWED ]
  then
    echo_with_date "Mem used: $MEM_USED kB > $MEM_ALLOWED kB => FAIL!"
  #  exit 1
  else
    echo_with_date "Mem used: $MEM_USED kB <= $MEM_ALLOWED kB => OK"
  fi
  sleep 10
done

echo Waiting for loggen processes to finish ...
for pid in ${pids[*]}; do
  wait $pid
done
