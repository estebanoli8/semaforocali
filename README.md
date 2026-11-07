# Metámosle Ingeniería a la Política

Central semafórica de demostración de Esteban Oli: Raspberry Pi 4 controla un semáforo físico mediante relés y lee dos sensores HC-SR04. Una aplicación Python en el Mac muestra las distancias, el estado del semáforo y tres cruces vecinos simulados, y propone tiempos mediante reglas.

<img src="logo.png" alt="Ingeniero Esteban Oli" width="280">

## Versión incluida

Versión 2.1 con el último cambio de logo PNG con sombra y transparencia. Incluye Wi-Fi directa, descubrimiento automático autenticado, arranque del controlador con systemd, dos sensores, historial SQLite y semáforos A/B/C con el mismo diseño del principal.

El modo llamado «inteligencia artificial» en la interfaz es una emulación basada en reglas; no contiene un modelo entrenado. Las distancias representan niveles de demanda para la demostración: un HC-SR04 no mide por sí solo el número real de vehículos de una fila.

## Uso diario (instalación ya configurada)

1. Enciende la Raspberry: crea la red `Oli-Semaforos` y arranca el controlador.
2. Conecta el Mac a esa red. Si sigue en otra red conocida, selecciónala manualmente.
3. En la terminal del Mac:

```bash
cd "$HOME/semaforo_cali"
bash 01_abrir_central.command
```

Abre http://127.0.0.1:8765 y conserva la terminal abierta. No se necesita Internet para operar. La dirección de la Raspberry en esta red es `10.42.0.1`.

## Primera instalación

Python 3.9 o posterior en el Mac; Raspberry Pi OS con NetworkManager y `lgpio` para `/usr/bin/python3` en la Raspberry. Los scripts están preparados para el usuario `esteban` y `/home/esteban/semaforo_central`; adapta esas rutas si utilizas otro usuario.

Descarga o clona este repositorio en `~/semaforo_cali`. Para configurar por primera vez, conecta la Raspberry por Ethernet a tu router con Internet y el Mac a la misma red.

1. Abre `01_abrir_central.command` con `bash` como arriba. Crea `central_semaforos.key` si falta.
2. En **otra terminal del Mac**, ejecuta:

```bash
cd "$HOME/semaforo_cali"
bash 02_cargar_y_arrancar_raspberry.command
```

Introduce la IP actual de la Raspberry y responde a cada pregunta por separado. La contraseña SSH es la del usuario de la Raspberry. El script copia la misma clave a ambos equipos. Verifica los relés con la alimentación de los bombillos desconectada.

3. Una vez termine el instalador, ejecuta:

```bash
bash 04_preparar_wifi_directa.command
```

Este paso configura el punto de acceso y el servicio de arranque. Guarda la contraseña Wi-Fi aleatoria que imprime; no está incluida en el repositorio. Conecta el Mac a `Oli-Semaforos`, permite conexiones entrantes a Python y comprueba las lecturas y el botón L antes de desconectar Ethernet.

No pegues varios comandos interactivos juntos: espera a que termine cada instalador. Conserva la clave y las bases de datos al actualizar. Si el servicio ya está activo, ejecuta primero `bash 03_detener_raspberry.command` antes de cargar otra versión.

## Hardware y GPIO (BCM)

| Función | GPIO | Pin físico |
|---|---:|---:|
| Relé verde IN1 | 17 | 11 |
| Relé amarillo IN2 | 27 | 13 |
| Relé rojo IN3 | 22 | 15 |
| Sensor 1 TRIG / ECHO | 23 / 24 | 16 / 18 |
| Sensor 2 TRIG / ECHO | 5 / 6 | 29 / 31 |

Los ECHO requieren divisores independientes de 5 V a menos de 3,3 V. La configuración original usa relés optoacoplados activos en LOW y lámparas de 12 V. El segundo sensor representa una entrada competidora; no hay un segundo semáforo físico controlado en esta versión.

## Pantalla y controles

- Dos lecturas de distancia aproximadamente cada segundo, barras de demanda y gráfica de 0–250 cm.
- Tres prioridades: mucho trancón, poco tráfico y coordinación simulada con A/B/C.
- L: amarillo intermitente; automático: secuencia normal.
- Schoringer y Rumba: efectos de exhibición habilitados expresamente desde la interfaz.
- Datos persistentes y reenvío tras cortes de red. Los valores retenidos se identifican con su antigüedad; no se presentan como mediciones nuevas.

**Prototipo para exhibición aislada, no controlador certificado para dirigir tránsito real.** Los efectos pueden encender luces incompatibles entre sí. No instalarlos para dar instrucciones a conductores.

## Claves y archivos locales

`.gitignore` excluye claves, contraseñas locales, históricos, registros y respaldos. No publiques `central_semaforos.key` ni la contraseña de la red. El descubrimiento usa HMAC sobre UDP 8766; la telemetría usa HTTP 8765 con clave de enlace en una red WPA2 local. No expongas esos puertos a Internet; HTTP no proporciona cifrado de transporte adicional.

## Pruebas sin hardware

```bash
python3 -m unittest -v test_control.py
python3 -m py_compile central_semaforos.py
```

Las pruebas verifican reglas, fases y efectos, retención y reenvío de muestras, y autenticación del descubrimiento. No validan la electrónica ni sustituyen la comprobación física del Wi-Fi.

## Guía completa y mantenimiento

Consulta [LEEME.md](LEEME.md) para tiempos, sensores, instalación y recuperación. Para cambiar el logo, reemplaza `logo.png` y recarga el navegador con Cmd+Shift+R.

Apagado de la Raspberry desde el Mac conectado a Oli-Semaforos:

```bash
ssh -t esteban@10.42.0.1 'sudo systemctl stop oli-semaforos.service && sudo shutdown -h now'
```

Después cierra la central con Ctrl+C y espera a que la Raspberry termine de apagarse antes de cortar su alimentación.
