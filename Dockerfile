ARG AIRFLOW_VERSION=2.8.1
ARG PYTHON_VERSION=3.11
FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

USER root

RUN mkdir -p /ms-playwright \
    && chown -R airflow:0 /ms-playwright \
    && chmod -R g+rwX /ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

ARG AIRFLOW_VERSION=2.8.1
ARG PYTHON_VERSION=3.11
COPY requirements-airflow.txt /requirements-airflow.txt
COPY requirements-browser.txt /requirements-browser.txt

RUN pip install --no-cache-dir \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt" \
    -r /requirements-airflow.txt

RUN pip install --no-cache-dir -r /requirements-browser.txt

USER root

RUN PYTHONPATH=/home/airflow/.local/lib/python${PYTHON_VERSION}/site-packages \
    /home/airflow/.local/bin/playwright install-deps chromium

USER airflow

RUN /home/airflow/.local/bin/playwright install chromium
