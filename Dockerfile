FROM python:3.10-bullseye

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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade packaging tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install Pyrogram & PyTgCalls

RUN pip install --no-cache-dir "pyrogram==2.0.106"
RUN pip install --no-cache-dir "py-tgcalls==2.3.0"

# Copy and install external utilities
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Copy source code
COPY . .

CMD ["python3", "main.py"]
