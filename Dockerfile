FROM python:3.11-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY strm_webhook.py .
COPY config.yaml .

# 默认 STRM 输出目录
RUN mkdir -p /data/strm

EXPOSE 9527

CMD ["python", "strm_webhook.py", "--config", "/app/config.yaml"]
