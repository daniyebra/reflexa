FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY reflexa/ reflexa/
COPY ui/ ui/
COPY scripts/ scripts/

RUN pip install --no-cache-dir -e "."

RUN mkdir -p /app/data
