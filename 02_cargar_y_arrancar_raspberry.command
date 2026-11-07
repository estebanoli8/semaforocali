#!/bin/bash
set -e
cd "$(dirname "$0")"
test -s central_semaforos.py
if [ ! -s central_semaforos.key ]; then
    echo "Primero ejecuta 01_abrir_central.command para generar la clave de enlace."
    exit 1
fi
DEFAULT_HOST="raspberrypi.local"
if [ -s raspberry_host.txt ]; then DEFAULT_HOST=$(cat raspberry_host.txt); fi
read -r -p "IP o nombre de la Raspberry [$DEFAULT_HOST]: " HOST_PI
HOST_PI=${HOST_PI:-$DEFAULT_HOST}
case "$HOST_PI" in *[!a-zA-Z0-9._-]*|-*|'') echo "Dirección inválida. Escribe solo IP o hostname."; exit 1;; esac
printf '%s\n' "$HOST_PI" > raspberry_host.txt
TARGET_PI="esteban@$HOST_PI"
echo "Apaga la alimentación de los bombillos para verificar los relés al arrancar."
echo "La contraseña SSH es la del usuario esteban de la Raspberry."
ssh -4 -o ConnectTimeout=10 "$TARGET_PI" '
    set -e
    /usr/bin/python3 -c "import lgpio"
    if systemctl is-active --quiet oli-semaforos.service; then
        echo "El servicio automático está activo. Detenlo con el script03 antes de actualizar."
        exit 1
    fi
    mkdir -p /home/esteban/semaforo_central
    cd /home/esteban/semaforo_central
    if [ -f central_semaforos.py ]; then
        /usr/bin/python3 central_semaforos.py detener
        sleep 3
        cp central_semaforos.py "central_semaforos.py.bak.$(date +%Y%m%d_%H%M%S)"
    fi
'
scp -4 central_semaforos.py central_semaforos.key "$TARGET_PI:/home/esteban/semaforo_central/"
ssh -4 -t "$TARGET_PI" '
    set -e
    cd /home/esteban/semaforo_central
    chmod 600 central_semaforos.key
    /usr/bin/python3 -m py_compile central_semaforos.py
    if systemctl is-enabled --quiet oli-semaforos.service 2>/dev/null; then
        sudo systemctl restart oli-semaforos.service
        echo "Servicio automático 2.1 reiniciado."
        exit 0
    fi
    MAC_IP=$(printf "%s" "$SSH_CONNECTION" | cut -d " " -f 1)
    echo "Central semafórica: http://$MAC_IP:8765"
    /usr/bin/python3 -u central_semaforos.py raspberry --central "http://$MAC_IP:8765" --background
'
echo "Si viste Controlador 2.1 iniciado, ya puedes alimentar los bombillos y ver la central."
read -r -p "Pulsa Enter para cerrar esta ventana. "
