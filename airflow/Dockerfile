# ═══════════════════════════════════════════════════════════
# Corpus — Airflow Dockerfile
# ═══════════════════════════════════════════════════════════

FROM apache/airflow:3.0.1-python3.12

USER root

# Install system deps for Docling and PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Install Python dependencies
COPY requirements-airflow.txt /opt/airflow/requirements-airflow.txt
RUN pip install --no-cache-dir -r /opt/airflow/requirements-airflow.txt

# Copy DAGs, plugins, and application source
COPY dags /opt/airflow/dags
COPY plugins /opt/airflow/plugins
COPY entrypoint.sh /opt/airflow/entrypoint.sh

USER root
RUN chmod +x /opt/airflow/entrypoint.sh

USER airflow

EXPOSE 8080

ENTRYPOINT ["/opt/airflow/entrypoint.sh"]
