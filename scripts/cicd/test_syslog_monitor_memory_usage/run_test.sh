#! /bin/bash

cat scripts/cicd/test_syslog_monitor_memory_usage/agent.json | envsubst > agent.json
python scalyr_agent/agent_main.py --config agent.json start

pids=()
for PORT in 1601 1602 1603 1604;
do
	loggen --rate 1000 --interval 60 --stream --active-connections=5 -Q localhost $PORT &
	pids+=($!)
done


echo Waiting for loggen processes to finish ...
for pid in ${pids[*]}; do
  wait $pid
done

MEM_ALLOWED=$((1*1024*1024)) #1Gb

PID=`cat ~/scalyr-agent-dev/log/agent.pid`
MEM_USED=`cat /proc/$PID/status | grep VmRSS | awk '{print $2}'`

python scalyr_agent/agent_main.py --config agent.json stop

if [ $MEM_USED -gt $MEM_ALLOWED ]
then
  echo "Mem used: $MEM_USED kB > $MEM_ALLOWED kB => FAIL!"
  exit 1
else
  echo "Mem used: $MEM_USED kB <= $MEM_ALLOWED kB => OK"
fi
