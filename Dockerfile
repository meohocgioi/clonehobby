FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tpclone ./tpclone
ENV PYTHONUNBUFFERED=1 DB_PATH=/data/tpclone.db WEB_HOST=0.0.0.0 WEB_PORT=8080
VOLUME /data
EXPOSE 8080
CMD ["python", "-m", "tpclone", "run"]
