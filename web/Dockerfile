FROM python:3.11-slim

WORKDIR /app/web

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY index.html /app/web/dist/index.html
COPY twa.html /app/web/dist/twa.html

RUN mkdir -p /app/web/dist

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
