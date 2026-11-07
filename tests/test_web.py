"""Run with: python -m unittest discover -s tests -v (requires httpx)."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.app import create_app
from web.catalog import Catalog, merge
from web.manager import Manager


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()

    def test_nested_options_and_typed_inputs(self):
        plan = self.catalog.compile([{'name':'秘境降妖', 'options':{'海底秘境模式':'日月之井', '秘境-日月-结束关卡':'第18关'}}])
        self.assertEqual(plan[0]['pipeline_override']['日月之井-指定关卡结束任务']['custom_recognition_param']['expression'], '{日月之井-关卡识别}>=18')
        plan = self.catalog.compile([{'name':'工坊考古', 'options':{'考古次数':{'考古几轮':'3'}}}])
        self.assertEqual(plan[0]['pipeline_override']['考古次数']['max_hit'], 3)

    def test_input_does_not_interpret_quotes_or_json(self):
        text = '甲"\\\n{队员2}'
        plan = self.catalog.compile([{'name':'邀请队员','options':{'邀请队员':{'队员1':text}}}])
        self.assertEqual(plan[0]['pipeline_override']['邀请队员-输入队员名称1']['input_text'], text)

    def test_invalid_task_case_and_integer(self):
        for tasks in ([], [{'name':'not-a-task'}], [{'name':'师门任务','options':{'师门任务模式':'invalid'}}],
                      [{'name':'工坊考古','options':{'考古次数':{'考古几轮':'bad'}}}]):
            with self.assertRaises(ValueError):
                self.catalog.compile(tasks)

    def test_recursive_merge_retains_siblings_and_does_not_mutate_source(self):
        patch = {'node': {'next':['new']}}
        result = merge({'node':{'enabled':True,'next':['old']}}, patch)
        self.assertEqual(result, {'node':{'enabled':True,'next':['new']}})
        result['node']['next'].append('extra')
        self.assertEqual(patch['node']['next'], ['new'])

    def test_all_resources_have_models_and_task_entries_exist(self):
        for name in self.catalog.resources:
            nodes = {}
            for directory in self.catalog.resource_paths(name):
                self.assertTrue(directory.is_dir())
                for path in (directory / 'pipeline').rglob('*.json'):
                    nodes.update(json.loads(path.read_text(encoding='utf-8')))
            for task in self.catalog.tasks.values():
                if task.get('execution') == 'web_teamup':
                    continue
                self.assertIn(task['entry'], nodes, task['name'])


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp.name, 'test-only-access-token')
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.headers = {'Authorization':'Bearer test-only-access-token'}

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def add(self, address='127.0.0.1:5555'):
        result = self.client.post('/api/devices', headers=self.headers,
                                  json={'name':'测试号','address':address,'adb_path':'/missing/adb'})
        self.assertEqual(result.status_code, 200)
        return result.json()['id']

    def test_access_and_origin(self):
        self.assertEqual(self.client.get('/api/devices').status_code,401)
        self.assertEqual(self.client.get('/api/devices',headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.client.get('/api/catalog',headers=self.headers).status_code,200)

    def test_profile_roundtrip_duplicate_and_invalid_task(self):
        key = self.add()
        self.assertEqual(self.client.post('/api/devices',headers=self.headers,json={'name':'重复','address':'127.0.0.1:5555','adb_path':'adb'}).status_code,400)
        profile = {'name':'改名','resource':'官服','tasks':[{'name':'师门任务','options':{'师门任务模式':'Yes'}}]}
        self.assertEqual(self.client.put('/api/devices/'+key,headers=self.headers,json=profile).status_code,200)
        reloaded = Manager(self.temp.name, Catalog())
        self.assertEqual(reloaded.devices[key]['tasks'],profile['tasks'])
        profile['tasks'] = [{'name':'invalid'}]
        self.assertEqual(self.client.put('/api/devices/'+key,headers=self.headers,json=profile).status_code,400)
        self.assertEqual(self.client.get('/api/devices/'+key+'/screenshot',headers=self.headers).status_code,503)
        self.assertEqual(self.client.delete('/api/devices/'+key,headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/devices/'+key+'/logs',headers=self.headers).status_code,404)

    def test_version_endpoint_exposes_build_and_kernel(self):
        body = self.client.get('/api/version', headers=self.headers).json()
        self.assertIn('kernel', body)
        self.assertIn('local', body)
        self.assertIsInstance(body['local']['dirty'], bool)
        self.assertEqual(self.client.get('/api/version').status_code, 401)

    def test_device_count_is_capped_at_ten(self):
        for index in range(10):
            self.add(f'127.0.0.1:{6000 + index}')
        result = self.client.post('/api/devices', headers=self.headers,
                                  json={'name':'溢出','address':'127.0.0.1:7000','adb_path':'/missing/adb'})
        self.assertEqual(result.status_code, 400)
        self.assertIn('10', result.json()['detail'])
        self.assertEqual(len(self.client.get('/api/devices', headers=self.headers).json()), 10)

    def test_activity_endpoint_reads_records_and_filters(self):
        directory = Path(self.temp.name) / 'activity'
        record = {'id':'run-1','device_id':'dev-a','device_name':'月宫','profile_name':'日常',
                  'profile_version':1,'status':'completed',
                  'started_at':'2026-11-06T09:00:00+00:00','finished_at':'2026-11-06T09:10:00+00:00',
                  'tasks':[{'name':'师门任务','entry':'shimen_renwu','status':'completed',
                            'started_at':'2026-11-06T09:00:00+00:00',
                            'finished_at':'2026-11-06T09:02:30+00:00','seconds':150.0}]}
        (directory / 'run-1.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        runs = self.client.get('/api/activity', headers=self.headers).json()['runs']
        self.assertEqual(runs[0]['tasks'][0]['seconds'], 150.0)
        self.assertEqual(self.client.get('/api/activity?device=other', headers=self.headers).json()['runs'], [])
        self.assertEqual(self.client.get('/api/activity?device=dev-a', headers=self.headers).json()['runs'][0]['id'], 'run-1')
        self.assertEqual(self.client.get('/api/activity?limit=0', headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get('/api/activity').status_code, 401)

    def test_empty_start_and_partial_batch_errors(self):
        key = self.add()
        self.assertEqual(self.client.post('/api/devices/'+key+'/start',headers=self.headers).status_code,400)
        result=self.client.post('/api/batch',headers=self.headers,json={'ids':[key,'missing'],'action':'start'}).json()
        self.assertEqual([x['ok'] for x in result],[False,False])


class SupervisorTests(unittest.TestCase):
    def test_two_workers_duplicate_guard_stop_and_cleanup(self):
        # Real subprocesses exercise concurrent pipe handling and stop supervision,
        # while avoiding any dependency on a connected game/emulator.
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Catalog())
            keys = [manager.add({'name':'测试','address':f'127.0.0.1:{port}','adb_path':'adb'})['id'] for port in (5555,5556)]
            for key in keys:
                manager.update(key, {'name':'测试','resource':'官服','tasks':[{'name':'师门任务'}]})
            worker = Path(directory)/'test_worker.py'
            worker.write_text('import sys,json\njson.loads(sys.stdin.readline())\nprint(\'@@WEB@@{"kind":"progress","current":1,"total":1,"task":"测试"}\',flush=True)\nsys.stdin.readline()\nprint(\'@@WEB@@{"kind":"status","status":"stopped"}\',flush=True)\n',encoding='utf-8')
            popen = subprocess.Popen
            def launch(command, **kwargs):
                return popen([sys.executable,'-u',str(worker)], **kwargs)
            try:
                with patch('web.manager.subprocess.Popen', side_effect=launch):
                    for key in keys:
                        manager.start(key)
                    with self.assertRaises(ValueError):
                        manager.start(keys[0])
                    with self.assertRaises(ValueError):
                        manager.delete(keys[0])
                    manager.stop(keys[0])
                    manager.close()
                deadline = time.monotonic()+3
                while any(manager.snapshot(k)['status'] != 'stopped' for k in keys) and time.monotonic()<deadline:
                    time.sleep(.01)
                for key in keys:
                    self.assertFalse(manager.active(key))
                    self.assertEqual(manager.snapshot(key)['status'],'stopped')
                    self.assertTrue(manager.logs(key)['logs'])
            finally:
                manager.close()


    def test_activity_record_tracks_each_task(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Catalog())
            key = manager.add({'name':'魔王寨','address':'127.0.0.1:5555','adb_path':'adb'})['id']
            manager.update(key, {'name':'魔王寨','resource':'官服',
                                 'tasks':[{'name':'师门任务'},{'name':'三界奇缘'}]})
            worker = Path(directory)/'activity_worker.py'
            worker.write_text(
                'import sys,json,time\n'
                'json.loads(sys.stdin.readline())\n'
                'print(\'@@WEB@@{"kind":"progress","current":1,"total":2,"task":"师门任务"}\',flush=True)\n'
                'time.sleep(.08)\n'
                'print(\'@@WEB@@{"kind":"progress","current":2,"total":2,"task":"三界奇缘"}\',flush=True)\n'
                'time.sleep(.05)\n'
                'print(\'@@WEB@@{"kind":"status","status":"completed"}\',flush=True)\n',
                encoding='utf-8')
            popen = subprocess.Popen
            def launch(command, **kwargs):
                return popen([sys.executable,'-u',str(worker)], **kwargs)
            try:
                with patch('web.manager.subprocess.Popen', side_effect=launch):
                    manager.start(key)
                    deadline = time.monotonic()+5
                    while not manager.snapshot(key).get('finished_at') and time.monotonic() < deadline:
                        time.sleep(.01)
                records = manager.activity()
                self.assertEqual(records[0]['status'], 'completed')
                self.assertEqual([task['status'] for task in records[0]['tasks']], ['completed', 'completed'])
                self.assertGreaterEqual(records[0]['tasks'][0]['seconds'], .05)
                self.assertTrue(list((Path(directory)/'activity').glob('*.json')))
                self.assertEqual(manager.activity(device='other'), [])
            finally:
                manager.close()

    def test_unresponsive_worker_and_child_are_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = Manager(directory, Catalog())
            key = manager.add({'name':'测试','address':'127.0.0.1:5555','adb_path':'adb'})['id']
            manager.update(key, {'name':'测试','resource':'官服','tasks':[{'name':'师门任务'}]})
            worker = Path(directory)/'unresponsive.py'
            worker.write_text('import sys,subprocess,time\nsys.stdin.readline()\nsubprocess.Popen([sys.executable,"-c","import time;time.sleep(300)"])\nprint("ready",flush=True)\ntime.sleep(300)\n', encoding='utf-8')
            popen = subprocess.Popen
            def launch(command, **kwargs):
                return popen([sys.executable,'-u',str(worker)], **kwargs)
            try:
                with patch('web.manager.subprocess.Popen', side_effect=launch), patch('web.manager.STOP_GRACE_SECONDS', .2):
                    manager.start(key)
                    deadline = time.monotonic()+3
                    while not manager.logs(key)['logs'] and time.monotonic()<deadline:
                        time.sleep(.01)
                    manager.close()
                    deadline = time.monotonic()+3
                    while manager.snapshot(key)['status'] != 'stopped' and time.monotonic()<deadline:
                        time.sleep(.01)
                    self.assertFalse(manager.active(key))
                    # EOF on inherited stdout also proves the nested child was killed.
                    self.assertEqual(manager.snapshot(key)['status'],'stopped')
                    self.assertIn('finished_at', manager.snapshot(key))
            finally:
                manager.close()


class VersionTests(unittest.TestCase):
    def test_version_key_orders_tags(self):
        from web.version import _version_key
        self.assertLess(_version_key('v3.0.15'), _version_key('v3.0.16'))
        self.assertIsNone(_version_key('dev-build'))

    def test_fast_forward_update_in_temporary_repository(self):
        import shutil
        from web import version
        if not shutil.which('git'):
            self.skipTest('git 不可用')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def run(cwd, *args):
                return subprocess.run(['git', '-C', str(cwd), *args], check=True,
                                      capture_output=True, text=True)
            def run_global(*args):
                return subprocess.run(['git', *args], check=True, capture_output=True, text=True)
            origin = root/'origin.git'
            run_global('init', '--bare', '-q', str(origin))
            work = root/'work'
            run_global('init', '-q', str(work))
            run(work, 'branch', '-M', 'main')
            (work/'a.txt').write_text('1', encoding='utf-8')
            run(work, 'add', '.')
            run(work, '-c', 'user.email=a@b', '-c', 'user.name=t', 'commit', '-qm', 'one')
            run(work, 'remote', 'add', 'origin', str(origin))
            run(work, 'push', '-q', '-u', 'origin', 'main')
            other = root/'other'
            run_global('clone', '-q', str(origin), str(other))
            (other/'b.txt').write_text('2', encoding='utf-8')
            run(other, 'add', '.')
            run(other, '-c', 'user.email=a@b', '-c', 'user.name=t', 'commit', '-qm', 'two')
            run(other, 'push', '-q')
            original_root = version.ROOT
            version.ROOT = work
            try:
                result = version.apply_update()
                self.assertTrue(result['changed'])
                self.assertTrue((work/'b.txt').is_file())
            finally:
                version.ROOT = original_root


class NetworkTests(unittest.TestCase):
    def test_local_network_only_allows_loopback_and_private(self):
        from web.app import local_network
        for host in ('127.0.0.1', '192.168.1.20', '10.0.0.5', '172.16.3.4', '::1', '::ffff:192.168.1.9'):
            self.assertTrue(local_network(host), host)
        for host in ('8.8.8.8', '1.1.1.1', '2606:4700:4700::1111', 'testclient', ''):
            self.assertFalse(local_network(host), host)

    def test_health_and_stream_are_gated_by_peer_address(self):
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory), 'test-only-access-token')
            headers = {'Authorization': 'Bearer test-only-access-token'}
            with TestClient(app, client=('8.8.8.8', 5000)) as client:
                self.assertFalse(client.get('/health').json()['monitor'])
                self.assertEqual(client.get('/api/devices/any/stream', headers=headers).status_code, 403)
            with TestClient(app, client=('127.0.0.1', 5000)) as client:
                self.assertTrue(client.get('/health').json()['monitor'])


if __name__ == '__main__':
    unittest.main()
