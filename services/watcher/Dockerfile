FROM python:3.12-slim

WORKDIR /app

COPY watcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY watcher/app ./app

CMD ["python", "-m", "app.main"]
