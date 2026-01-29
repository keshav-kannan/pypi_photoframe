#!/usr/bin/env bash
set -euo pipefail

# ---- Config (edit to taste) ----
APP_DIR="${APP_DIR:-$HOME/photo-frame}"
PHOTOS_DIR="${PHOTOS_DIR:-/mnt/photo-frame/photos}"
DATA_DIR="${DATA_DIR:-$HOME/photo-frame-data}"
VENV_DIR="${VENV_DIR:-$APP_DIR/.venv}"
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive}"
RCLONE_SOURCE="${RCLONE_SOURCE:-PhotoFrame}"   # folder name in Drive
# --------------------------------

echo "==> Installing OS packages..."
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  git rclone \
  xserver-xorg xinit \
  libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-ttf-2.0-0 libsdl2-mixer-2.0-0 \
  libjpeg-dev libpng-dev

echo "==> Creating folders..."
sudo mkdir -p "$(dirname "$PHOTOS_DIR")"
mkdir -p "$PHOTOS_DIR"
mkdir -p "$DATA_DIR/favorites"
mkdir -p "$DATA_DIR/assets"

echo "==> Copying bundled font into data dir (if present)..."
if [ -f "$APP_DIR/assets/Inter-Regular.ttf" ]; then
  cp -f "$APP_DIR/assets/Inter-Regular.ttf" "$DATA_DIR/assets/Inter-Regular.ttf"
fi

echo "==> Creating Python venv..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Writing environment file..."
cat > "$DATA_DIR/env" <<EOF
PHOTO_FRAME_PHOTOS_DIR=$PHOTOS_DIR
PHOTO_FRAME_DATA_DIR=$DATA_DIR
EOF

echo "==> Installing systemd units..."
sudo cp -f "$APP_DIR/systemd/photo-frame.service" /etc/systemd/system/photo-frame.service
sudo cp -f "$APP_DIR/systemd/photo-frame-sync.service" /etc/systemd/system/photo-frame-sync.service
sudo cp -f "$APP_DIR/systemd/photo-frame-sync.timer" /etc/systemd/system/photo-frame-sync.timer

sudo systemctl daemon-reload

echo "==> Enable sync timer + app autostart..."
sudo systemctl enable --now photo-frame-sync.timer
sudo systemctl enable --now photo-frame.service

echo "==> Done."
echo "Next: run 'rclone config' to set remote '$RCLONE_REMOTE' (if not already), then start sync:"
echo "  sudo systemctl start photo-frame-sync.service"
