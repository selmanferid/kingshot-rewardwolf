FROM python:3.11-slim
RUN apt-get update && apt-get install -y \
    libdouble-conversion3 \
    libxslt1.1 \
    libminizip1 \
    libglib2.0-0 \
    libnss3 \
    libfontconfig1 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libxkbcommon0 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY kingshot_giftcode_daemon.py .
RUN mkdir -p /app/data
CMD ["python3", "-u", "kingshot_giftcode_daemon.py"]
