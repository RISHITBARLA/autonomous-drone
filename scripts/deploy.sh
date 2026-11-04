#!/usr/bin/env bash
# ==============================================================================
# AUTONOMOUS-DRONE Production Deployment Script for Raspberry Pi 4
# ==============================================================================
set -e

echo "=================================================================="
echo "🚀 AUTONOMOUS-DRONE: Starting Companion Computer Deployment"
echo "=================================================================="

# Check if running in project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "📂 Project root: $SCRIPT_DIR"

# 1. Ensure current user is in required hardware groups (dialout, video)
echo "🔑 Checking hardware group permissions..."
sudo usermod -a -G dialout,video "$USER"

# 2. Update Linux packages and camera dependencies
echo "📦 Checking system packages..."
sudo apt-get update -y
sudo apt-get install -y git python3-pip python3-venv python3-libcamera python3-picamera2 v4l-utils libcamera-tools

# 3. Setup Virtual Environment with system site-packages (for Picamera2/Libcamera)
if [ ! -d "venv" ]; then
    echo "🐍 Creating virtual environment with system site-packages..."
    python3 -m venv --system-site-packages venv
fi

# Ensure system-site-packages is enabled in pyvenv.cfg
if [ -f "venv/pyvenv.cfg" ]; then
    sed -i 's/include-system-site-packages = false/include-system-site-packages = true/' venv/pyvenv.cfg
fi

# 4. Activate venv and install Python requirements
echo "📚 Installing / updating Python dependencies..."
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. Ensure .env exists
if [ ! -f ".env" ]; then
    echo "⚙️ Creating default .env from .env.example..."
    cp .env.example .env
fi

# 6. Install Udev rule for Pixhawk persistent device (/dev/pixhawk)
if [ -f "systemd/99-pixhawk.rules" ]; then
    echo "🔌 Installing udev rule for Pixhawk (/dev/pixhawk)..."
    sudo cp systemd/99-pixhawk.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules
    sudo udevadm trigger
fi

# 7. Install and enable Systemd service for auto-start on boot
echo "⚡ Installing systemd service (autonomous-drone.service)..."
sudo cp systemd/autonomous-drone.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable autonomous-drone.service

# 8. Start / Restart the service
echo "🔄 Starting autonomous-drone background service..."
sudo systemctl restart autonomous-drone.service

sleep 2

# 9. Verify service status
echo "=================================================================="
if sudo systemctl is-active --quiet autonomous-drone.service; then
    echo "✅ DEPLOYMENT SUCCESSFUL! Service is ACTIVE and running."
else
    echo "⚠️ Warning: Service is not active. Check logs with: journalctl -u autonomous-drone -n 20"
fi
echo "=================================================================="

# Get active IP addresses
IP_ADDRS=$(hostname -I | tr ' ' '\n' | grep -v '^$' || echo "localhost")
echo "🌐 Ground Station UI is accessible on your network at:"
for ip in $IP_ADDRS; do
    echo "   👉 http://${ip}:5000"
done
echo "=================================================================="
echo "Commands for ongoing operations:"
echo "  View live logs:    journalctl -u autonomous-drone -f"
echo "  Restart service:   sudo systemctl restart autonomous-drone"
echo "  Stop service:      sudo systemctl stop autonomous-drone"
echo "=================================================================="
