#!/bin/sh
# Starts a trivial static HTTP server just so Render's port scanner sees an
# open port, completely separate from the bot process. main.py no longer
# needs any HTTP/threading code at all.
python3 -m http.server "${PORT:-8080}" --bind 0.0.0.0 &

# Run the actual bot in the foreground so the container's lifecycle
# (SIGTERM on redeploy, exit codes, etc.) tracks the bot process.
exec python3 main.py
