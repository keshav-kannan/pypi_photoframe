#!/usr/bin/env bash
set -euo pipefail

PHOTOS_DIR="${PHOTO_FRAME_PHOTOS_DIR:-/mnt/photo-frame/photos}"
DATA_DIR="${PHOTO_FRAME_DATA_DIR:-$HOME/photo-frame-data}"

# Your app should read these env vars already (from your main())
export PHOTO_FRAME_PHOTOS_DIR="$PHOTOS_DIR"
export PHOTO_FRAME_DATA_DIR="$DATA_DIR"

# Launch
exec "$HOME/photo-frame/.venv/bin/python" "$HOME/photo-frame/photo_frame.py"
