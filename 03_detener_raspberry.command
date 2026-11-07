#!/bin/bash
set -e
cd "$(dirname "$0")"
DEFAULT_HOST="raspberrypi.local"
if [ -s raspberry_host.txt ]; then DEFAULT_HOST=$(cat raspberry_host.txt); fi
read -r -p "IP o nombre de la Raspberry [$DEFAULT_HOST]: " HOST_PI
HOST_PI=${HOST_PI:-$DEFAULT_HOST}
case "$HOST_PI" in *[!a-zA-Z0-9._-]*|-*|'') echo "Dirección inválida."; exit 1;; esac
ssh -4 -t -o ConnectTimeout=10 "esteban@$HOST_PI" 'if systemctl is-active --quiet oli-semaforos.service; then sudo systemctl stop oli-semaforos.service; else /usr/bin/python3 /home/esteban/semaforo_central/central_semaforos.py detener; fi'
echo "Para apagar también el sistema operativo, ejecuta: ssh -t esteban@$HOST_PI sudo shutdown -h now"
read -r -p "Pulsa Enter para cerrar esta ventana. "
