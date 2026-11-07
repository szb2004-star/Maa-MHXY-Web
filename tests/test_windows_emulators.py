"""Recorded CLI shapes and end-to-end provider routing, without Windows binaries."""
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
from web.emulators import identity
from web.mumu import MuMu
from web.windows_emulators import LDPlayer, WindowsMuMu


class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / '中文 install with spaces'
        self.root.mkdir()
        self.root = self.root.resolve()
        for name in ('mumu-cli.exe', 'MuMuManager.exe', 'ldconsole.exe', 'adb.exe'):
            (self.root / name).touch()
        with patch('web.windows_emulators.sys.platform', 'win32'):
            self.mumu = MuMu(str(self.root))
            self.ld = LDPlayer(str(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def result(self, output):
        return subprocess.CompletedProcess([], 0, output, b'')

    def test_mumu_factory_and_live_port_not_index_formula(self):
        self.assertIsInstance(self.mumu, WindowsMuMu)
        payload = {'4': {'index': '4', 'name': '月宫', 'is_process_started': True,
                         'is_android_started': True, 'adb_port': 24444}}
        with patch('web.windows_emulators.subprocess.run', return_value=self.result(json.dumps(payload).encode())) as run:
            row = self.mumu.discover()[0]
        self.assertEqual(row['address'], '127.0.0.1:24444')
        self.assertEqual(row['emulator']['index'], 4)
        self.assertEqual(run.call_args.args[0], [str(self.root / 'mumu-cli.exe'), 'info', '--vmindex', 'all'])
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_stopped_mumu_has_no_guessed_port(self):
        self.mumu.run_cli = Mock(return_value=json.dumps({'index': '9', 'name': '停机', 'is_process_started': False}))
        row = self.mumu.discover()[0]
        self.assertEqual(row['state'], 'stopped')
        self.assertEqual(row['address'], '')

    def test_mumu_legacy_binary_and_json_envelopes(self):
        (self.root / 'mumu-cli.exe').unlink()
        with patch('web.windows_emulators.sys.platform', 'win32'):
            legacy = WindowsMuMu(str(self.root))
        self.assertEqual(legacy.tool.name, 'MuMuManager.exe')
        for data in ([{'index':'1','name':'一'}], {'return': {'results':[{'index':'1','name':'一'}]}}):
            legacy.run_cli = Mock(return_value=json.dumps(data))
            self.assertEqual(legacy.info(1)[0]['index'], 1)

    def test_ldplayer_chinese_names_commas_and_old_new_list2(self):
        output = '0,主号,0,0,0,-1,-1\r\n3,队员,测试,123,456,1,222,333,1280,720,240\r\n'
        with patch('web.windows_emulators.subprocess.run', return_value=self.result(output.encode('gb18030'))):
            rows = self.ld.discover()
        self.assertEqual([r['name'] for r in rows], ['主号', '队员,测试'])
        self.assertEqual(rows[1]['address'], '127.0.0.1:5561')
        self.assertEqual(rows[0]['state'], 'stopped')
        self.assertEqual(rows[1]['state'], 'running')

    def test_malformed_list_and_mumu_error_are_not_empty_success(self):
        for emulator, output in ((self.ld, '3,bad,broken'), (self.mumu, '{"error_code":12}'), (self.mumu, 'not json')):
            emulator.run_cli = Mock(return_value=output)
            with self.assertRaises(ValueError):
                emulator.discover()

    def test_boot_exact_instance_and_waits_for_adb_boot(self):
        self.ld.info = Mock(side_effect=[[
            {'index':3,'name':'队员','state':'stopped'}], [
            {'index':3,'name':'队员','state':'running','adb_port':5561}]])
        with patch('web.windows_emulators.subprocess.run', return_value=self.result(b'1\n')) as run:
            self.assertEqual(self.ld.ensure_running(3, threading.Event(), lambda _:None), '127.0.0.1:5561')
        calls = [c.args[0] for c in run.call_args_list]
        self.assertEqual(calls[0], [str(self.root / 'ldconsole.exe'), 'launch', '--index', '3'])
        self.assertEqual(calls[-1][-5:], ['-s','127.0.0.1:5561','shell','getprop','sys.boot_completed'])

    def test_both_vendors_shutdown_and_game_launch_only_target_instance(self):
        for emulator, close, game in (
            (self.mumu, ['control','--vmindex',2,'shutdown'], ['control','--vmindex',2,'app','launch','--package','com.netease.my']),
            (self.ld, ['quit','--index',2], ['runapp','--index',2,'--packagename','com.netease.my'])):
            emulator.run_cli = Mock(return_value='')
            emulator.command('close', 2)
            emulator.run_cli.assert_called_with(close, 10)
            emulator.adb_shell = Mock(return_value='package:/game.apk')
            emulator.game_in_foreground = Mock(side_effect=[False,True])
            emulator.screen_size = Mock(return_value=(1280,720))
            self.assertTrue(emulator.launch_game(2, '127.0.0.1:5559', 'com.netease.my', threading.Event(), lambda _:None))
            emulator.run_cli.assert_called_with(game, 20)

    def test_missing_bundled_adb_is_actionable(self):
        (self.root / 'adb.exe').unlink()
        with patch('web.windows_emulators.sys.platform', 'win32'), self.assertRaisesRegex(ValueError, 'adb.exe'):
            LDPlayer(str(self.root))

    def test_mac_rejects_windows_tool(self):
        with patch('web.windows_emulators.sys.platform', 'darwin'), self.assertRaisesRegex(ValueError, 'Windows'):
            LDPlayer(str(self.root))

    def test_api_vendor_qualified_imports_and_status(self):
        manager = Manager(Path(self.temp.name) / 'data', Catalog())
        rows = []
        for emulator in (self.mumu, self.ld):
            rows.append(emulator.normalize({'index':2,'name':'同名','state':'stopped'}))
        self.assertNotEqual(identity(rows[0]), identity(rows[1]))
        with TestClient(create_app(Path(self.temp.name) / 'api', None)) as client:
            for row in rows:
                factory = Mock(); factory.discover.return_value=[row]
                body = {'kind': row['emulator']['kind'], 'indexes':[2]}
                with patch('web.app.create_emulator', return_value=factory), patch('web.manager.create_emulator', return_value=factory):
                    response = client.post('/api/emulators/import', json=body)
                    self.assertEqual(response.status_code, 200, response.text)
                    again = client.post('/api/emulators/import', json=body).json()[0]
                    self.assertEqual(response.json()[0]['id'], again['id'])
                    self.assertTrue(client.post('/api/emulators/discover',json={'kind':body['kind']}).json()[0]['added'])
            self.assertEqual(client.post('/api/emulators/discover', json={'kind':'bad'}).status_code, 422)
        for row in rows:
            manager.import_mumu(row)
        self.assertEqual(len(manager.devices),2)
        with patch('web.manager.create_emulator') as factory:
            factory.return_value.discover.side_effect = [[rows[0]], [rows[1]]]
            result = manager.list_with_power()
        self.assertTrue(all(d['power']['supported'] for d in result))

    def test_manager_shutdown_routes_ldplayer_and_preserves_other_devices(self):
        manager = Manager(Path(self.temp.name) / 'power', Catalog())
        row = self.ld.normalize({'index':2,'name':'队员','state':'running','adb_port':5559})
        imported = manager.import_emulator(row)
        other = manager.import_emulator(self.mumu.normalize({'index':2,'name':'队长','state':'stopped'}))
        adapter = Mock()
        adapter.info.side_effect = [[{'index':2,'state':'running'}], [{'index':2,'state':'stopped'}]]
        with patch('web.manager.create_emulator', return_value=adapter) as create, patch('web.manager.time.sleep'):
            result = manager.set_power(imported['id'], False)
        self.assertFalse(result['on'])
        self.assertEqual(create.call_args.args[0]['kind'], 'ldplayer')
        adapter.command.assert_called_once_with('close',2,timeout=20)
        self.assertIn(other['id'],manager.devices)
        self.assertFalse(manager.power_operations)
