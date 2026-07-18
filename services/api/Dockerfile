FROM python:3.12-slim

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY api/app ./app

# Vendored at build time so the running app never needs network access —
# everything the browser loads comes from localhost, matching the "all
# local" design. Pin the version for reproducible builds.
ADD https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js /app/app/static/htmx.min.js

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
