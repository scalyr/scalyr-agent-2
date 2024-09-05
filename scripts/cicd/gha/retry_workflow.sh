WORKFLOW_NAME=$1

populate_workflow_status_json() {
  WORKFLOW_STATUS_JSON=`gh run list --json status,workflowName,number,createdAt,databaseId,conclusion --jq "map(select(.workflowName == \"$WORKFLOW_NAME\"))[0]"`
}

populate_workflow_status_json
RUN_ID="`echo $WORKFLOW_STATUS_JSON | jq '.databaseId'`"

for X in `seq 480`;
do
    populate_workflow_status_json
	  echo $WORKFLOW_STATUS_JSON

    if [ "$(echo $WORKFLOW_STATUS_JSON | jq '.status')" = "\"completed\"" ]; then
      if [ "$(echo $WORKFLOW_STATUS_JSON | jq '.conclusion')" = "\"success\"" ]; then
      	echo Success
        break
      else
        echo Rerunning $RUN_ID
        gh run rerun $RUN_ID --failed
      fi
    else
      echo "Waiting for $RUN_ID to finish .."
    fi

    sleep 30
done


