FROM python:3.12-slim

WORKDIR /app

# Mesa's software EGL backend (llvmpipe) gives pyrender a headless OpenGL
# context — no GPU or X server needed to rasterize thumbnails. Debian's
# packaged OSMesa doesn't support the core-profile context pyrender needs,
# so EGL is the backend that actually works here. libx11/libxext/libxrender
# are only there because pyrender unconditionally imports its interactive
# Viewer (pyglet) at package import time, even though we never use it.
# libgomp1 is needed by cadquery-ocp (OpenCASCADE uses OpenMP internally).
# libarchive-tools provides bsdtar — rarfile's extraction backend for .rar
# archives (see watcher/Dockerfile's comment for why bsdtar specifically).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglx-mesa0 \
    libgl1-mesa-dri \
    libegl1 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    libarchive-tools \
    && rm -rf /var/lib/apt/lists/*

ENV PYOPENGL_PLATFORM=egl

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY worker/app ./app

CMD ["python", "-m", "app.main"]
