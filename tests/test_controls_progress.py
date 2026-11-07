import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from web.app import create_app
from web.catalog import Catalog
from web.manager import Manager
from web.progress import panel_progress


class ProgressTests(unittest.TestCase):
    def test_counts_from_current_task_only(self):
        result=panel_progress('师门任务(3/10)\n上交烹饪','师门任务')
        self.assertEqual((result['sub_current'],result['sub_total']),(3,10))
        self.assertEqual(result['detail_source'],'game_task_panel')
        self.assertIsNone(panel_progress('宝图任务 5/10','师门任务'))
        result=panel_progress('师门任务\n交给师父\n宝图任务 5/10','师门任务')
        self.assertIsNone(result['sub_current'])

    def test_zero_and_invalid_counts(self):
        self.assertEqual(panel_progress('师门任务0／10','师门任务')['sub_current'],0)
        for text in ['师门任务11/10','师门任务1/0','师门任务第5环']:
            result=panel_progress(text,'师门任务')
            self.assertIsNone(result['sub_total'])
            self.assertIn('师门',result['task_detail'])


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.manager=Manager(self.root,Catalog())
        self.key=self.manager.import_mumu({'name':'测试实例','address':'127.0.0.1:5555','adb_path':'adb',
                   'mumu':{'app_path':'/Applications/MuMuPlayer.app','index':5},'state':'stopped'})['id']

    def tearDown(self):
        self.manager.close();self.temp.cleanup()

    def test_power_open_and_close_use_selected_instance_only(self):
        with patch('web.mumu.MuMu') as factory, patch('web.game_login.enter_game',return_value=True) as login:
            mumu=factory.return_value
            mumu.ensure_running.return_value='127.0.0.1:5555'
            mumu.launch_game.return_value=True
            with patch('web.manager.time.sleep'):
                self.assertEqual(self.manager.set_power(self.key,True)['status'],'running')
            self.assertEqual(login.call_args.args[0]['address'],'127.0.0.1:5555')
            self.assertEqual(mumu.ensure_running.call_args.args[0],5)
            self.assertEqual(mumu.launch_game.call_args.args[:3],(5,'127.0.0.1:5555','com.netease.my'))
            mumu.command.assert_not_called()
            mumu.command.reset_mock();mumu.info.side_effect=[[{'state':'running'}],[{'state':'stopped'}]]
            with patch('web.manager.time.sleep'):
                self.assertFalse(self.manager.set_power(self.key,False)['on'])
            mumu.command.assert_called_once_with('close',5,timeout=20)
        self.assertFalse(self.manager.power_operations)

    def test_power_failure_clears_busy_and_start_is_blocked_during_shutdown(self):
        with patch('web.mumu.MuMu') as factory:
            factory.return_value.info.side_effect=ValueError('MuMu unavailable')
            with self.assertRaises(ValueError):self.manager.set_power(self.key,False)
        self.assertFalse(self.manager.power_operations)
        self.manager.power_operations[self.key]='stopping'
        with self.assertRaisesRegex(ValueError,'开关机'):self.manager.start(self.key)
        self.manager.power_operations.clear()

    def test_status_scan_is_read_only_and_reports_native_power(self):
        with patch('web.mumu.MuMu') as factory:
            factory.return_value.discover.return_value=[{'mumu':{'index':5},'state':'running'}]
            rows=self.manager.list_with_power()
            self.assertTrue(rows[0]['power']['on'])
            factory.return_value.discover.assert_called_once_with(open_manager=False)
            factory.return_value.command.assert_not_called()

    def test_old_resources_migrate_to_official_without_changing_tasks(self):
        old={'id':'legacy','name':'旧配置','resource':'官方混服','tasks':[{'name':'师门任务'}],
             'version':1,'created_at':'old','updated_at':'old'}
        (self.root/'profiles.json').write_text(json.dumps({'legacy':old}),encoding='utf-8')
        migrated=Manager(self.root,Catalog())
        self.assertEqual(migrated.profiles['legacy']['resource'],'官服')
        self.assertEqual(migrated.profiles['legacy']['tasks'],old['tasks'])
        self.assertEqual(migrated.profiles['legacy']['version'],2)
        self.assertTrue(all(d['resource']=='官服' for d in migrated.devices.values()))

    def test_api_profiles_default_to_official_and_empty_start_is_rejected(self):
        with TestClient(create_app(self.root/'api','test-only-access-token')) as client:
            headers={'Authorization':'Bearer test-only-access-token'}
            profile=client.post('/api/profiles',headers=headers,json={'name':'官方日常','tasks':[{'name':'师门任务'}]})
            self.assertEqual(profile.status_code,200)
            self.assertEqual(profile.json()['resource'],'官服')
            self.assertNotIn('resources',client.get('/api/catalog',headers=headers).json())
            manager=client.app.state.manager
            key=manager.import_mumu({'name':'测试','address':'127.0.0.1:5555','adb_path':'adb',
                                   'mumu':{'app_path':'test','index':5}})['id']
            self.assertEqual(client.post(f'/api/devices/{key}/start',headers=headers).status_code,400)
            with patch.object(manager,'set_power',return_value={'status':'stopped','on':False}) as power:
                response=client.put(f'/api/devices/{key}/power',headers=headers,json={'on':False})
                self.assertEqual(response.status_code,200)
                power.assert_called_once_with(key,False)


if __name__=='__main__':unittest.main()
