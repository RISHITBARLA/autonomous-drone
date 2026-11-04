# AUTONOMOUS-DRONE Installation & Deployment Guide

This document describes how to set up, develop, and deploy the **AUTONOMOUS-DRONE** platform on Windows development machines and the Raspberry Pi 4 companion computer.

---

## 1. Development on Windows PC (Simulated / Mock Environment)

### Prerequisites
- Python 3.10+ installed.
- Git for Windows.

### Setup Instructions
1. **Clone the repository:**
   ```powershell
   git clone https://github.com/laxminivas06/AUTONOMOUS-DRONE.git
   cd AUTONOMOUS-DRONE
   ```

2. **Configure Environment:**
   ```powershell
   Copy-Item .env.example .env
   ```

3. **Install Dependencies:**
   ```powershell
   py -3.10 -m pip install -r requirements.txt
   ```

4. **Execute Full Automated Test Suite:**
   ```powershell
   py -3.10 -m pytest -v
   ```

5. **Start Companion Ground Station Server:**
   ```powershell
   py -3.10 backend/app.py
   ```
   Open your browser to: `http://localhost:5000`

---

## 2. Production Deployment on Raspberry Pi 4

### Recommended Hardware
- **Companion Computer:** Raspberry Pi 4 Model B (4GB or 8GB recommended).
- **Flight Controller:** Pixhawk 2.4.8 connected via TELEM2 UART port.
- **Camera:** Sony IMX477 12.3MP High Quality Camera (15-pin CSI-2 ribbon).
- **Power Supply:** Dedicated 5V/3A switching BEC connected to the quadcopter power distribution board.
- **Operating System:** Raspberry Pi OS 64-bit (Debian Bookworm or Bullseye).

### Step 1: System Packages & Drivers
Connect via SSH:
```bash
ssh drone@<RASPBERRY_PI_IP>
```

Update system and install required apt dependencies:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3-pip python3-venv python3-libcamera python3-picamera2 v4l-utils libcamera-tools
```

### Step 2: Camera & Serial UART Configuration
1. Open Raspberry Pi firmware configuration:
   ```bash
   sudo nano /boot/firmware/config.txt
   # (On older Bullseye: sudo nano /boot/config.txt)
   ```
2. Ensure camera and UART are enabled:
   ```ini
   camera_auto_detect=1
   dtoverlay=imx477
   enable_uart=1
   ```
3. Disable Linux serial login console:
   ```bash
   sudo raspi-config
   # Interface Options -> Serial Port -> Login Shell: NO -> Hardware UART: YES
   ```
4. Reboot the companion computer:
   ```bash
   sudo reboot
   ```

### Step 3: Application Installation
1. Clone repository to user home directory:
   ```bash
   cd ~
   git clone https://github.com/laxminivas06/AUTONOMOUS-DRONE.git
   cd AUTONOMOUS-DRONE
   ```

2. Create virtual environment with system site-packages (for picamera2):
   ```bash
   python3 -m venv --system-site-packages venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Setup environment configuration:
   ```bash
   cp .env.example .env
   nano .env
   ```
   Set for physical hardware:
   ```ini
   CAMERA_BACKEND=auto
   MAVLINK_SIMULATE=false
   MAVLINK_CONNECTION_STRING=/dev/ttyAMA0
   MAVLINK_BAUDRATE=57600
   ```

4. Verify tests pass on Raspberry Pi:
   ```bash
   pytest -v
   ```

### Step 4: Systemd Service Installation (Auto-Start on Boot)
1. Copy systemd service file:
   ```bash
   sudo cp systemd/autonomous-drone.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
2. Enable and start service:
   ```bash
   sudo systemctl enable autonomous-drone
   sudo systemctl start autonomous-drone
   ```
3. Check service status:
   ```bash
   sudo systemctl status autonomous-drone
   ```
4. View live companion logs:
   ```bash
   journalctl -u autonomous-drone -f
   ```

Access Ground Station from any PC/tablet on the local network at:
`http://<RASPBERRY_PI_IP>:5000`
