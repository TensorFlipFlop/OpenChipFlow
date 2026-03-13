#!/bin/bash
set -e

TOOL_DIR="$(dirname "$0")"
LOG_FILE="test_event_log.jsonl"
export OPENCHIPFLOW_EVENT_LOG="$LOG_FILE"

# Clean up
rm -f "$LOG_FILE"

echo "Testing Python API..."
python3 -c "
import sys
sys.path.append('${TOOL_DIR}')
from event_logger import EventLogger
import time

logger = EventLogger('test_role')
logger.start({'input1': '${TOOL_DIR}/event_logger.py'})
time.sleep(0.1)
logger.end(0, {'output1': '${TOOL_DIR}/event_logger.py'})
"

if [ ! -f "$LOG_FILE" ]; then
    echo "Error: Log file not created by Python API"
    exit 1
fi

echo "Python API test passed. Log content:"
cat "$LOG_FILE"
rm "$LOG_FILE"

echo "Testing CLI API..."
START_TIME=$(python3 "${TOOL_DIR}/event_logger.py" --role test_cli --event start --inputs input1="${TOOL_DIR}/event_logger.py")

if [ -z "$START_TIME" ]; then
    echo "Error: START_TIME empty"
    exit 1
fi

sleep 0.1

python3 "${TOOL_DIR}/event_logger.py" --role test_cli --event end --start-time "$START_TIME" --exit-code 0 --outputs output1="${TOOL_DIR}/event_logger.py"

if [ ! -f "$LOG_FILE" ]; then
    echo "Error: Log file not created by CLI API"
    exit 1
fi

echo "CLI API test passed. Log content:"
cat "$LOG_FILE"

rm "$LOG_FILE"
echo "All tests passed."
