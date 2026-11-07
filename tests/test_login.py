import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from web.game_login import enter_game
from web.catalog import Catalog
from web.manager import Manager


class LoginSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, code, report, **kwargs):
        script=self.root/'login_child.py';script.write_text('import sys,json,time\njson.loads(sys.stdin.readline())\n'+code,encoding='utf-8')
        popen=subprocess.Popen
        with patch('web.game_login.subprocess.Popen',side_effect=lambda command,**options:popen([sys.executable,'-u',str(script)],**options)):
            return enter_game({},self.root/'run',report,**kwargs)

    def test_reports_child_stages_before_completion(self):
        phases=[]
        code="print('@@LOGIN@@'+json.dumps({'event':'phase','message':'正在关闭福利'}),flush=True)\ntime.sleep(.1)\nprint('@@LOGIN@@'+json.dumps({'success':True}),flush=True)\n"
        self.assertTrue(self.run_script(code,phases.append))
        self.assertIn('正在关闭福利',phases)
        self.assertIn('已登录',phases[-1])

    def test_failure_preserves_reason_and_output(self):
        code="print('@@LOGIN@@'+json.dumps({'success':False,'message':'福利关闭失败'}),flush=True)\nsys.exit(1)\n"
        with self.assertRaisesRegex(ValueError,'福利关闭失败'):
            self.run_script(code,lambda _:None)
        self.assertIn('@@LOGIN@@',(self.root/'run/login-output.log').read_text())

    def test_stop_interrupts_login_child(self):
        stop=threading.Event()
        def report(message):
            if message=='child running':stop.set()
        code="print('@@LOGIN@@'+json.dumps({'event':'phase','message':'child running'}),flush=True)\ntime.sleep(120)\n"
        with self.assertRaisesRegex(ValueError,'已取消'):
            self.run_script(code,report,stopping=stop)

    def test_cancelled_login_never_starts_child(self):
        stop=threading.Event();stop.set()
        with patch('web.game_login.subprocess.Popen') as child,self.assertRaisesRegex(ValueError,'已取消'):
            enter_game({},self.root,lambda _:None,stopping=stop)
        child.assert_not_called()

    def test_native_boot_is_distinct_from_failed_scene_login(self):
        manager=Manager(self.root/'manager',Catalog())
        key=manager.import_mumu({'name':'测试','address':'127.0.0.1:5555','adb_path':'adb',
            'mumu':{'app_path':'/test/MuMuPlayer.app','index':1}})['id']
        with patch('web.mumu.MuMu') as factory,patch('web.game_login.enter_game',side_effect=ValueError('福利未关闭')):
            emulator=factory.return_value
            emulator.ensure_running.return_value='127.0.0.1:5555';emulator.launch_game.return_value=True
            emulator.discover.return_value=[{'mumu':{'index':1},'state':'running'}]
            with self.assertRaisesRegex(ValueError,'福利未关闭'):manager.set_power(key,True)
            power=manager.list_with_power()[0]['power']
        self.assertTrue(power['on'])
        self.assertEqual(power['scene_status'],'error')
        self.assertIn('福利未关闭',power['phase'])
        self.assertFalse(manager.power_operations)
        manager.close()
