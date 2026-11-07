from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from fastapi.testclient import TestClient
from web.account_data import amount,one_number,role_header,skills_from_text
from web.accounts import Accounts
from web.app import create_app
from web.catalog import Catalog
from web.manager import Manager
from web.teamup_ui import TextBox


def text(value,x=0,y=0):return TextBox(value,(x,y,100,24))


class AccountParserTests(unittest.TestCase):
    def test_zero_grouped_and_abbreviated_balances(self):
        self.assertEqual(amount('0')['value'],0)
        self.assertEqual(amount('2.152.059')['value'],2152059)
        self.assertEqual(amount('2,152,059')['value'],2152059)
        self.assertTrue(amount('2.15万')['approximate'])
        self.assertEqual(amount('2.15万')['value'],21500)
        for value in ('23级','12/15','金币不足','2,12,059','O'):
            self.assertIsNone(amount(value),value)
        self.assertIsNone(one_number([text('1'),text('2')]))
        self.assertEqual(one_number([text('0')])['value'],0)

    def test_role_and_skill_levels_exclude_upgrade_costs(self):
        self.assertEqual(role_header([text('即墨町悦 23级'),text('ID 805719385')]),
                         {'role_name':'即墨町悦','role_id':'805719385','level':23})
        split=role_header([text('即墨町悦 23级',300,80),text('ID',300,125),text('805719385',400,125)])
        self.assertEqual(split['role_id'],'805719385')
        skills=skills_from_text([text('强身术60级')],('强身术',))
        self.assertEqual(skills[0]['level'],60)
        self.assertEqual(skills_from_text([text('强身术'),text('600',120)],('强身术',)),[])
        self.assertEqual(skills_from_text([text('攻法修炼'),text('15/25',120)],('攻法修炼',))[0]['level'],15)
        self.assertFalse(skills_from_text([text('攻法修炼'),text('500/1000',120)],('攻法修炼',)))


class AccountCollectorTests(unittest.TestCase):
    def test_wallet_uses_verified_bag_template_when_title_ocr_is_blank(self):
        from web.account_worker import Collector
        ui=Mock();ui.match.return_value=True;ui.image.return_value=object()
        ui.texts.side_effect=lambda roi,image=None:[text('0')] if roi[0]==190 else [text('2.152.059')] if roi[0]==420 else []
        with tempfile.TemporaryDirectory() as directory:
            collector=Collector(ui,directory);collector.home=Mock();collector.snapshot=Mock(return_value=object())
            data,status,_=collector.currency()
            self.assertEqual(status,'ok');self.assertEqual(data['gold']['value'],0)
            self.assertEqual(data['silver']['value'],2152059)


class AccountStorageTests(unittest.TestCase):
    def test_persistence_role_change_and_failed_read_preserve_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(directory,Catalog());key=manager.add({'name':'one','address':'one','adb_path':'adb'})['id']
            accounts=Accounts(manager)
            try:
                accounts.section(key,{'section':'identity','status':'ok','data':{'role_name':'甲','role_id':'123456789'}})
                accounts.section(key,{'section':'currency','status':'ok','data':{'gold':{'value':0}}})
                previous=accounts.get(key)['sections']['currency']
                accounts.section(key,{'section':'currency','status':'failed','message':'offline','data':{}})
                after=accounts.get(key)['sections']['currency']
                self.assertEqual(after['updated_at'],previous['updated_at']);self.assertEqual(after['data']['gold']['value'],0)
                self.assertEqual(after['error'],'offline')
                accounts.section(key,{'section':'identity','status':'ok','data':{'role_name':'乙','role_id':'987654321'}})
                self.assertNotIn('currency',accounts.get(key)['sections'])
                reloaded=Accounts(manager)
                try:self.assertEqual(reloaded.get(key)['sections']['identity']['data']['role_name'],'乙')
                finally:reloaded.close()
            finally:accounts.close();manager.close()

    def test_capture_blocks_conflicting_device_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(directory,Catalog());key=manager.import_mumu({'name':'one','address':'one','adb_path':'adb','mumu':{'app_path':'mumu','index':0}})['id']
            manager.capture_operations[key]={'active':True}
            for action in (lambda:manager.start(key),lambda:manager.set_power(key,False),
                           lambda:manager.delete(key),lambda:manager.assign_profile(key,None)):
                with self.assertRaisesRegex(ValueError,'采集'):action()
            manager.capture_operations.clear();manager.close()


class AccountAPITests(unittest.TestCase):
    def test_tabs_follow_instances_offline_capture_is_rejected_and_auth_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory,TestClient(create_app(directory,'test-only-access-token')) as client:
            manager=client.app.state.manager
            keys=[manager.import_mumu({'name':name,'address':name,'adb_path':'adb','mumu':{'app_path':'mumu','index':i}})['id'] for i,name in enumerate(('月宫','小号'))]
            headers={'Authorization':'Bearer test-only-access-token'}
            self.assertEqual(client.get('/api/accounts').status_code,401)
            records=client.get('/api/accounts',headers=headers).json()['accounts'];self.assertEqual(len(records),2)
            with patch.object(manager,'list_with_power',return_value=[{**manager.get(key),'power':{'on':False}} for key in keys]):
                self.assertEqual(client.post('/api/accounts/'+keys[0]+'/capture',headers=headers).status_code,400)
                self.assertEqual(client.post('/api/accounts/capture-running',headers=headers).json()['results'],[])
            self.assertEqual(client.get('/api/accounts/missing',headers=headers).status_code,404)

    def test_real_subprocess_publishes_sections_and_releases_instance(self):
        with tempfile.TemporaryDirectory() as directory,TestClient(create_app(directory)) as client:
            manager=client.app.state.manager;accounts=client.app.state.accounts
            key=manager.import_mumu({'name':'小号','address':'one','adb_path':'adb','mumu':{'app_path':'mumu','index':0}})['id']
            script=Path(directory)/'capture_worker.py'
            script.write_text('''import json,sys,time
json.loads(sys.stdin.readline())
for section,data in [('identity',{'role_name':'测试','role_id':'123456789'}),('currency',{'gold':{'value':0},'silver':{'value':2152059}}),('training',{'skills':[]}),('guild_skills',{'skills':[]})]:
 print('@@ACCOUNT@@'+json.dumps({'kind':'section','section':section,'status':'ok','data':data}),flush=True)
print('@@ACCOUNT@@'+json.dumps({'kind':'finished','status':'completed','message':'done'}),flush=True)
''',encoding='utf-8')
            popen=subprocess.Popen
            with patch.object(manager,'list_with_power',return_value=[{**manager.get(key),'power':{'on':True}}]),patch('web.accounts.subprocess.Popen',side_effect=lambda command,**kwargs:popen([sys.executable,'-u',str(script)],**kwargs)):
                response=client.post('/api/accounts/'+key+'/capture');self.assertEqual(response.status_code,200)
                deadline=time.monotonic()+5
                while accounts.get(key)['capture']['active'] and time.monotonic()<deadline:time.sleep(.01)
            data=client.get('/api/accounts/'+key).json()
            self.assertEqual(data['capture']['status'],'completed')
            self.assertEqual(data['sections']['currency']['data']['gold']['value'],0)
            self.assertNotIn(key,manager.capture_operations)
            self.assertTrue((Path(directory)/'accounts'/(key+'.json')).is_file())

if __name__=='__main__':unittest.main()
