#!/usr/bin/env bash
set -e

echo "Stopping services..."

systemctl --user disable photo-frame-kiosk.service || true
systemctl --user stop photo-frame-kiosk.service || true

systemctl --user disable photo-frame-sync.timer || true
systemctl --user stop photo-frame-sync.timer || true

rm -f ~/.config/systemd/user/photo-frame-kiosk.service
rm -f ~/.config/systemd/user/photo-frame-sync.service
rm -f ~/.config/systemd/user/photo-frame-sync.timer

systemctl --user daemon-reload

echo "Removing directories..."

rm -rf ~/photo-frame
rm -rf ~/photo-frame-data
sudo rm -rf /mnt/photo-frame

echo "Disabling linger..."
sudo loginctl disable-linger pi

echo "Optional: removing packages..."
sudo apt remove -y \
  rclone \
  libsdl2-ttf-2.0-0 libsdl2-image-2.0-0

sudo apt autoremove -y

echo "Done. Reboot recommended."
