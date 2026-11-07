import tempfile
from pathlib import Path
import unittest
import central_semaforos as c


def sensor(cm,quality='valida'):
    return dict(cm=cm,quality=quality,age=0,display_cm=cm,held_age=0,raw=[cm]*3)


class Control(unittest.TestCase):
    def test_discovery_authentication(self):
        from unittest.mock import patch, MagicMock
        key='a'*48
        data=dict(kind='central',nonce='b'*32,port=8765)
        packet=c.discovery_packet(data,key)
        self.assertEqual(c.discovery_decode(packet,key),data)
        with self.assertRaises(ValueError):c.discovery_decode(packet,'wrong-key')
        fake=MagicMock();fake.__enter__.return_value=fake
        # Un anuncio viejo con otro desafío no debe determinar el destino.
        stale=c.discovery_packet(dict(data,nonce='c'*32),key)
        fake.recvfrom.side_effect=[(stale,('10.42.0.99',8766)),(packet,('10.42.0.2',8766))]
        with patch.object(c.socket,'socket',return_value=fake),patch.object(c.secrets,'token_hex',return_value='b'*32):
            self.assertEqual(c.find_central(key),'http://10.42.0.2:8765')
        fake.bind.assert_called_with(('10.42.0.1',0))

    def test_sensor_boundaries_and_scenarios(self):
        for cm,expected in [(None,(8,2)),(1,(8,2)),(5,(6,3)),(10,(6,3)),(11,(4,6)),(30,(4,6)),(31,(3,10)),(250,(3,10)),(401,(8,2))]:
            p=c.base_plan(sensor(cm));self.assertEqual((p['red'],p['green']),expected)
        p,_=c.decide([sensor(40),sensor(20)],'mucho',0);self.assertEqual((p['red'],p['green']),(3,12))
        p,_=c.decide([sensor(40),sensor(20)],'poco',0);self.assertEqual((p['red'],p['green']),(8,3))
        a,_=c.decide([sensor(20),sensor(20)],'ia',0)
        b,_=c.decide([sensor(20),sensor(100)],'ia',0)
        self.assertGreater(b['red'],a['red']);self.assertLess(b['green'],a['green'])
        congested,_=c.decide([sensor(100),sensor(20)],'ia',28)
        self.assertEqual((congested['red'],congested['green']),(10,2))
        invalid=sensor(100,'inestable');p,_=c.decide([invalid,sensor(20)],'mucho',0)
        self.assertEqual(p,c.DEFAULT)

    def test_cycle_and_effect_schedule(self):
        hw=c.Simulation();m=c.Machine(hw,0)
        cmd=dict(mode='auto',effects=False,plan=dict(red=3,green=6))
        m.tick(0,True,cmd);self.assertEqual(m.lights,{'rojo'})
        m.tick(3,True,cmd);self.assertEqual(m.lights,{'rojo','amarillo'})
        m.tick(4,True,cmd);self.assertEqual(m.lights,{'verde'})
        cmd['plan']=dict(red=8,green=2);m.tick(5,True,cmd);self.assertEqual(m.deadline,10)
        cmd['mode']='schoringer';m.tick(6,True,cmd);self.assertEqual(m.mode,'auto')
        cmd['effects']=True;m.tick(6,True,cmd);self.assertEqual(m.lights,{'rojo','verde'})
        cmd['mode']='rumba'
        for t,expected in [(7,{'rojo','amarillo','verde'}),(7.25,set()),(7.5,{'rojo','amarillo','verde'}),(9.75,set()),
                           (10,{'rojo'}),(10.5,{'amarillo'}),(11,{'verde'}),(11.5,{'rojo'}),(12,{'amarillo'}),(12.5,{'verde'}),
                           (13,{'rojo'}),(13.5,{'amarillo'}),(14,{'verde'}),(14.5,{'rojo','amarillo','verde'})]:
            m.tick(t,True,cmd);self.assertEqual(m.lights,expected,t)
        m.tick(15,False,cmd);self.assertEqual(m.lights,{'amarillo'})
        m.tick(16,False,cmd);self.assertEqual(m.lights,{'rojo'})
        m.tick(17,False,cmd);self.assertEqual(m.phase,'blink')
        cmd['mode']='auto';m.tick(18,True,cmd);self.assertEqual(m.lights,{'rojo'})
        cmd['mode']='blink';m.tick(19,True,cmd);self.assertEqual(m.lights,{'amarillo'})
        m.tick(19.5,True,cmd);self.assertEqual(m.lights,set())

    def test_durable_replay_and_hold(self):
        with tempfile.TemporaryDirectory() as folder:
            source=c.Journal(Path(folder)/'pi.db');device=source.device_id()
            destination=c.Journal(Path(folder)/'central.db');state=c.Central(destination)
            for seq in range(4):
                s=sensor(25) if seq<2 else dict(sensor(None,'sin_eco'),display_cm=25,held_age=seq-1)
                source.append(device,dict(t=100+seq,sensors=[s,sensor(60)]))
            batch=source.pending(device)
            payload=dict(version=c.VERSION,device=device,samples=batch,latest=batch[-1],controller={})
            answer=state.ingest(payload)
            state.ingest(payload)  # respuesta perdida => reenvío sin duplicados
            self.assertEqual(len(destination.history(device)),4)
            source.acknowledge(device,answer['ack']);self.assertEqual(source.pending(device),[])
            restored=c.Central(c.Journal(Path(folder)/'central.db'))
            snapshot=restored.snapshot()
            self.assertEqual(snapshot['sensors'][0]['display_cm'],25)
            self.assertEqual(snapshot['sensors'][0]['quality'],'desconectado')
            self.assertEqual(snapshot['history'][-1]['cm'][0],25)
            self.assertTrue(snapshot['history'][-1]['held'][0])
            self.assertEqual(snapshot['plan'],c.DEFAULT)
            with self.assertRaises(ValueError):state.control({'mode':'rumba'})
            state.control({'effects':True,'mode':'rumba'})
            state.control({'effects':False})
            self.assertEqual(state.mode,'auto')

    def test_normal_never_conflicts(self):
        import random
        random.seed(12);hw=c.Simulation();m=c.Machine(hw,0)
        for i in range(10000):
            cmd=dict(mode=random.choice(['auto']*99+['blink']),effects=False,plan=dict(red=3,green=10))
            m.tick(i/10,random.random()>.01,cmd)
            self.assertFalse({'rojo','verde'}<=m.lights)

    def test_network_backfill(self):
        import argparse, threading, time
        from http.server import ThreadingHTTPServer
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);keypath=root/'key';key=c.key_file(keypath,True)
            target=c.Journal(root/'central.db');state=c.Central(target)
            class Server(ThreadingHTTPServer):
                allow_reuse_address=True
                daemon_threads=True
            server=Server(('127.0.0.1',0),c.http_handler(state,key));port=server.server_port
            serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
            stop=threading.Event()
            args=argparse.Namespace(token_file=str(keypath),data_dir=str(root/'pi'),simulate=True,
                active_high=False,chip=0,confirmed_off=True,central=f'http://127.0.0.1:{port}')
            controller=threading.Thread(target=c.run_pi,args=(args,stop),daemon=True);controller.start()
            def wait(predicate, seconds=10):
                end=time.monotonic()+seconds
                while time.monotonic()<end:
                    if predicate():return
                    time.sleep(.1)
                self.fail('Tiempo de espera agotado')
            try:
                wait(lambda:state.snapshot()['connected'] and len(target.history(state.device))>=2)
                device=state.device
                before=target.history(device)[-1]['seq']
                server.shutdown();server.server_close();serving.join(timeout=2)
                time.sleep(6)
                source=c.Journal(root/'pi'/'raspberry.sqlite3')
                self.assertGreaterEqual(len(source.pending(device)),4)
                server=Server(('127.0.0.1',port),c.http_handler(state,key))
                serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
                wait(lambda:state.snapshot()['connected'] and target.history(device)[-1]['seq']>=before+5)
                wait(lambda:len(source.pending(device))==0)
                seqs=[s['seq'] for s in target.history(device)]
                self.assertEqual(seqs,list(range(seqs[0],seqs[-1]+1)))
                self.assertTrue(controller.is_alive())
            finally:
                stop.set();controller.join(timeout=5)
                server.shutdown();server.server_close();serving.join(timeout=2)


if __name__=='__main__':unittest.main()
