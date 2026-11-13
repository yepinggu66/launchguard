FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    PORT=8080

WORKDIR /app

COPY webapp/requirements.txt /app/webapp/requirements.txt
RUN pip install --no-cache-dir -r /app/webapp/requirements.txt

COPY guard /app/guard
COPY webapp /app/webapp

RUN mkdir -p /data

EXPOSE 8080

CMD ["sh", "-c", "uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
