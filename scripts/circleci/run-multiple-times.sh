#!/usr/bin/env bash

# Utility script which runs provided command multiple times and records success
# / failure for each run.
# We assume success if the command exit code is 0, failure otherwise.

COMMAND_TO_RUN=$1
ITERATIONS_TO_RUN=${ITERATIONS_TO_RUN:-"2"}

# How long to sleep after each command run
SLEEP_DELAY=${SLEEP_DELAY:-"5"}

set +e

total_runs=0
successful_runs=0
failed_runs=0

echo ""
echo "Running command '${COMMAND_TO_RUN}' for ${ITERATIONS_TO_RUN} iterations"
echo ""

for (( i=1; i<=ITERATIONS_TO_RUN; i++ )); do
    echo ""
    echo "Running command, iteration: ${i}"
    echo ""

    start_ts=$(date +%s)
    bash -c "${COMMAND_TO_RUN}"
    exit_code=$?
    end_ts=$(date +%s)

    run_duration=$((end_ts-start_ts))

    echo "Run ${i} completed, duration: ${run_duration} seconds"

    if [ "${exit_code}" -eq 0 ]; then
        successful_runs=$((successful_runs+1))
        echo ""
        echo "Run ${i} status: success"
    else
        failed_runs=$((failed_runs+1))
        echo ""
        echo "Run ${i} status: failure"
    fi

    total_runs=$((total_runs+1))

    echo ""
    echo "Current partial run status"
    echo "Total runs: ${total_runs}, successes: ${successful_runs}, failures: ${failed_runs}"
    echo ""

    if [ "${i}" -lt "${ITERATIONS_TO_RUN}" ]; then
        echo ""
        echo "Sleeping ${SLEEP_DELAY} before next run..."
        sleep "${SLEEP_DELAY}"
    fi
done

echo ""
echo "Status after ${total_runs} of command runs"
echo "Successful runs: ${successful_runs}"
echo "Failed runs: ${failed_runs}"

set -e

# We exit with 0 if there were no failures during all the runs
if [ "${failed_runs}" -eq 0 ]; then
    exit 0
fi

exit 2
