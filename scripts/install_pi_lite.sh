#!/usr/bin/env bash
set -e

APP_DIR="$HOME/photo-frame"
DATA_DIR="$HOME/photo-frame-data"
PHOTOS_DIR="/mnt/photo-frame/photos"
VENV_DIR="$APP_DIR/.venv"

echo "=== Installing minimal packages ==="
sudo apt update
sudo apt install -y \
  xserver-xorg xinit x11-xserver-utils \
  python3 python3-venv python3-pip \
  git rclone \
  libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-ttf-2.0-0

echo "=== Creating directories ==="
mkdir -p "$DATA_DIR/assets"
mkdir -p "$DATA_DIR/favorites"
mkdir -p "$PHOTOS_DIR"

echo "=== Copying font ==="
if [ -f "$APP_DIR/assets/Inter-Regular.ttf" ]; then
  cp "$APP_DIR/assets/Inter-Regular.ttf" "$DATA_DIR/assets/"
fi

echo "=== Creating virtual environment ==="
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "=== Writing env file ==="
cat > "$DATA_DIR/env" <<EOF
PHOTO_FRAME_PHOTOS_DIR=$PHOTOS_DIR
PHOTO_FRAME_DATA_DIR=$DATA_DIR
EOF

echo "=== Installing systemd user service ==="
mkdir -p ~/.config/systemd/user
cp "$APP_DIR/systemd/photo-frame-kiosk.service" ~/.config/systemd/user/

systemctl --user daemon-reexec
systemctl --user daemon-reload
systemctl --user enable photo-frame-kiosk.service

echo "=== Enable user services at boot ==="
sudo loginctl enable-linger admin

echo "=== DONE ==="
echo "Next:"
echo "  1) Run: rclone config"
echo "  2) Reboot"
