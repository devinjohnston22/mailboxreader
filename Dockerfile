# syntax=docker/dockerfile:1
FROM python:3.12.14-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca,target=/run/proxy-ca,required=false \
    if [ -f /run/proxy-ca ]; then PIP_CERT=/run/proxy-ca pip install --no-cache-dir -r requirements.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi
COPY --chown=10001:10001 mailboxreader ./mailboxreader
COPY --chown=10001:10001 migrations ./migrations
COPY --chown=10001:10001 scripts ./scripts
COPY --chown=10001:10001 dashboards ./dashboards
RUN chmod -R a+rX /app/mailboxreader /app/migrations /app/scripts /app/dashboards \
    && useradd --uid 10001 --create-home app
USER 10001
CMD ["sh", "-c", "python -m mailboxreader.db && exec uvicorn mailboxreader.api:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log"]
