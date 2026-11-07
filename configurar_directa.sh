#!/bin/bash
set -euo pipefail
cd /home/esteban/semaforo_central
test -s central_semaforos.key
sudo -v
sudo systemctl stop oli-semaforos.service 2>/dev/null || true
/usr/bin/python3 central_semaforos.py detener
sleep 3
/usr/bin/python3 central_semaforos.py verificar

if ! command -v dnsmasq >/dev/null 2>&1; then
    echo "Instalando el componente DHCP mientras sigue conectado a Claro."
    sudo apt-get update
    sudo apt-get install -y dnsmasq-base
fi
sudo raspi-config nonint do_wifi_country CO
sudo nmcli radio wifi on
PROFILE="Oli-Semaforos"
if ! sudo nmcli connection show "$PROFILE" >/dev/null 2>&1; then
    AP_PASSWORD=$(/usr/bin/python3 -c 'import secrets; print(secrets.token_urlsafe(12))')
    sudo nmcli connection add type wifi ifname wlan0 con-name "$PROFILE" ssid "$PROFILE" \
        802-11-wireless.mode ap 802-11-wireless.band bg 802-11-wireless.channel 6 \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$AP_PASSWORD" \
        ipv4.method shared ipv4.addresses 10.42.0.1/24 ipv4.never-default yes ipv6.method disabled
fi
sudo nmcli connection modify "$PROFILE" connection.autoconnect yes connection.autoconnect-priority 999
sudo nmcli connection up "$PROFILE"
AP_PASSWORD=$(sudo nmcli --show-secrets -g 802-11-wireless-security.psk connection show "$PROFILE")

sudo tee /etc/systemd/system/oli-semaforos.service >/dev/null <<'SERVICE'
[Unit]
Description=Controlador de semaforos Oli - descubrimiento Wi-Fi automatico
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
User=esteban
WorkingDirectory=/home/esteban/semaforo_central
ExecStart=/usr/bin/python3 -u /home/esteban/semaforo_central/central_semaforos.py raspberry --central auto --confirmed-off
Restart=on-failure
RestartSec=5
TimeoutStopSec=12
UMask=0077

[Install]
WantedBy=multi-user.target
SERVICE
sudo systemctl daemon-reload
sudo systemctl enable --now oli-semaforos.service
sudo systemctl is-active oli-semaforos.service
echo ""
echo "RED CREADA: Oli-Semaforos"
printf 'CONTRASEÑA WI-FI: %s\n' "$AP_PASSWORD"
echo "Raspberry: 10.42.0.1. Controlador automático instalado."
echo "Conecta el Mac a esta red y activa Conectarse automáticamente."
echo "Abre la central 2.1: el enlace se establece sin escribir la IP del Mac."
