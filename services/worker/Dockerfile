# ---- Stage 1: build the STEP -> OBJ converter tool -------------------------
# Linked directly against Debian's packaged OpenCASCADE (OCCT) libraries
# instead of pulling in cadquery-ocp's ~1.4GB bundled OpenCASCADE
# distribution via pip -- see step_converter/step_converter.cpp's own
# header comment for the full reasoning (mirrors how the author's separate
# spool-swift native-Mac rewrite solved the same problem: OCCT is portable
# C++, so isolating tessellation into a small external tool sidesteps
# needing OCCT bindings for the host language at all). This stage's g++/
# dev-header footprint never reaches the final image -- only the compiled
# binary does.
FROM python:3.12-slim AS step-converter-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    libocct-foundation-dev \
    libocct-modeling-data-dev \
    libocct-modeling-algorithms-dev \
    libocct-data-exchange-dev \
    && rm -rf /var/lib/apt/lists/*
COPY worker/step_converter/step_converter.cpp /build/step_converter.cpp
RUN g++ -std=c++17 -O2 -I/usr/include/opencascade /build/step_converter.cpp \
    -lTKDESTEP -lTKXSBase -lTKMesh -lTKBRep -lTKTopAlgo -lTKGeomAlgo \
    -lTKG3d -lTKG2d -lTKMath -lTKernel -lTKBO -lTKPrim \
    -o /build/step_converter

# ---- Stage 2: the actual worker image ---------------------------------------
FROM python:3.12-slim

WORKDIR /app

# Mesa's software EGL backend (llvmpipe) gives pyrender a headless OpenGL
# context — no GPU or X server needed to rasterize thumbnails. Debian's
# packaged OSMesa doesn't support the core-profile context pyrender needs,
# so EGL is the backend that actually works here. libx11/libxext/libxrender
# are only there because pyrender unconditionally imports its interactive
# Viewer (pyglet) at package import time, even though we never use it.
# libgomp1 is needed by OCCT (uses OpenMP internally). libarchive-tools
# provides bsdtar — rarfile's extraction backend for .rar archives (see
# watcher/Dockerfile's comment for why bsdtar specifically). The
# libocct-*-7.8 packages are runtime-only (no -dev, no compiler needed
# here) — just the shared libraries step_converter (copied in below)
# links against at startup; confirmed via `apt-get install` dry-run this
# whole set is ~380MB installed, vs. cadquery-ocp's ~1.4GB bundled
# OpenCASCADE distribution it replaces.
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
    libocct-foundation-7.8 \
    libocct-modeling-data-7.8 \
    libocct-modeling-algorithms-7.8 \
    libocct-data-exchange-7.8 \
    && rm -rf /var/lib/apt/lists/*

ENV PYOPENGL_PLATFORM=egl

COPY --from=step-converter-build /build/step_converter /usr/local/bin/step_converter

COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common ./common
COPY worker/app ./app

CMD ["python", "-m", "app.main"]
