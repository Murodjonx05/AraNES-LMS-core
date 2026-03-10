FROM python:3.11-slim

WORKDIR /app/gateway_server

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash curl ca-certificates nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY gateway_server /app/gateway_server
COPY services /app/services

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/gateway_server/requirements.txt \
    && find /app/services -name run.sh -exec chmod +x {} +

ENV GATEWAY_PORT=8001

EXPOSE 8001

CMD ["sh", "-c", "exec uvicorn gateway:app --host 0.0.0.0 --port ${GATEWAY_PORT}"]
