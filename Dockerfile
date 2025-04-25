FROM python:3.10.9-slim-buster

WORKDIR /app
ADD . /app

RUN apt-get update && \
   apt-get install -y --no-install-recommends \
   gcc \
   python3-dev \
   git \
   ffmpeg \
   && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
   pip install --no-cache-dir -r requirements.txt

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]