import json

log_path = "/opt/airflow/logs/dag_id=daily_arxiv_ingestion/run_id=manual__2026-07-11T08:43:37.515702+00:00_LA4nJzyW/task_id=fetch_and_parse_chunk_index/attempt=1.log"

try:
    with open(log_path) as f:
        lines = f.readlines()
except Exception as e:
    print(f"Could not open log file: {e}")
    exit(1)

count = 0
for line in lines:
    if not line.strip():
        continue
    try:
        data = json.loads(line)
        timestamp = data.get("timestamp")
        level = data.get("level")
        event = data.get("event")
        event_str = event if len(event) <= 100 else event[:100] + "..."
        print(f"{timestamp} | {level.upper():5} | {event_str}")
        count += 1
    except Exception:
        pass
print(f"Total lines parsed: {count}")
