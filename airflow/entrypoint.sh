#!/bin/bash
set -e

echo "═══════════════════════════════════════════"
echo " Corpus — Airflow Initialization"
echo "═══════════════════════════════════════════"

# Initialize the Airflow database
echo "» Initializing Airflow database..."
airflow db migrate

# Start the scheduler in the background
echo "» Starting Airflow scheduler..."
airflow scheduler &

# Start the DAG processor in the background (required by Airflow 3.0+)
echo "» Starting Airflow dag-processor..."
airflow dag-processor &

# Start the API server (web UI) in the foreground
echo "» Starting Airflow api-server on port 8080..."
exec airflow api-server --port 8080
