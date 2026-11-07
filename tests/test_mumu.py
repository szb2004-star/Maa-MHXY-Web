import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from web.app import create_app
from web.catalog import Catalog
from web.manager import Manager
from web.mumu import MuMu


class MuMuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = self.root / 'MuMuPlayer.app'
        for name in ('Contents/MacOS/mumutool','Contents/MacOS/MuMuEmulator.app/Contents/MacOS/tools/adb'):
            p = self.app / name
            p.parent.mkdir(parents=True,exist_ok=True)
            p.touch()
        self.vm = self.root/'data/vms/4/setting/vm.json'
        self.vm.parent.mkdir(parents=True)
        self.vm.write_text(json.dumps({'customAdbPort':23333}),encoding='utf-8')
        with patch('web.mumu.sys.platform','darwin'):
            self.mumu = MuMu(str(self.app),data_root=self.root/'data')
        self.row = {'index':4,'name':'角色四','state':'stopped'}

    def tearDown(self):
        self.temp.cleanup()

    def test_discover_stopped_instance_uses_configured_port(self):
        payload = {'errcode':0,'return':{'count':1,'results':[self.row]}}
        result = subprocess.CompletedProcess([],0,json.dumps(payload),'')
        with patch('web.mumu.subprocess.run',return_value=result) as command:
            device = self.mumu.discover()[0]
        self.assertEqual(device['address'],'127.0.0.1:23333')
        self.assertEqual(device['mumu']['index'],4)
        self.assertEqual(device['state'],'stopped')
        self.assertEqual(command.call_args.args[0][-2:], ['info','all'])

    def test_single_instance_info_is_not_wrapped_in_results(self):
        result = subprocess.CompletedProcess([],0,json.dumps({'errcode':0,'return':self.row}),'')
        with patch('web.mumu.subprocess.run',return_value=result):
            self.assertEqual(self.mumu.info(4),[self.row])

    def test_reported_port_and_missing_port_do_not_guess(self):
        self.assertEqual(self.mumu.port({**self.row,'adb_port':24444}),24444)
        self.vm.unlink()
        self.assertEqual(self.mumu.normalize(self.row)['address'],'')

    def test_launches_exact_instance_and_waits_for_android_boot(self):
        ready={**self.row,'state':'running','adb_port':24444}
        self.mumu.info=Mock(side_effect=[[self.row],[ready]])
        self.mumu.command=Mock(return_value={})
        with patch('web.mumu.subprocess.run',return_value=subprocess.CompletedProcess([],0,b'1\n',b'')) as adb:
            address=self.mumu.ensure_running(4,threading.Event(),lambda _:None)
        self.mumu.command.assert_called_once_with('open',4,timeout=20)
        self.assertEqual(address,'127.0.0.1:24444')
        self.assertEqual(adb.call_args.args[0][-4:],[address,'shell','getprop','sys.boot_completed'])

    def test_cancelled_launch_does_not_open_instance(self):
        stop=threading.Event(); stop.set()
        self.mumu.info=Mock()
        self.assertIsNone(self.mumu.ensure_running(4,stop,lambda _:None))
        self.mumu.info.assert_not_called()

    def test_timeout_reports_boot_problem(self):
        self.mumu.info=Mock(return_value=[{**self.row,'state':'running'}])
        with self.assertRaisesRegex(ValueError,'启动超时'):
            self.mumu.ensure_running(4,threading.Event(),lambda _:None,timeout=0)

    def test_import_idempotence_preserves_config_and_adopts_manual_device(self):
        manager=Manager(self.root/'web',Catalog())
        manual=manager.add({'name':'自定义名称','address':'127.0.0.1:23333','adb_path':'adb'})
        profile={'name':'自定义名称','resource':'官服','tasks':[{'name':'师门任务'}]}
        manager.update(manual['id'],profile)
        row=self.mumu.normalize(self.row)
        adopted=manager.import_mumu(row)
        self.assertEqual(adopted['id'],manual['id'])
        self.assertEqual(adopted['tasks'],profile['tasks'])
        self.assertEqual(manager.import_mumu(row)['id'],manual['id'])
        self.assertEqual(len(manager.devices),1)
        with self.assertRaisesRegex(ValueError,'相同的 ADB 端口'):
            manager.import_mumu({**row,'mumu':{**row['mumu'],'index':5}})

    def test_only_official_game_package_is_available(self):
        catalog=Catalog()
        self.assertEqual(catalog.game_package('官服'),'com.netease.my')
        self.assertEqual(list(catalog.resources),['官服'])
        with self.assertRaises(ValueError):catalog.game_package('九游')

    def test_launch_game_opens_installed_package_and_checks_landscape(self):
        self.mumu.adb_shell=Mock(return_value='package:/data/app/game/base.apk')
        self.mumu.game_in_foreground=Mock(side_effect=[False,True])
        self.mumu.screen_size=Mock(return_value=(1280,720))
        self.mumu.command=Mock(return_value={})
        messages=[]
        self.assertTrue(self.mumu.launch_game(4,'127.0.0.1:23333','com.netease.my',threading.Event(),messages.append))
        self.mumu.command.assert_called_once_with('control',4,'--action','open_app','--package','com.netease.my',timeout=20)
        self.assertIn('1280×720', messages[-1])

    def test_missing_game_and_portrait_screen_do_not_report_success(self):
        self.mumu.adb_shell=Mock(return_value='')
        self.mumu.command=Mock()
        with self.assertRaisesRegex(ValueError,'未安装'):
            self.mumu.launch_game(4,'127.0.0.1:23333','com.netease.my',threading.Event(),lambda _:None)
        self.mumu.command.assert_not_called()
        self.mumu.adb_shell.return_value='package:/data/app/game/base.apk'
        self.mumu.game_in_foreground=Mock(return_value=True)
        self.mumu.screen_size=Mock(return_value=(720,1280))
        with self.assertRaisesRegex(ValueError,'横屏就绪'):
            self.mumu.launch_game(4,'127.0.0.1:23333','com.netease.my',threading.Event(),lambda _:None,timeout=0)

    def test_foreground_match_requires_exact_game_package(self):
        self.mumu.adb_shell=Mock(return_value='mCurrentFocus=Window{123 u0 com.netease.my.uc/.MainActivity}')
        self.assertFalse(self.mumu.game_in_foreground('127.0.0.1:23333','com.netease.my'))
        self.assertTrue(self.mumu.game_in_foreground('127.0.0.1:23333','com.netease.my.uc'))
        self.mumu.adb_shell.assert_called_with('127.0.0.1:23333','dumpsys','window')

    def test_api_lists_and_imports_offline_instances(self):
        row=self.mumu.normalize(self.row)
        with patch('web.app.MuMu') as factory:
            factory.return_value.discover.return_value=[row]
            with TestClient(create_app(self.root/'api','test-only-access-token')) as client:
                headers={'Authorization':'Bearer test-only-access-token'}
                self.assertEqual(client.post('/api/mumu/discover',json={}).status_code,401)
                scan=client.post('/api/mumu/discover',json={},headers=headers).json()
                self.assertFalse(scan[0]['added'])
                imported=client.post('/api/mumu/import',json={'indexes':[4]},headers=headers)
                self.assertEqual(imported.status_code,200)
                self.assertEqual(imported.json()[0]['tasks'],[])
                scan=client.post('/api/mumu/discover',json={},headers=headers).json()
                self.assertTrue(scan[0]['added'])
                self.assertEqual(client.post('/api/mumu/import',json={'indexes':[9]},headers=headers).status_code,400)


if __name__=='__main__':
    unittest.main()
