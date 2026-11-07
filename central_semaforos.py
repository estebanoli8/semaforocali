#!/usr/bin/env python3
"""Central semafórica 2.1. Python >=3.9. GPIO únicamente en Raspberry Pi.
Demostración aislada; no es un controlador vial certificado.
"""
import argparse
import csv
import fcntl
import hmac
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from statistics import median
from urllib.request import Request, build_opener, ProxyHandler
import webbrowser

VERSION = '2.1'
TITLE = 'Metámosle Ingeniería a la Política'
ROOT = Path(__file__).resolve().parent
PINS = {'verde': 17, 'amarillo': 27, 'rojo': 22}
SENSORS = ((23, 24), (5, 6))  # TRIG, ECHO. ECHO siempre con divisor.
MODES = ('auto', 'blink', 'schoringer', 'rumba')
SCENARIOS = ('mucho', 'poco', 'ia')
KEY = ROOT / 'central_semaforos.key'
DEFAULT = {'red': 8, 'green': 2, 'reason': 'Sin lectura reciente: ciclo de respaldo.'}


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def usable(s):
    return (s.get('quality') == 'valida' and number(s.get('cm')) and 2 <= s['cm'] <= 400
            and number(s.get('age')) and 0 <= s['age'] <= 3)


def key_file(path, create=False):
    path = Path(path)
    if create and not path.exists():
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_hex(24))
    key = path.read_text().strip()
    if len(key) < 24:
        raise ValueError('Clave de enlace inválida.')
    return key


def base_plan(s):
    if not usable(s):
        return dict(DEFAULT)
    r, g = (6, 3) if s['cm'] <= 10 else ((4, 6) if s['cm'] <= 30 else (3, 10))
    return {'red': r, 'green': g, 'reason': 'Duración según distancia de la entrada principal.'}


def decide(sensors, scenario, elapsed):
    occupied = {'mucho': (85, 75, 25), 'poco': (25, 65, 30), 'ia': (65, 55, 35)}[scenario]
    if scenario == 'ia':
        occupied = (65, 55, round(55 + 35*math.sin(elapsed/18)))
    def phase(offset):
        t = (elapsed + offset) % 30
        return 'verde' if t < 12 else ('amarillo' if t < 15 else 'rojo')
    neighbors = [dict(id=letter, role=role, phase=phase(offset), occupancy=occ)
                 for letter, role, offset, occ in zip('ABC',
                     ('Entrada principal', 'Entrada transversal', 'Salida del corredor'), (0, 8, -8), occupied)]
    s1, s2 = sensors
    plan = base_plan(s1)
    if usable(s1):
        if scenario == 'mucho':
            plan = dict(red=3, green=12, reason='Prioridad seleccionada: despejar la entrada principal. Verde de 12 s; rojo de 3 s.')
        elif scenario == 'poco':
            plan = dict(red=8, green=3, reason='Prioridad seleccionada: dejar más tiempo a los otros flujos. Verde de 3 s; rojo de 8 s.')
        else:
            arrivals = sum(n['phase'] == 'verde' for n in neighbors[:2])
            extra = 2 * arrivals
            competing = usable(s2) and s2['cm'] > s1['cm'] + 10
            plan['green'] = max(2, min(12, plan['green'] + extra - (3 if competing else 0)))
            plan['red'] = max(3, min(12, plan['red'] - arrivals + (3 if competing else 0)))
            plan['reason'] = (f'IA emulada por reglas: {arrivals} cruces de entrada en verde; C tiene espacio. '
                              + ('Sensor 2 supera al 1 por más de 10 cm: se cede tiempo al otro flujo.' if competing
                                 else ('Se favorece el flujo principal.' if usable(s2) else 'Sensor 2 sin dato reciente: se decide con sensor 1 y A/B/C.')))
            if neighbors[2]['occupancy'] >= 85:
                plan = dict(red=10, green=2, reason='IA emulada por reglas: C supera el 85% de ocupación simulada. Se limita el paso para no alimentar una salida congestionada.')
    return plan, neighbors


class Journal:
    """SQLite: muestras reales, valores retenidos y envío confirmado. Sin borrar pendientes."""
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS samples (device TEXT, seq INTEGER, payload TEXT, PRIMARY KEY(device,seq))')
        self.db.commit()

    def meta(self, key, default=None):
        with self.lock:
            r = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return r[0] if r else default

    def set_meta(self, key, value):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, str(value)))

    def device_id(self):
        value = self.meta('device')
        if not value:
            value = secrets.token_hex(12)
            self.set_meta('device', value)
        return value

    def append(self, device, payload):
        with self.lock, self.db:
            seq = int(self.meta('seq', '0')) + 1
            payload = dict(payload, seq=seq)
            self.db.execute('INSERT INTO samples VALUES (?,?,?)', (device, seq, json.dumps(payload, allow_nan=False)))
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('seq', str(seq)))
            return payload

    def ingest(self, device, samples):
        if not samples and self.meta('active_device') == device:
            return
        with self.lock, self.db:
            self.db.executemany('INSERT OR IGNORE INTO samples VALUES (?,?,?)',
                               [(device, s['seq'], json.dumps(s, allow_nan=False)) for s in samples])
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('active_device', device))

    def pending(self, device):
        with self.lock:
            ack = int(self.meta('ack', '0'))
            rows = self.db.execute('SELECT payload FROM samples WHERE device=? AND seq>? ORDER BY seq LIMIT 120', (device, ack))
            return [json.loads(r[0]) for r in rows]

    def acknowledge(self, device, seq):
        if seq <= int(self.meta('ack', '0')):
            return
        with self.lock, self.db:
            ack = max(int(self.meta('ack', '0')), seq)
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('ack', str(ack)))
            # Conservar 24 horas nominales de muestras confirmadas; nunca borrar las pendientes.
            self.db.execute('DELETE FROM samples WHERE device=? AND seq<?', (device, ack - 86400))

    def history(self, device, limit=300):
        with self.lock:
            rows = self.db.execute('SELECT payload FROM samples WHERE device=? ORDER BY seq DESC LIMIT ?', (device, limit))
            return [json.loads(r[0]) for r in rows][::-1]


class Outputs:
    def __init__(self, active_high=False, chip=0):
        import lgpio
        self.lg = lgpio
        self.h = lgpio.gpiochip_open(chip)
        self.active = int(active_high)
        self.claimed, self.callbacks, self.channels = [], [], []
        self.lights = set()
        try:
            for pin in PINS.values():
                lgpio.gpio_claim_output(self.h, pin, 1-self.active)
                self.claimed.append(pin)
            for trig, echo in SENSORS:
                lgpio.gpio_claim_output(self.h, trig, 0)
                self.claimed.append(trig)
                lgpio.gpio_claim_alert(self.h, echo, lgpio.BOTH_EDGES, lgpio.SET_PULL_DOWN)
                self.claimed.append(echo)
                c = dict(trig=trig, echo=echo, lock=threading.Lock(), event=threading.Event(), armed=False, rise=None, width=None)
                self.channels.append(c)
                def edge(chip, gpio, level, tick, channel=c):
                    with channel['lock']:
                        if not channel['armed']:
                            return
                        if level == 1:
                            channel['rise'] = tick
                        elif level == 0 and channel['rise'] is not None:
                            channel['width'] = (tick-channel['rise']) / 1e9
                            channel['armed'] = False
                            channel['event'].set()
                self.callbacks.append(lgpio.callback(self.h, echo, lgpio.BOTH_EDGES, edge))
        except Exception:
            self.close()
            raise

    def set_lights(self, lights, effects=False):
        if not set(lights) <= set(PINS):
            raise ValueError('Color desconocido')
        if {'rojo', 'verde'} <= set(lights) and not effects:
            raise ValueError('Conflicto de luces fuera del modo de exhibición')
        # Apagar antes de encender: no introducir combinaciones durante transiciones.
        for color, pin in PINS.items():
            if color not in lights:
                self.lg.gpio_write(self.h, pin, 1-self.active)
        for color in lights:
            self.lg.gpio_write(self.h, PINS[color], self.active)
        self.lights = set(lights)

    def pulse(self, c):
        self.lg.gpio_write(self.h, c['trig'], 0)
        if self.lg.gpio_read(self.h, c['echo']):
            return None
        with c['lock']:
            c['event'].clear()
            c.update(armed=True, rise=None, width=None)
        try:
            self.lg.tx_pulse(self.h, c['trig'], 20, 100, pulse_cycles=1)
            c['event'].wait(.065)
        finally:
            with c['lock']:
                c['armed'] = False
                width = c['width']
        cm = width * 17150 if width is not None else None
        return round(cm, 2) if cm is not None and 2 <= cm <= 400 else None

    def measure(self):
        # No disparar dos ultrasonidos a la vez. Separación >=70 ms entre disparos.
        raws = [[], []]
        for _ in range(3):
            for i, c in enumerate(self.channels):
                raws[i].append(self.pulse(c))
                time.sleep(.07)
        result = []
        for raw in raws:
            values = [x for x in raw if x is not None]
            d = median(values) if len(values) >= 2 else None
            quality = 'sin_eco' if d is None else ('inestable' if max(values)-min(values) > max(3, d*.2) else 'valida')
            result.append(dict(cm=round(d, 1) if d is not None else None, quality=quality, raw=raw))
        return result

    def close(self):
        for cb in self.callbacks:
            cb.cancel()
        for pin in self.claimed:
            try:
                if pin in PINS.values():
                    self.lg.gpio_write(self.h, pin, 1-self.active)
                elif pin in [p[0] for p in SENSORS]:
                    self.lg.tx_pulse(self.h, pin, 0, 0)
                    self.lg.gpio_write(self.h, pin, 0)
                self.lg.gpio_free(self.h, pin)
            except Exception:
                pass
        self.lg.gpiochip_close(self.h)


class Simulation:
    def set_lights(self, lights, effects=False):
        if {'rojo', 'verde'} <= set(lights) and not effects:
            raise ValueError('Conflicto')
        self.lights = set(lights)

    def measure(self):
        t = time.monotonic()
        values = [round(110 + 95*math.sin(t/15), 1), round(105 + 85*math.cos(t/19), 1)]
        return [dict(cm=v, quality='valida', raw=[v,v,v]) for v in values]

    def close(self):
        pass


class Machine:
    def __init__(self, hardware, now):
        self.hw, self.plan = hardware, dict(DEFAULT)
        self.mode, self.phase, self.since, self.deadline = 'espera', 'espera', now, now+5
        self.lights = set()
        self.set({'rojo'})

    def set(self, lights, effects=False):
        if self.lights != set(lights):
            self.hw.set_lights(lights, effects)
            self.lights = set(lights)

    def enter(self, phase, seconds, now, lights):
        self.phase, self.since, self.deadline = phase, now, now+seconds
        self.set(lights)

    def red(self, now, plan):
        self.plan, self.mode = dict(plan), 'auto'
        self.enter('rojo', self.plan['red'], now, {'rojo'})

    def tick(self, now, online, command):
        target = command['mode']
        if target in ('schoringer', 'rumba') and not command.get('effects', False):
            target = 'auto'
        if not online:
            self.mode = 'sin_conexion'
            if self.phase == 'espera' and now < self.deadline:
                return
            if self.phase in ('verde', 'schoringer', 'rumba'):
                self.enter('salida_amarillo', 1, now, {'amarillo'})
            elif self.phase == 'amarillo':
                self.phase = 'salida_amarillo'
            elif self.phase in ('rojo', 'rojo_amarillo'):
                self.enter('despeje', 1, now, {'rojo'})
            elif self.phase == 'salida_amarillo' and now >= self.deadline:
                self.enter('despeje', 1, now, {'rojo'})
            elif self.phase == 'espera' or (self.phase == 'despeje' and now >= self.deadline):
                self.enter('blink', .5, now, {'amarillo'})
        elif target != 'auto':
            if self.phase != target or self.mode != target:
                self.mode, self.phase, self.since, self.deadline = target, target, now, now
            if target == 'schoringer':
                self.set({'rojo','verde'}, effects=True)
            elif target == 'rumba':
                t = (now-self.since) % 7.5
                if t < 3:
                    self.set(set(PINS) if int(t/.25) % 2 == 0 else set(), effects=True)
                else:
                    self.set({('rojo','amarillo','verde')[int((t-3)/.5) % 3]})
        else:
            if self.mode != 'auto':
                self.red(now, command['plan'])
            elif now >= self.deadline:
                if self.phase == 'rojo':
                    self.enter('rojo_amarillo', 1, now, {'rojo','amarillo'})
                elif self.phase == 'rojo_amarillo':
                    self.enter('verde', self.plan['green'], now, {'verde'})
                elif self.phase == 'verde':
                    self.enter('amarillo', 1, now, {'amarillo'})
                elif self.phase == 'amarillo':
                    self.red(now, command['plan'])
        if self.phase == 'blink':
            self.set({'amarillo'} if int((now-self.since)/.5) % 2 == 0 else set())

    def snapshot(self, now):
        return dict(mode=self.mode, phase=self.phase, lights=sorted(self.lights),
                    remaining=max(0, round(self.deadline-now, 2)), applied=self.plan)


def validate_sample(s):
    if not isinstance(s, dict) or type(s.get('seq')) is not int or s['seq'] < 1 or not number(s.get('t')):
        raise ValueError('Muestra inválida')
    if not isinstance(s.get('sensors'), list) or len(s['sensors']) != 2:
        raise ValueError('Se necesitan dos canales de sensor')
    for sensor in s['sensors']:
        if not isinstance(sensor, dict):
            raise ValueError('Sensor inválido')
        for field in ('cm','display_cm','age','held_age'):
            if sensor.get(field) is not None and not number(sensor[field]):
                raise ValueError('Dato no numérico')
        raw = sensor.get('raw', [])
        if not isinstance(raw, list) or len(raw) > 3 or any(v is not None and not number(v) for v in raw):
            raise ValueError('Muestras individuales inválidas')


class Central:
    def __init__(self, journal, title=TITLE):
        self.journal, self.title, self.lock = journal, title, threading.RLock()
        self.mode, self.scenario, self.effects = 'auto', 'ia', False
        self.started = time.monotonic()
        self.received, self.latest, self.controller = None, None, {}
        self.device = journal.meta('active_device','')
        saved = journal.history(self.device, 1)
        if saved:
            self.latest = saved[-1]
        self.simulated = False

    def ingest(self, body):
        if body.get('version') != VERSION:
            raise ValueError('Actualiza ambos equipos a la versión 2.1')
        device, samples, latest = body.get('device'), body.get('samples'), body.get('latest')
        if not isinstance(device, str) or not 1 <= len(device) <= 64 or not isinstance(samples,list) or len(samples)>120:
            raise ValueError('Lote inválido')
        if not isinstance(body.get('controller'),dict):
            raise ValueError('Falta el estado del controlador')
        for sample in samples:
            validate_sample(sample)
        if latest is not None:
            validate_sample(latest)
        with self.lock:
            self.journal.ingest(device, samples)
            self.device, self.latest = device, latest or self.latest
            self.received, self.controller = time.monotonic(), body['controller']
            self.simulated = bool(body.get('simulated'))
            plan, _ = decide(self.current_sensors(), self.scenario, time.monotonic()-self.started)
            return dict(version=VERSION, mode=self.mode, effects=self.effects, plan=plan,
                        ack=max((s['seq'] for s in samples), default=0))

    def current_sensors(self):
        extra = (time.monotonic()-self.received if self.received is not None
                 else max(0,time.time()-self.latest['t']) if self.latest else 99999)
        result = []
        for original in (self.latest or {}).get('sensors', [{},{}]):
            s = dict(original)
            s['age'] = (s.get('age') or 0) + extra
            s['held_age'] = (s.get('held_age') or 0) + extra
            if self.received is None or extra > 5:
                s['quality'] = 'desconectado'
            result.append(s)
        return result

    def snapshot(self):
        with self.lock:
            sensors = self.current_sensors()
            plan, neighbors = decide(sensors, self.scenario, time.monotonic()-self.started)
            age = time.monotonic()-self.received if self.received is not None else None
            return dict(version=VERSION, title=self.title, connected=age is not None and age <= 5,
                        age=age, sensors=sensors, controller=self.controller, simulated=self.simulated,
                        mode=self.mode, scenario=self.scenario, effects=self.effects, plan=plan,
                        neighbors=neighbors, history=[dict(seq=s['seq'],t=s['t'],
                            cm=[v.get('display_cm') for v in s['sensors']],
                            held=[v.get('quality')!='valida' for v in s['sensors']])
                            for s in self.journal.history(self.device)], device=self.device)

    def control(self, data):
        if not isinstance(data,dict):
            raise ValueError('Orden inválida')
        with self.lock:
            mode, scenario, effects = data.get('mode',self.mode), data.get('scenario',self.scenario), data.get('effects',self.effects)
            if mode not in MODES or scenario not in SCENARIOS or type(effects) is not bool:
                raise ValueError('Orden fuera de rango')
            if not effects and mode in ('schoringer','rumba'):
                if 'mode' in data:
                    raise ValueError('Activa primero los efectos de exhibición')
                mode = 'auto'
            self.mode, self.scenario, self.effects = mode, scenario, effects


def http_handler(state, key):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def local(self):
            return ipaddress.ip_address(self.client_address[0]).is_loopback

        def reply(self, data, status=200, mime='application/json'):
            payload = json.dumps(data,allow_nan=False).encode() if mime=='application/json' else data
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError,ConnectionResetError):
                pass

        def do_GET(self):
            if self.path=='/health':
                return self.reply(dict(app='central_semaforos',version=VERSION))
            if not self.local():
                return self.reply({'error':'Abre la interfaz en 127.0.0.1'},403)
            if self.path=='/api/state':
                return self.reply(state.snapshot())
            if self.path in ('/','/logo.png'):
                path = ROOT / ('interfaz.html' if self.path=='/' else 'logo.png')
                return self.reply(path.read_bytes(),mime='text/html; charset=utf-8' if self.path=='/' else 'image/png')
            if self.path=='/api/export.csv':
                stream=io.StringIO(); writer=csv.writer(stream)
                writer.writerow(['secuencia','timestamp_sensor','sensor1_cm','calidad1','mostrado1_cm','sensor2_cm','calidad2','mostrado2_cm'])
                for s in state.journal.history(state.device,1000000):
                    a,b=s['sensors'];writer.writerow([s['seq'],s['t'],a.get('cm'),a.get('quality'),a.get('display_cm'),b.get('cm'),b.get('quality'),b.get('display_cm')])
                return self.reply(stream.getvalue().encode(),mime='text/csv; charset=utf-8')
            self.reply({'error':'No encontrado'},404)

        def do_POST(self):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 1024*1024:
                    raise ValueError('Tamaño inválido')
                if self.path=='/api/telemetry':
                    if not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+key):
                        return self.reply({'error':'Clave incorrecta'},401)
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict):
                        raise ValueError('Mensaje inválido')
                    return self.reply(state.ingest(data))
                if self.path=='/api/control':
                    origin=self.headers.get('Origin')
                    if (not self.local() or not self.headers.get('Content-Type','').startswith('application/json')
                        or (origin and origin not in (f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'))):
                        return self.reply({'error':'Origen no permitido'},403)
                    state.control(json.loads(self.rfile.read(size)))
                    return self.reply({'ok':True})
                self.reply({'error':'No encontrado'},404)
            except (ValueError,TypeError,KeyError) as e:
                self.reply({'error':str(e)},400)
    return Handler


def command_valid(data):
    if data.get('version') != VERSION or data.get('mode') not in MODES or type(data.get('effects')) is not bool:
        raise ValueError('Respuesta incompatible')
    p=data.get('plan',{})
    if any(not number(p.get(k)) or not 2 <= p[k] <= 15 for k in ('red','green')):
        raise ValueError('Tiempos inválidos')
    if data['mode'] in ('schoringer','rumba') and not data['effects']:
        raise ValueError('Efecto no habilitado')
    return dict(mode=data['mode'],effects=data['effects'],plan=p)


def discovery_packet(data, key):
    payload=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
    return json.dumps(dict(data=data,signature=hmac.new(key.encode(),payload,'sha256').hexdigest())).encode()


def discovery_decode(packet, key):
    if len(packet)>2048:raise ValueError('Paquete demasiado grande')
    envelope=json.loads(packet)
    data=envelope['data']
    payload=json.dumps(data,sort_keys=True,separators=(',',':')).encode()
    expected=hmac.new(key.encode(),payload,'sha256').hexdigest()
    if not hmac.compare_digest(envelope.get('signature',''),expected):raise ValueError('Firma inválida')
    return data


def respond_discovery(key, port, stop):
    """Responder únicamente a solicitudes firmadas. No enviar la clave por UDP."""
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        try:sock.bind(('0.0.0.0',8766))
        except OSError as e:
            print(f'Descubrimiento Wi-Fi no disponible: {e}. Cierra otras centrales.',flush=True);return
        sock.settimeout(.5)
        while not stop.is_set():
            try:
                packet,address=sock.recvfrom(2048)
                if ipaddress.ip_address(address[0]) not in ipaddress.ip_network('10.42.0.0/24'):continue
                data=discovery_decode(packet,key)
                if data.get('kind')!='discover' or not isinstance(data.get('nonce'),str) or len(data['nonce'])!=32:continue
                sock.sendto(discovery_packet(dict(kind='central',nonce=data['nonce'],port=port),key),address)
            except (socket.timeout,ValueError,TypeError,KeyError,OSError):
                continue


def find_central(key):
    nonce=secrets.token_hex(16)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
        sock.bind(('10.42.0.1',0))
        sock.settimeout(.8)
        sock.sendto(discovery_packet(dict(kind='discover',nonce=nonce),key),('10.42.0.255',8766))
        end=time.monotonic()+.8
        while time.monotonic()<end:
            packet,address=sock.recvfrom(2048)
            try:data=discovery_decode(packet,key)
            except (ValueError,TypeError,KeyError):continue
            if (data.get('kind')=='central' and data.get('nonce')==nonce and type(data.get('port')) is int
                    and 1024<=data['port']<=65535 and ipaddress.ip_address(address[0]) in ipaddress.ip_network('10.42.0.0/24')):
                return f'http://{address[0]}:{data["port"]}'
    return None


def run_pi(args, external_stop=None):
    key=key_file(args.token_file)
    folder=Path(args.data_dir);folder.mkdir(parents=True,exist_ok=True)
    lease=open(folder/'controller.lock','a')
    try:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('Ya existe un controlador activo en esta carpeta. Deténlo primero.')
    journal=Journal(folder/'raspberry.sqlite3'); device=journal.device_id()
    hw=Simulation() if args.simulate else Outputs(args.active_high,args.chip)
    stop=external_stop or threading.Event();lock=threading.RLock()
    shared=dict(latest=None, measured=None, last_reply=None, command=dict(mode='auto',effects=False,plan=DEFAULT), controller={},endpoint=None,discovered=0)
    threads=[];good=[None,None];good_at=[None,None]
    previous_samples=journal.history(device,1)
    if previous_samples:
        old=previous_samples[-1]
        for i,s in enumerate(old['sensors']):
            if number(s.get('display_cm')):
                good[i]=s['display_cm']
                age=max(0,time.time()-old['t'])+(s.get('held_age') or 0)
                good_at[i]=time.monotonic()-age
    def sensing():
        while not stop.is_set():
            started=time.monotonic()
            try:
                values=hw.measure()
            except Exception as e:
                values=[dict(cm=None,quality='error',raw=[],detail=str(e)) for _ in range(2)]
            now=time.monotonic()
            for i,s in enumerate(values):
                if s['quality']=='valida':
                    good[i],good_at[i]=s['cm'],now
                s.update(age=0,display_cm=good[i],held_age=None if good_at[i] is None else now-good_at[i],retained=s['quality']!='valida')
            sample=journal.append(device,dict(t=time.time(),sensors=values))
            with lock:
                shared['latest'],shared['measured']=sample,now
            print(' | '.join(f"Sensor {i+1}: {s['display_cm']} cm ({s['quality']})" for i,s in enumerate(values)),flush=True)
            stop.wait(max(0,1-(time.monotonic()-started)))
    def discover():
        while not stop.is_set():
            try:
                endpoint=find_central(key)
                if endpoint:
                    with lock:shared.update(endpoint=endpoint,discovered=time.monotonic())
            except OSError:pass
            stop.wait(2)
    def network():
        opener=build_opener(ProxyHandler({}));was=False;last_error=-100
        while not stop.is_set():
            start=time.monotonic()
            with lock:
                endpoint=args.central
                if endpoint=='auto':
                    endpoint=shared['endpoint'] if start-shared['discovered']<8 else None
                latest=json.loads(json.dumps(shared['latest']))
                if latest:
                    for s in latest['sensors']:
                        extra=start-shared['measured'];s['age']+=extra
                        if s['held_age'] is not None:s['held_age']+=extra
                body=dict(version=VERSION,device=device,samples=journal.pending(device),latest=latest,controller=shared['controller'],simulated=args.simulate)
            try:
                if not endpoint:raise ValueError('Esperando la central en Wi-Fi Oli-Semaforos')
                req=Request(endpoint.rstrip('/')+'/api/telemetry',data=json.dumps(body,allow_nan=False).encode(),
                            headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
                with opener.open(req,timeout=2) as res:data=json.load(res)
                cmd=command_valid(data)
                sent=max((s['seq'] for s in body['samples']),default=0)
                if type(data.get('ack')) is not int or data['ack'] != sent:
                    raise ValueError('Confirmación de lote inválida')
                journal.acknowledge(device,sent)
                with lock:shared.update(command=cmd,last_reply=time.monotonic())
                if not was:print('Central semafórica conectada.',flush=True)
                was=True
            except Exception as e:
                if was or start-last_error>=10:
                    print(f'Central no disponible: {e}',flush=True);last_error=start
                was=False
            stop.wait(max(0,.1-(time.monotonic()-start)))
    try:
        if not args.simulate and not args.confirmed_off:
            if input('Con bombillos sin alimentación, ¿los tres relés están apagados? Escribe SI: ').strip().lower()!='si':
                return
        for target in ((sensing,network,discover) if args.central=='auto' else (sensing,network)):
            t=threading.Thread(target=target,daemon=True);threads.append(t);t.start()
        m=Machine(hw,time.monotonic());previous=None
        while not stop.is_set():
            now=time.monotonic()
            with lock:last,cmd=shared['last_reply'],shared['command']
            m.tick(now,last is not None and now-last<=5,cmd)
            status=m.snapshot(time.monotonic())
            with lock:shared['controller']=status
            if (status['mode'],status['phase']) != previous:
                previous=status['mode'],status['phase'];print(f"FASE {status['phase']} | MODO {status['mode']}",flush=True)
            stop.wait(.01)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        try:hw.set_lights(set())
        finally:
            for t in threads:t.join(timeout=3)
            hw.close();lease.close()
        print('Salidas desactivadas. Controlador detenido.',flush=True)


def background(args):
    key_file(args.token_file)
    if not args.simulate:
        hw=Outputs(args.active_high,args.chip)
        try:
            print('Verifica con alimentación de bombillos desconectada. Los relés deben estar apagados.')
            if input('¿Están apagados los tres? Escribe SI: ').strip().lower()!='si':
                raise ValueError('Cancelado. Para polaridad invertida usa --active-high.')
        finally:hw.close()
    folder=Path(args.data_dir);folder.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable,'-u',str(Path(__file__).resolve()),'raspberry','--central',args.central,
         '--token-file',str(Path(args.token_file).resolve()),'--data-dir',str(folder.resolve()),'--chip',str(args.chip),'--confirmed-off']
    if args.active_high:cmd.append('--active-high')
    if args.simulate:cmd.append('--simulate')
    with open(folder/'central_semaforos.log','ab') as log:
        p=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    time.sleep(.8)
    if p.poll() is not None:raise ValueError('No arrancó. Revisa central_semaforos.log.')
    (folder/'central_semaforos.pid').write_text(str(p.pid))
    print(f'Controlador {VERSION} iniciado. PID {p.pid}. Registro: {folder / "central_semaforos.log"}')


def stop_controller(folder):
    pidfile=Path(folder)/'central_semaforos.pid'
    if not pidfile.exists():
        print('No hay PID guardado. Para primer plano usa Ctrl+C.');return
    pid=int(pidfile.read_text());proc=Path(f'/proc/{pid}/cmdline')
    if not proc.exists():
        print('Ya estaba detenido.');return
    cmd=proc.read_bytes().split(b'\0')
    if str(Path(__file__).resolve()).encode() not in cmd or b'raspberry' not in cmd:
        raise ValueError('El PID corresponde a otro proceso; no se detendrá.')
    os.kill(pid,signal.SIGTERM)
    print('Parada solicitada. Espera unos segundos antes de volver a arrancar.')


def run_central(args):
    key=key_file(args.token_file,True)
    if not (ROOT/'interfaz.html').exists() or not (ROOT/'logo.png').exists():
        raise ValueError('Falta interfaz.html o logo.png junto al Python. Copia todos los archivos del paquete.')
    folder=Path(args.data_dir);folder.mkdir(parents=True,exist_ok=True)
    state=Central(Journal(folder/'central.sqlite3'),args.title)
    class Server(ThreadingHTTPServer):
        allow_reuse_address=True
        daemon_threads=True
    try:server=Server((args.bind,args.port),http_handler(state,key))
    except OSError as e:
        raise ValueError(f'No se pudo abrir el puerto {args.port}: {e}. Comprueba si la central ya está abierta.')
    stop=threading.Event();server.timeout=.3;demo=None
    discovery=threading.Thread(target=respond_discovery,args=(key,args.port,stop),daemon=True)
    discovery.start()
    if args.demo:
        sim=argparse.Namespace(token_file=args.token_file,data_dir=str(folder/'demo'),simulate=True,
                               central=f'http://127.0.0.1:{args.port}',active_high=False,chip=0,confirmed_off=True)
        demo=threading.Thread(target=run_pi,args=(sim,stop),daemon=True);demo.start()
    print(f'Central semafórica {VERSION}: http://127.0.0.1:{args.port}',flush=True)
    print('Conserva esta terminal abierta. Historial guardado en central.sqlite3.',flush=True)
    if not args.no_browser:webbrowser.open(f'http://127.0.0.1:{args.port}')
    try:
        while not stop.is_set():server.handle_request()
    except KeyboardInterrupt:pass
    finally:
        stop.set()
        if demo:demo.join(timeout=4)
        discovery.join(timeout=1)
        server.server_close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='role',required=True)
    central=sub.add_parser('central')
    central.add_argument('--port',type=int,default=8765)
    central.add_argument('--bind',default='0.0.0.0')
    central.add_argument('--title',default=TITLE)
    central.add_argument('--demo',action='store_true')
    central.add_argument('--no-browser',action='store_true')
    pi=sub.add_parser('raspberry')
    pi.add_argument('--central',default='auto',help='auto para Wi-Fi directa o http://IP:8765 para red existente')
    pi.add_argument('--chip',type=int,default=0)
    pi.add_argument('--active-high',action='store_true')
    pi.add_argument('--background',action='store_true')
    pi.add_argument('--confirmed-off',action='store_true',help=argparse.SUPPRESS)
    pi.add_argument('--simulate',action='store_true')
    stop=sub.add_parser('detener')
    sub.add_parser('verificar',help='Comprobar relés apagados antes de instalar el arranque automático')
    for p in (central,pi,stop):
        p.add_argument('--data-dir',default=str(ROOT))
    for p in (central,pi):p.add_argument('--token-file',default=str(KEY))
    args=parser.parse_args()
    signal.signal(signal.SIGTERM,lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if args.role=='central':run_central(args)
        elif args.role=='detener':stop_controller(args.data_dir)
        elif args.role=='verificar':
            hw=Outputs()
            try:
                if input('Con bombillos sin alimentación, ¿los tres relés están apagados? Escribe SI: ').strip().lower()!='si':
                    raise ValueError('Comprobación cancelada; no se instalará el arranque automático.')
            finally:hw.close()
        elif args.background:background(args)
        else:run_pi(args)
    except KeyboardInterrupt:pass
    except Exception as e:
        print(f'ERROR: {e}',file=sys.stderr);sys.exit(1)


if __name__=='__main__':main()
