gh run list --json status,workflowName,number,createdAt,databaseId,conclusion --jq 'map(select(.workflowName == "Build Linux Packages"))[0]'


RUN_ID="`echo $WF_JSON | jq '.databaseId'`"

for X in `seq 120`;
do
    WF_JSON="`gh run view $RUN_ID --json status,workflowName,number,createdAt,databaseId,conclusion --jq 'map(select(.workflowName == "Build Linux Packages"))[0]'`"
    if [ "`echo $WF_JSON | jq '.conclusion'`" = "\"success\"" ]; then
        break
    elif [ "`echo $WF_JSON | jq '.conclusion'`" = "\"failure\"" ]; then
        echo Rerunning $RUN_ID
        gh run rerun $RUN_ID --failed
    else
      echo "Waiting for $RUN_ID to finish .."
    fi

    sleep 60
done


