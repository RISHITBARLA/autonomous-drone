#!/usr/bin/env bash
# ==============================================================================
# AUTONOMOUS-DRONE: Live Deployment & Verification Script on Raspberry Pi 4
# ==============================================================================
set -e

TARGET_DIR="/home/drone/AUTONOMOUS-DRONE"
cd "$TARGET_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/drone/backups/backup_${TIMESTAMP}"
mkdir -p "$BACKUP_DIR"

echo "=================================================================="
echo "🚀 AUTONOMOUS-DRONE: Live Deployment Execution [${TIMESTAMP}]"
echo "📂 Target Directory: $TARGET_DIR"
echo "📦 Backup Directory: $BACKUP_DIR"
echo "=================================================================="

# 1. Back up existing target files
FILES_TO_BACKUP=(
  ".env"
  ".env.example"
  "backend/app.py"
  "backend/api/flight_routes.py"
  "backend/api/geofence_routes.py"
  "backend/flight/flight_controller.py"
  "backend/flight/mavlink_service.py"
  "backend/search/coverage_planner.py"
  "config/settings.py"
  "data/missions.json"
  "frontend/index.html"
  "frontend/css/dashboard.css"
  "frontend/js/dashboard.js"
  "scripts/deploy.sh"
)

echo "💾 Backing up replaced files to $BACKUP_DIR..."
for f in "${FILES_TO_BACKUP[@]}"; do
  if [ -f "$f" ]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$f")"
    cp -p "$f" "$BACKUP_DIR/$f"
  fi
done
echo "✅ Backup completed successfully."

# 2. Extract new deployment bundle
echo "📥 Unpacking deployment bundle..."
tar -xzf /tmp/deploy_bundle.tar.gz -C "$TARGET_DIR"

# 3. Verify SHA256 hashes
echo "🔍 Verifying SHA256 checksums..."
sha256sum -c manifest.sha256
echo "✅ Checksum verification passed 100%!"

# 4. Authorize Windows SSH public key for seamless subsequent automation
mkdir -p /home/drone/.ssh
chmod 700 /home/drone/.ssh
PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIM+GhAEqr7Tcr1rbb/re6iSCSLEHB5q0KlPao7hZNoYF ideal@Creator-Club"
if ! grep -q "$PUBKEY" /home/drone/.ssh/authorized_keys 2>/dev/null; then
  echo "$PUBKEY" >> /home/drone/.ssh/authorized_keys
  chmod 600 /home/drone/.ssh/authorized_keys
  echo "🔑 Windows developer SSH public key authorized."
fi

# 5. Safe .env configuration (preserve unrelated settings, enforce required hardware settings)
if [ ! -f ".env" ]; then
  cp .env.example .env
fi

echo "⚙️ Reconciling .env hardware settings..."
python3 - << 'EOF'
import re

env_file = ".env"
try:
    with open(env_file, "r") as f:
        content = f.read()
except FileNotFoundError:
    content = ""

settings = {
    "MAVLINK_TRANSPORT": "serial",
    "MAVLINK_CONNECTION": "/dev/serial0",
    "MAVLINK_CONNECTION_STRING": "/dev/serial0",
    "MAVLINK_BAUDRATE": "115200",
    "MAVLINK_SIMULATE": "false",
    "FLIGHT_CONTROL_ENABLED": "false",
    "ARMING_CHECKS_ENABLED": "true",
    "FORCE_ARM": "false",
}

for key, val in settings.items():
    pattern = rf"^{key}=.*$"
    replacement = f"{key}={val}"
    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content += f"\n{key}={val}\n"

with open(env_file, "w") as f:
    f.write(content)

print("✅ .env hardware and safety parameters reconciled.")
EOF

# 6. Verify UART permissions
echo "🔌 Verifying UART device and permissions..."
ls -l /dev/serial0 /dev/ttyAMA0 2>/dev/null || echo "⚠️ Notice: /dev/serial0 not found. Check if enable_uart=1 in /boot/firmware/config.txt"
groups drone

# 7. Restart systemd service
echo "🔄 Restarting autonomous-drone background service..."
sudo systemctl daemon-reload
sudo systemctl restart autonomous-drone.service
sleep 2

# 8. Check service status
echo "=================================================================="
echo "📊 SERVICE STATUS:"
sudo systemctl status autonomous-drone --no-pager || true

echo "=================================================================="
echo "📋 RECENT JOURNAL LOGS:"
sudo journalctl -u autonomous-drone -n 60 --no-pager || true

# 9. Verify live HTTP endpoints
echo "=================================================================="
echo "🌐 TESTING LIVE HTTP ENDPOINTS:"
echo "--- Root HTTP Headers ---"
curl -sI http://127.0.0.1:5000/ || true

echo "--- Flight Status API ---"
curl -s http://127.0.0.1:5000/api/flight/status || true
echo ""

echo "--- Coverage API ---"
curl -s http://127.0.0.1:5000/api/geofence/coverage || true
echo ""

echo "=================================================================="
echo "🎉 DEPLOYMENT AND VERIFICATION COMPLETED!"
echo "=================================================================="

