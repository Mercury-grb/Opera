FROM python:3.11-bullseye
# Install Deno and FFmpeg (Required by yt-dlp)
RUN apt-get update && apt-get install -y curl unzip ffmpeg
RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:$PATH"

# Install build dependencies, git, and FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    git \
    ffmpeg \
    libopus-dev \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Node.js — required by the bgutil PO-token-provider plugin (see
# requirements.txt) to work around YouTube's SABR streaming enforcement.
# As of late 2025/2026, YouTube requires a valid PO (Proof-of-Origin) token
# to serve real audio/video URLs; without one it silently falls back to
# storyboard/image-only formats, which is what "Requested format is not
# available" actually means under the hood. This isn't specific to this
# bot — it's an active, ongoing fight between YouTube and every yt-dlp
# user right now. bgutil generates valid tokens locally via a small
# bundled JS script, which needs a JS runtime present.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade packaging tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install PyTgCalls
# NOTE: previously pinned plain pyrogram==2.0.106 here. That caused
# `ImportError: cannot import name 'GroupcallForbidden' from
# 'pyrogram.errors'` — plain pyrogram (unmaintained since 2023) doesn't
# have several exception/type classes that py-tgcalls expects. This is
# exactly what the old "ultimate patch" was hiding by faking missing
# attributes instead of fixing the real mismatch.
#
# Fix: install Kurigram instead of plain pyrogram. Kurigram is an actively
# maintained, drop-in-compatible fork — same `import pyrogram` namespace,
# no code changes needed anywhere else — that includes the newer
# error/type classes py-tgcalls needs. It's pulled in via requirements.txt
# below; do NOT also pip install plain "pyrogram" here, or the two will
# fight over the same import namespace.
#
# IMPORTANT: "pytgcalls" on PyPI is an old, unrelated, deprecated package
# (last released ~5 years ago) — a name collision that trips a lot of
# people up. The actively developed project is published on PyPI under
# the hyphenated name "py-tgcalls". Pinning that instead keeps the
# dependency resolution predictable instead of whatever git's HEAD
# happens to require on a given day.
RUN pip install --no-cache-dir "py-tgcalls==2.3.0"

# Copy and install external utilities
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- REMOVED: "THE ULTIMATE PYROGRAM PATCH" ---
# This used to monkeypatch pyrogram.raw.types with a catch-all __getattr__
# that silently returned a fake MockType for any missing type lookup,
# instead of raising an error. Pyrogram's update dispatcher relies on real
# type lookups here to turn incoming Telegram updates into Message objects
# — silently faking a missing type is a very plausible reason messages
# were never reaching handlers, with no error ever surfacing.
#
# If removing this patch causes an ImportError/AttributeError on startup or
# during pytgcalls usage, that error will now be visible and will tell us
# EXACTLY which type is missing, so we can either pin a compatible
# pytgcalls version or switch to an actively maintained pyrogram fork
# (e.g. Kurigram) instead of hiding it again.

# Copy source code
COPY . .

CMD ["python3", "main.py"]
