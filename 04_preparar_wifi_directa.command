#!/bin/bash
set -e
cd "$(dirname "$0")"
echo "Configuración única. Conserva Raspberry por Ethernet a Claro y Mac en Wi-Fi de Claro."
echo "Primero actualiza ambos equipos a 2.1 con los scripts 01 y 02."
read -r -p "IP actual de la Raspberry [192.168.40.21]: " HOST_PI
HOST_PI=${HOST_PI:-192.168.40.21}
case "$HOST_PI" in *[!a-zA-Z0-9._-]*|-*|'') echo "Dirección inválida"; exit 1;; esac
scp -4 configurar_directa.sh "esteban@$HOST_PI:/home/esteban/semaforo_central/"
ssh -4 -t "esteban@$HOST_PI" 'bash /home/esteban/semaforo_central/configurar_directa.sh'
printf '%s\n' '10.42.0.1' > raspberry_host.txt
echo "Anota la contraseña mostrada arriba. Selecciona Oli-Semaforos en el Wi-Fi del Mac."
echo "Después de comprobar la conexión, puedes desconectar el Ethernet de Claro."
read -r -p "Pulsa Enter para cerrar esta ventana. "
