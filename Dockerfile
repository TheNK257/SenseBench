# Optional container path. The default install needs no Docker: `pip install ./backend && sensebench serve`.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENSEBENCH_HOST=0.0.0.0 \
    SENSEBENCH_DATA_DIR=/data

WORKDIR /app
COPY backend/ backend/
RUN pip install --no-cache-dir ./backend \
    && useradd --create-home sensebench \
    && mkdir /data && chown sensebench /data
USER sensebench

EXPOSE 8000
CMD ["sensebench", "serve"]
