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
from web.catalog import Catalog
from web.manager import Manager


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.manager=Manager(self.root,Catalog())
        self.profile={'name':'日常组合','resource':'官服','tasks':[
            {'name':'福利签到','options':{}},
            {'name':'师门任务','options':{'师门任务模式':'Yes'}}]}

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def device(self,port):
        return self.manager.add({'name':f'角色{port}','address':f'127.0.0.1:{port}','adb_path':'adb'})['id']

    def test_shared_profile_persistence_assignment_and_independent_duplicate(self):
        profile=self.manager.save_profile(None,self.profile)
        keys=[self.device(port) for port in (5555,5556)]
        for key in keys:self.manager.assign_profile(key,profile['id'])
        self.assertEqual([d['tasks'] for d in self.manager.list()],[self.profile['tasks']]*2)
        self.assertEqual(len(self.manager.list_profiles()[0]['devices']),2)
        changed={**self.profile,'name':'新版日常','tasks':[{'name':'宝图任务'}]}
        updated=self.manager.save_profile(profile['id'],changed,profile['version'])
        self.assertEqual(updated['version'],2)
        self.assertTrue(all(d['profile_name']=='新版日常' for d in self.manager.list()))
        self.assertTrue(all(d['tasks']==changed['tasks'] for d in self.manager.list()))
        copied=self.manager.duplicate_profile(profile['id'])
        self.manager.save_profile(copied['id'],{**copied,'tasks':[{'name':'师门任务'}]},copied['version'])
        self.assertEqual(self.manager.profiles[profile['id']]['tasks'],changed['tasks'])
        self.assertEqual(Manager(self.root,Catalog()).list()[0]['tasks'],changed['tasks'])
        with self.assertRaisesRegex(ValueError,'正在被'):self.manager.delete_profile(profile['id'])
        for key in keys:self.manager.assign_profile(key,None)
        self.assertTrue(all(not d['tasks'] and d['resource']=='官服' for d in self.manager.list()))
        self.manager.delete_profile(profile['id'])
        self.assertNotIn(profile['id'],self.manager.profiles)

    def test_invalid_and_stale_edits_do_not_change_saved_profile(self):
        profile=self.manager.save_profile(None,self.profile)
        for payload in ({**self.profile,'name':'  '},{**self.profile,'tasks':[]},
                        {**self.profile,'tasks':[{'name':'not-a-task'}]}):
            with self.assertRaises(ValueError):self.manager.save_profile(profile['id'],payload)
        with self.assertRaisesRegex(ValueError,'名称已存在'):self.manager.save_profile(None,self.profile)
        self.manager.save_profile(profile['id'],{**self.profile,'name':'已更新'},1)
        with self.assertRaisesRegex(ValueError,'已被其他操作更新'):
            self.manager.save_profile(profile['id'],self.profile,1)
        self.assertEqual(self.manager.profiles[profile['id']]['name'],'已更新')
        key=self.device(5555)
        before=dict(self.manager.devices[key])
        with self.assertRaises(ValueError):self.manager.update_settings(key,{'name':' ','resource':'官服'})
        self.assertEqual(self.manager.devices[key],before)

    def test_existing_device_combinations_migrate_once_without_losing_options(self):
        devices={str(i):{'id':str(i),'name':f'旧角色{i}','resource':'官服','tasks':self.profile['tasks'],
                          'address':f'127.0.0.1:{5555+i}','adb_path':'adb'} for i in range(2)}
        devices['empty']={'id':'empty','name':'仅打开游戏','resource':'九游','tasks':[],
                          'address':'127.0.0.1:5557','adb_path':'adb'}
        (self.root/'devices.json').write_text(json.dumps(devices),encoding='utf-8')
        migrated=Manager(self.root,Catalog())
        self.assertEqual(len(migrated.profiles),1)
        rows=migrated.list()
        self.assertEqual(rows[0]['tasks'],self.profile['tasks'])
        self.assertEqual(rows[0]['profile_id'],rows[1]['profile_id'])
        self.assertFalse(rows[2].get('profile_id'))
        again=Manager(self.root,Catalog())
        self.assertEqual(len(again.profiles),1)
        self.assertEqual(again.list()[0]['profile_id'],rows[0]['profile_id'])

    def test_running_queue_is_snapshot_and_next_run_uses_updated_profile(self):
        profile=self.manager.save_profile(None,self.profile)
        keys=[self.device(port) for port in (5555,5556)]
        for key in keys:self.manager.assign_profile(key,profile['id'])
        worker=self.root/'snapshot_worker.py'
        worker.write_text('import sys,json,pathlib\nc=json.loads(sys.stdin.readline())\npathlib.Path(c["device"]["id"]+".json").write_text(json.dumps(c))\nprint("snapshot saved",flush=True)\nsys.stdin.readline()\nprint(\'@@WEB@@{"kind":"status","status":"stopped"}\',flush=True)\n',encoding='utf-8')
        popen=subprocess.Popen
        def launch(command,**kwargs):
            kwargs['cwd']=self.root
            return popen([sys.executable,'-u',str(worker)],**kwargs)
        try:
            with patch('web.manager.subprocess.Popen',side_effect=launch):
                self.manager.start(keys[0])
                with self.assertRaisesRegex(ValueError,'停止实例'):
                    self.manager.assign_profile(keys[0],None)
                self.manager.save_profile(profile['id'],{**self.profile,'tasks':[{'name':'宝图任务'}]},1)
                self.manager.start(keys[1])
                deadline=time.monotonic()+3
                while not all((self.root/(key+'.json')).exists() for key in keys) and time.monotonic()<deadline:time.sleep(.01)
                # Wait for the logging message, which follows the completed file write.
                while not all(self.manager.logs(key)['logs'] for key in keys) and time.monotonic()<deadline:time.sleep(.01)
                first=json.loads((self.root/(keys[0]+'.json')).read_text())
                second=json.loads((self.root/(keys[1]+'.json')).read_text())
                self.assertEqual([t['name'] for t in first['plan']],['福利签到','师门任务'])
                self.assertEqual([t['name'] for t in second['plan']],['宝图任务'])
                self.assertEqual(first['device']['profile_version'],1)
                self.assertEqual(second['device']['profile_version'],2)
                self.assertEqual(self.manager.snapshot(keys[0])['total'],2)
        finally:self.manager.close()

    def test_profile_api_workflow_auth_assignment_and_used_delete_guard(self):
        headers={'Authorization':'Bearer test-only-access-token'}
        with TestClient(create_app(self.root/'api','test-only-access-token')) as client:
            self.assertEqual(client.get('/api/profiles').status_code,401)
            response=client.post('/api/profiles',json=self.profile,headers=headers)
            self.assertEqual(response.status_code,200)
            profile=response.json()
            device=client.post('/api/devices',headers=headers,json={'name':'月宫','address':'127.0.0.1:5555','adb_path':'adb'}).json()
            assign=f'/api/devices/{device["id"]}/profile'
            self.assertEqual(client.put(assign,headers=headers,json={'profile_id':profile['id']}).status_code,200)
            rows=client.get('/api/devices',headers=headers).json()
            self.assertEqual(rows[0]['profile_name'],'日常组合')
            self.assertEqual(rows[0]['tasks'],self.profile['tasks'])
            self.assertEqual(client.patch(f'/api/devices/{device["id"]}/settings',headers=headers,json={'name':'已改名','resource':'九游'}).status_code,400)
            copied=client.post(f'/api/profiles/{profile["id"]}/duplicate',headers=headers,json={})
            self.assertEqual(copied.status_code,200)
            self.assertEqual(client.delete(f'/api/profiles/{profile["id"]}',headers=headers).status_code,400)
            self.assertEqual(client.put(assign,headers=headers,json={'profile_id':None}).status_code,200)
            self.assertEqual(client.delete(f'/api/profiles/{profile["id"]}',headers=headers).status_code,200)
            self.assertEqual(client.put(assign,headers=headers,json={'profile_id':profile['id']}).status_code,404)


if __name__=='__main__':unittest.main()
