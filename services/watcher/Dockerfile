FROM python:3.12-slim

WORKDIR /app

# bsdtar (libarchive) is rarfile's extraction backend for .rar archives —
# listing/peeking a .rar needs no external tool (rarfile parses RAR's own
# header format in pure Python), but actual decompression does, since
# RAR's compression algorithm isn't freely implementable the way .zip/.7z's
# are. Picked over unrar/unar specifically because it's in Debian's main
# repo with no non-free licensing wrinkle.
RUN apt-get update && apt-get install -y --no-install-recommends libarchive-tools \
    && rm -rf /var/lib/apt/lists/*

COPY watcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY watcher/app ./app

CMD ["python", "-m", "app.main"]
