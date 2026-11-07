#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -f central_semaforos.key ] && [ -f "$HOME/semaforo_cali/central_semaforos.key" ]; then
    cp "$HOME/semaforo_cali/central_semaforos.key" central_semaforos.key
fi
python3 -m py_compile central_semaforos.py
if curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:8765/health >/dev/null 2>&1; then
    echo "Ya hay un servidor en 8765. Si es la versión anterior, detenlo con Ctrl+C antes de actualizar."
    open http://127.0.0.1:8765
    read -r -p "Pulsa Enter para cerrar esta ventana. "
    exit 0
fi
echo "Central 2.1. Conserva esta ventana abierta y la tapa del equipo abierta."
exec caffeinate -i python3 -u central_semaforos.py central
