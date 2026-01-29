#!/usr/bin/env bash

source "$HOME/photo-frame-data/env"

export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

exec "$HOME/photo-frame/.venv/bin/python" \
     "$HOME/photo-frame/photo_frame.py"
