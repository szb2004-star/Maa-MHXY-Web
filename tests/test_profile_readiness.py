from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from fastapi.testclient import TestClient
from web.app import create_app
from web.catalog import Catalog, ASSETS
from web.manager import Manager
from web.readiness import probe_ready, scene_visible


def world_screen(overlay=None):
    image=Image.new('RGB',(1280,720),'#17283e')
    root=ASSETS/'resource/base/image'
    image.paste(Image.open(root/'zonghe/baoguo.png').convert('RGB'),(1200,600))
    if overlay:
        image.paste(Image.open(root/overlay).convert('RGB'),(440,30))
    stream=BytesIO();image.save(stream,'PNG');return stream.getvalue()


class ReadinessTests(unittest.TestCase):
    def row(self,**extra):
        return {'id':'one','adb_path':'/path with spaces/adb','address':'127.0.0.1:5555',
                'run':{'active':False},'power':{'supported':True,'on':True,'status':'running'},**extra}

    def result(self, output=b'', code=0):
        return subprocess.CompletedProcess([],code,output,b'')

    def test_running_tasks_capture_and_powered_off_never_probe_adb(self):
        cases=[(self.row(run={'active':True}),'执行配置'),
               (self.row(account_capture={'active':True}),'采集'),
               (self.row(power={'supported':True,'on':False,'status':'stopped'}),'未开机'),
               (self.row(power={'supported':True,'on':True,'status':'logging_in'}),'登录')]
        with patch('web.readiness.subprocess.run') as run:
            for row,reason in cases:
                state=probe_ready(row,'com.netease.my');self.assertFalse(state['ready']);self.assertIn(reason,state['reason'])
            run.assert_not_called()

    def test_disconnected_is_rejected_without_connecting_or_launching(self):
        with patch('web.readiness.subprocess.run',return_value=self.result(b'offline\n',1)) as run:
            state=probe_ready(self.row(),'com.netease.my')
        self.assertFalse(state['ready']);self.assertIn('ADB 未连接',state['reason'])
        self.assertEqual(run.call_args.args[0][-1],'get-state');self.assertEqual(run.call_count,1)

    def test_exact_foreground_package_required_even_if_old_focus_is_game(self):
        for text in (b'mCurrentFocus=Window{com.netease.my.uc/.Main}',
                     b'mCurrentFocus=Window{com.android.permissioncontroller/.Dialog}\nmFocusedApp=App{com.netease.my/.Main}'):
            with patch('web.readiness.subprocess.run',side_effect=[self.result(b'device\n'),self.result(text)]) as run:
                result=probe_ready(self.row(),'com.netease.my')
            self.assertFalse(result['ready']);self.assertIn('不在前台',result['reason']);self.assertEqual(run.call_count,2)

    def test_live_connected_world_is_required(self):
        black=BytesIO();Image.new('RGB',(1280,720)).save(black,'PNG')
        for png,expected in ((black.getvalue(),False),(world_screen(),True),(world_screen('qiandao/fuli.png'),False)):
            with patch('web.readiness.subprocess.run',side_effect=[self.result(b'device\n'),self.result(b'mCurrentFocus=Window{u0 com.netease.my/.Main}'),self.result(png)]) as run:
                result=probe_ready(self.row(),'com.netease.my')
            self.assertEqual(result['ready'],expected,result)
            self.assertEqual(run.call_args.args[0][-3:],['exec-out','screencap','-p'])

    def test_invalid_or_portrait_capture_not_ready(self):
        self.assertFalse(scene_visible(b'not a png'))
        out=BytesIO();Image.new('RGB',(720,1280)).save(out,'PNG')
        self.assertFalse(scene_visible(out.getvalue()))


class ReceiveProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.manager=Manager(self.root,Catalog())
        self.device=self.manager.add({'name':'测试实例','address':'127.0.0.1:5555','adb_path':'adb'})
        self.key=self.device['id']
        self.profile=self.manager.save_profile(None,{'name':'日常','resource':'官服','tasks':[{'name':'宝图任务'}]})
        self.row={**self.device,'run':{'active':False},'power':{'supported':True,'on':True,'status':'running'}}

    def tearDown(self):
        self.manager.close();self.temp.cleanup()

    def test_remembered_login_success_does_not_bypass_live_check(self):
        self.manager.power_results[self.key]='ready'
        with patch.object(self.manager,'list_with_power',return_value=[self.row]),patch('web.readiness.probe_ready',return_value={'ready':False,'reason':'ADB 未连接'}):
            with self.assertRaisesRegex(ValueError,'ADB 未连接'):self.manager.receive_profile(self.key,self.profile['id'])
        self.assertIsNone(self.manager.get(self.key).get('profile_id'))

    def test_busy_state_rechecked_after_probe_before_binding(self):
        def probe(*args):
            self.manager.power_operations[self.key]='starting'
            return {'ready':True,'reason':'ready'}
        with patch.object(self.manager,'list_with_power',return_value=[self.row]),patch('web.readiness.probe_ready',side_effect=probe):
            with self.assertRaisesRegex(ValueError,'停止实例'):self.manager.receive_profile(self.key,self.profile['id'])
        self.assertIsNone(self.manager.get(self.key).get('profile_id'));self.manager.power_operations.clear()

    def test_connected_world_receives_and_offline_receiving_is_rejected(self):
        with patch.object(self.manager,'list_with_power',return_value=[self.row]),patch('web.readiness.probe_ready',return_value={'ready':True,'reason':'ready'}):
            result=self.manager.receive_profile(self.key,self.profile['id'])
        self.assertEqual(result['profile_id'],self.profile['id'])
        self.manager.assign_profile(self.key,None)
        off={**self.row,'power':{'supported':True,'on':False,'status':'stopped'}}
        with patch.object(self.manager,'list_with_power',return_value=[off]):
            with self.assertRaisesRegex(ValueError,'未开机'):self.manager.receive_profile(self.key,self.profile['id'])
        self.assertIsNone(self.manager.get(self.key).get('profile_id'))

    def test_send_api_checks_readiness_while_manual_preconfiguration_still_works(self):
        with TestClient(create_app(self.root/'api',None)) as client:
            device=client.post('/api/devices',json={'name':'实例','address':'127.0.0.1:5555','adb_path':'adb'}).json()
            profile=client.post('/api/profiles',json={'name':'配置','resource':'官服','tasks':[{'name':'宝图任务'}]}).json()
            with patch('web.readiness.probe_ready',return_value={'ready':False,'reason':'未进入游戏场景'}):
                response=client.put('/api/devices/'+device['id']+'/receive-profile',json={'profile_id':profile['id']})
                self.assertEqual(response.status_code,400,response.text)
                self.assertIn('未进入游戏',response.json()['detail'])
                rows=client.get('/api/profiles/'+profile['id']+'/targets').json()
                self.assertFalse(rows[0]['ready'])
            with patch('web.readiness.probe_ready',return_value={'ready':True,'reason':'ready'}):
                self.assertEqual(client.put('/api/devices/'+device['id']+'/receive-profile',json={'profile_id':profile['id']}).status_code,200)
