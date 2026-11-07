# Central semafórica 2.1 — instalación y red portátil

Esta versión sustituye el programa anterior en ambos equipos. Conserva relés GPIO17/27/22 y sensor 1 GPIO23/24; añade sensor 2 GPIO5/6, el logo, la interfaz nueva, historial persistente y modos especiales. No cambia automáticamente la configuración del router ni accede a tu red desde ChatGPT: los pasos siguientes se ejecutan en tus equipos.

## Archivos del paquete

- `central_semaforos.py`: controlador y servidor central, versión 2.1.
- `interfaz.html` y `logo.png`: interfaz y logo local, sin servicios web ni fuentes externas.
- `01_abrir_central.command`: abre la central en el Mac.
- `02_cargar_y_arrancar_raspberry.command`: pide la IP, detiene la versión anterior, respalda el Python anterior, copia Python + clave y arranca el controlador.
- `03_detener_raspberry.command`: detiene el controlador.
- `04_preparar_wifi_directa.command` y `configurar_directa.sh`: crean el Wi-Fi de la Raspberry e instalan el controlador automático, una sola vez.
- `test_control.py`: pruebas del modelo, tiempos, modos y almacenamiento; no toca GPIO.

La clave `central_semaforos.key` se genera localmente y no viene en el ZIP. Conserva la existente. Los históricos se crean como archivos SQLite locales. No borres ni reemplaces esos archivos al actualizar.

## 1. Actualizar primero en la red que ya funciona

Continúa inicialmente con Raspberry por Ethernet a Claro y Mac por Wi-Fi a Claro. No cambies ambas cosas a la vez.

1. Detén el controlador anterior desde una terminal del Mac:

```bash
ssh esteban@192.168.40.21 '/usr/bin/python3 /home/esteban/semaforo_central/central_semaforos.py detener'
```

2. Detén la central anterior con Ctrl+C en su terminal. Si el puerto está ocupado, abre `http://127.0.0.1:8765/health` y comprueba la versión antes de abrir una segunda instancia. El código 2.1 permite reutilizar el puerto después del cierre normal.
3. Descarga y descomprime `semaforo_cali.zip` desde Finder. Copia TODOS los archivos de la carpeta descomprimida a `~/semaforo_cali`, reemplazando los archivos del programa cuando Finder pregunte. Conserva `central_semaforos.key`, las bases de datos y registros existentes.
4. Para abrir la carpeta destino desde la terminal del Mac:

```bash
mkdir -p "$HOME/semaforo_cali"
open "$HOME/semaforo_cali"
```

5. Arranca la central, desde una terminal del Mac:

```bash
cd "$HOME/semaforo_cali"
bash 01_abrir_central.command
```

6. En otra terminal del Mac, arranca la carga:

```bash
cd "$HOME/semaforo_cali"
bash 02_cargar_y_arrancar_raspberry.command
```

Cuando pida la dirección, escribe `192.168.40.21` mientras sigas en Claro, si esa IP sigue siendo la de tu Raspberry. Las contraseñas SSH son las de `esteban` en la Raspberry. No se ven mientras se escriben.

La carga detiene y respalda el Python anterior antes de sobrescribirlo. Si informa de GPIO ocupado, hay un programa anterior activo; detenlo antes de continuar. No ejecutes ambas versiones a la vez. Si usabas polaridad activa alta, agrega `--active-high` al comando de arranque remoto dentro del script 02; por defecto se mantiene la activa baja de la instalación original.

Con alimentación de bombillos desconectada y electrónica alimentada, comprueba que los indicadores de los relés estén apagados. Responde `SI` cuando lo hayas comprobado. Después de `Controlador 2.1 iniciado`, puedes alimentar los bombillos. La página se abre en `http://127.0.0.1:8765`; recarga con Cmd+Shift+R si conserva el diseño anterior.

La central necesita los tres archivos `central_semaforos.py`, `interfaz.html` y `logo.png` juntos. En la Raspberry solo se copian el Python y la clave; no necesita navegador ni el logo. La nueva versión usa dos sensores por defecto; el sensor 1 seguirá operando si el segundo aún no tiene ecos.

## 2. Conectar el segundo HC-SR04

Haz cambios de cableado con las fuentes desconectadas. Numeración BCM:

| Elemento | BCM | Pin físico Pi 4 |
|---|---:|---:|
| Relé verde IN1 | 17 | 11 |
| Relé amarillo IN2 | 27 | 13 |
| Relé rojo IN3 | 22 | 15 |
| TRIG sensor 1 | 23 | 16 |
| ECHO sensor 1, después de su divisor | 24 | 18 |
| TRIG sensor 2 | 5 | 29 |
| ECHO sensor 2, después de su divisor | 6 | 31 |
| Alimentación de sensores, 5 V | — | 2 o 4 |
| GND de sensores y divisores | — | 6, por ejemplo |

Cada HC-SR04 necesita SU PROPIO divisor en ECHO. Puedes usar 330 Ω entre ECHO y el nodo GPIO, y 470 Ω entre ese nodo y GND: aproximadamente 2,94 V al recibir 5 V. No conectes el ECHO de 5 V directamente al GPIO. No confundas GPIO6 (pin físico31) con pin físico6 (GND). Conserva la interfaz optoacoplada y sus conexiones ya comprobadas.

El software dispara los ultrasonidos por turnos, con al menos 70 ms entre disparos y mediana de tres ecos por canal. La lectura conjunta se programa aproximadamente cada segundo. La temporización exacta depende del sistema operativo. Orienta los sensores para que no reciban directamente el eco del otro.

## 3. Diseño y funcionamiento

Orden de la página: encabezado/logo y controles; semáforo principal grande; dos tarjetas de distancia; red gráfica de cruces simulados A/B/C; gráfica de ambas distancias; propuesta de la central.

El título es `Metámosle Ingeniería a la Política`, en tamaño grande. A/B/C clonan el mismo dibujo del principal, con escala reducida y un enlace gráfico compartido. Puede cambiarse sin editar código:

```bash
cd "$HOME/semaforo_cali"
caffeinate -i python3 -u central_semaforos.py central --title "TU TÍTULO"
```

No abras este comando mientras otra central esté ocupando el puerto. El fondo es gris y los acentos verdes corresponden al logo adjunto, que se conserva como imagen original.

Los indicadores de trancón recorren verde → amarillo → naranja → rojo, de 0 a 250 cm. El número conserva el valor real hasta 400 cm, aunque supere el límite visual de la barra y de la gráfica. Aún no hay dato inicial hasta que se capture un primer eco válido: no se inventa un cero.

### Tres prioridades

- **1 · Mucho trancón, más verde:** con sensor 1 válido, verde 12 s y rojo 3 s. Es una prioridad seleccionada por el operador.
- **2 · Poco tráfico, priorizar otro:** con sensor 1 válido, verde 3 s y rojo 8 s. Es una prioridad seleccionada por el operador.
- **3 · Modo inteligencia artificial:** emulación mediante reglas, no una red entrenada. Parte de los tiempos locales del sensor 1; suma 2 s de verde por cada cruce A/B en verde y resta 1 s de rojo. Si el sensor 2 supera al sensor 1 por más de 10 cm, resta 3 s de verde y suma 3 s de rojo para ceder tiempo al flujo transversal. Verde limitado a 2–12 s y rojo a 3–12 s. La ocupación simulada de C oscila entre20% y90%; al alcanzar85%, tiene prioridad limitar la entrada: rojo10/verde2 para no alimentar una salida congestionada.

Sensor 1 representa la entrada controlada por las luces físicas. Sensor 2 representa una entrada competidora, sin otro semáforo físico conectado. Las fases de A/B/C son simuladas, con ciclo de 30 s y desfases; no proceden de semáforos reales.

Base local para IA: 2–10 cm → rojo6/verde3; más de10–30 → rojo4/verde6; más de30–400 → rojo3/verde10. Si sensor1 no es válido o tiene más de3 s, se usa rojo8/verde2 en los tres escenarios. Si solo falla sensor2, se decide con sensor1 y vecinos, explicándolo en pantalla.

Los tiempos se fijan al comenzar el siguiente rojo. La secuencia normal conserva rojo → rojo+amarillo1s → verde → amarillo1s. Los tiempos rojos indicados son el intervalo rojo solo; el segundo de rojo+amarillo se suma a la duración física de la luz roja.

### Modos manuales

- **L:** solo amarillo, 0,5 s encendido y 0,5 s apagado. Vuelve al automático con otra pulsación.
- **Schoringer:** rojo y verde simultáneos; amarillo apagado.
- **Rumba:** 3 s alternando todas las luces encendidas/apagadas cada250ms; después rojo0,5s → amarillo0,5s → verde0,5s, tres veces. Se repite el ciclo de7,5s.
- **Automático:** cancela el efecto y comienza por rojo. Seleccionar una prioridad también vuelve al automático.

Schoringer y Rumba requieren marcar `Habilitar efectos de exhibición`. Al desmarcarlo vuelve al automático. Estos efectos accionan físicamente los relés: utilizar únicamente en un montaje aislado de la circulación, sin orientar a conductores. Con tres bombillos de12W a12V simultáneos, solo las lámparas demandan aproximadamente3A; la alimentación y el cableado deben soportar además la electrónica. La conmutación rápida acelera el desgaste de relés electromecánicos; reserva Rumba para pruebas breves. No se garantiza una duración exacta de250ms en los contactos mecánicos.

## 4. Datos sin huecos: qué se conserva y qué significa

- Cada segundo la Raspberry guarda la lectura de ambos sensores y su calidad en `raspberry.sqlite3`.
- Si un eco falla o es inestable, mantiene el último dato válido para la cifra y la línea. Se marca `Dato retenido` con su antigüedad; en la gráfica el segmento retenido es discontinuo.
- La lógica de decisión utiliza la lectura reciente y su calidad, nunca el número retenido como si fuera nuevo.
- Si se corta el Wi-Fi, las muestras se guardan localmente. Al reconectar se reenvían en lotes, se confirman y se eliminan duplicados. No se descartan pendientes deliberadamente; se conservan24h nominales de muestras ya confirmadas en la Raspberry. La central conserva todo el historial recibido en `central.sqlite3`.
- El navegador conserva los últimos números y la última gráfica en almacenamiento local. Recargar la página o interrumpir brevemente la red no vacía los valores ya recibidos.
- La gráfica muestra las últimas300 muestras y escala0–250cm. El CSV permite descargar el historial recibido, distinguiendo medición y valor mostrado.
- Un buffer no puede recuperar ecos que nunca existieron, ni evitar pérdida si se agota el almacenamiento o se corta la energía durante una escritura. Antes de la primera lectura válida se indica `Esperando`; no se fabrican datos. Durante una desconexión la pantalla conserva el último historial y lo completa al recuperar enlace.
- El tiempo de las muestras procede de la Raspberry. Sin Internet/RTC, comprueba su reloj antes de salir; un salto de reloj puede afectar las etiquetas de tiempo, aunque la secuencia y los tiempos de las luces usan su contador y reloj monotónico.

## 5. Wi-Fi directa, sin H3S ni Claro durante el uso

Topología: Raspberry (punto de acceso Oli-Semaforos) ↔ Wi-Fi Mac ↔ central web. La Pi4 usa su Wi-Fi integrado como punto de acceso WPA2 y entrega dirección al Mac. IP de la Raspberry:10.42.0.1. No hay que fijar manualmente una IP en el Mac ni compartir Internet desde él.

Preparación única, mientras aún tienes acceso por Claro:

1. Actualiza los archivos de ambos equipos a2.1 con los pasos1–3. Conserva la Raspberry por Ethernet a Claro y el Mac en el Wi-Fi de Claro.
2. Ejecuta en una segunda terminal del Mac:

```bash
cd "$HOME/semaforo_cali"
bash 04_preparar_wifi_directa.command
```

3. Introduce la IP actual de la Raspberry (192.168.40.21, si no cambió). El script copia el configurador y pide las credenciales SSH/sudo de esteban. Detiene el controlador y vuelve a verificar que los relés estén apagados antes de habilitar su arranque automático.
4. El configurador activa el punto de acceso, genera una contraseña aleatoria y la muestra. Guarda esa contraseña. Si falta dnsmasq-base, lo instala usando Internet por Claro. La clave Wi-Fi queda guardada por NetworkManager; no viene prefijada en este paquete.
5. En el Wi-Fi del Mac selecciona **Oli-Semaforos**, introduce la contraseña mostrada y activa **Conectarse automáticamente a esta red**. Acepta permanecer conectado sin Internet. Permite conexiones entrantes a Python si lo pregunta macOS.
6. Con la central2.1 abierta, espera unos segundos: la Raspberry la descubre usando mensajes firmados con la clave de enlace compartida. No necesita conocer de antemano la IP del Mac.
7. Verifica ambas distancias y L. Después desconecta el Ethernet de Claro. No ejecutes el configurador H3S de paquetes anteriores.

Uso diario:

1. Enciende la Raspberry: crea Oli-Semaforos y arranca el controlador como servicio automáticamente.
2. El Mac recuerda la red. Si permanece en Claro u otra red conocida, selecciona Oli-Semaforos; macOS no garantiza cambiar desde otra red ya conectada.
3. Abre `01_abrir_central.command` (o `bash 01_abrir_central.command`). No necesitas SSH, volver a copiar archivos ni introducir direcciones. Mientras el Wi-Fi conecte, los equipos se enlazan automáticamente.

La central se ejecuta al abrir ese archivo, no se ha instalado un inicio automático al iniciar sesión del Mac. El descubrimiento usa UDP8766 en la red10.42.0.0/24 y la transferencia usa HTTP8765; la clave de enlace se conserva en ambos equipos. Los mensajes de descubrimiento usan desafío aleatorio y firma HMAC; nunca envían la clave. No cambies esa subred sin adaptar también el programa.

El adaptador integrado de la Raspberry se dedica a esta red directa, por lo que no se usa simultáneamente como cliente Wi-Fi de Claro. No se necesita Internet para operar. Si el equipo central tiene otra conexión independiente, puede conservar acceso a Internet por ella, pero no se configura aquí.

Si necesitas volver a la configuración anterior, reconecta Ethernet a Claro antes de desactivar el punto de acceso. Desde SSH:

```bash
sudo systemctl disable --now oli-semaforos.service
sudo nmcli connection modify Oli-Semaforos connection.autoconnect no
sudo nmcli connection down Oli-Semaforos
```

No se eliminan las redes guardadas anteriormente. Para reactivar, con acceso por Ethernet:

```bash
sudo nmcli connection modify Oli-Semaforos connection.autoconnect yes
sudo nmcli connection up Oli-Semaforos
sudo systemctl enable --now oli-semaforos.service
```

Fuentes: https://www.raspberrypi.com/tutorials/host-a-hotel-wifi-hotspot/ y https://www.networkmanager.dev/docs/api/latest/settings-ipv4.html . Solo se necesita una interfaz inalámbrica en este caso porque no se requiere una segunda conexión Wi-Fi a Internet.

## 6. Ver registros, detener y reiniciar

En la red directa, desde el Mac:

```bash
ssh -t esteban@10.42.0.1 'sudo journalctl -u oli-semaforos.service -n 30 -f'
```

Ctrl+C sale del visor, no detiene el controlador. Script03 sí lo detiene. Para apagar después la Raspberry usa `ssh -t esteban@IP_ACTUAL sudo shutdown -h now`, espera30s antes de retirar la alimentación. Cierra la central con Ctrl+C. Los archivos y las bases de datos permanecen.

Al volver, enciende la Raspberry, conecta el Mac a Oli-Semaforos y abre script01. El servicio Raspberry arranca solo. Script02 sirve para actualizaciones: detén antes el servicio con script03; script02 lo reinicia tras copiar. No ejecutes a mano otro controlador sobre los mismos GPIO mientras el servicio esté activo.

Ante más de5s sin respuesta de la central, el controlador pasa mediante transición a amarillo intermitente; recuperar enlace devuelve el modo solicitado. Si se reinicia la central, arranca en automático y con efectos deshabilitados.

Para probar solo la interfaz sin tocar GPIO, con la central normal detenida:

```bash
cd "$HOME/semaforo_cali"
python3 central_semaforos.py central --demo --data-dir "$HOME/semaforo_cali/prueba_visual"
```

La interfaz indicará sensores simulados. No conectes la Raspberry real a esa instancia. Deténla con Ctrl+C y vuelve a abrir script01 para usar sensores físicos. Esta aplicación demuestra coordinación y retroalimentación; no sustituye un controlador vial ni mide por sí sola una fila real de vehículos.

## Validación de esta entrega

Se probaron límites de distancias, influencia de ambos sensores y A/B/C, fijación de tiempos por ciclo, secuencia exacta de Rumba en el reloj lógico, permisos de efectos y recuperación a automático. Una prueba de red real entre procesos simulados cortó la central y verificó recuperación de todas las secuencias guardadas sin duplicados. Se abrió la interfaz en Chromium, en tamaños de escritorio y móvil, y se probaron L, botones, dos valores, retención al fallar la consulta y autenticación. No se han probado desde aquí los sensores, los contactos de relés ni la asociación Wi-Fi física entre tus equipos.
