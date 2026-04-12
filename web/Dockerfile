FROM python:3.11-slim

WORKDIR /app/web

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY index.html /app/web/dist/index.html
COPY favicon.ico /app/web/dist/favicon.ico
COPY favicon-32.png /app/web/dist/favicon-32.png
COPY apple-touch-icon.png /app/web/dist/apple-touch-icon.png
COPY logo.png /app/web/dist/logo.png
COPY logo-128.png /app/web/dist/logo-128.png
COPY logo-1024.png /app/web/dist/logo-1024.png

RUN mkdir -p /app/web/dist

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
