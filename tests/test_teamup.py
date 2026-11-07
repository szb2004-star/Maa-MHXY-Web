import queue
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from web.catalog import Catalog
from web.manager import Manager
from web.teamup import TeamMailbox, TeamOptions, TeamStopped, group_label, run_teamup
from web.teamup_ui import TextBox, slot_count


class FakeUI:
    def __init__(self, leader=True, counts=(1, 5, 5)):
        self.leader=leader;self.counts=list(counts);self.last=None
        self.now=0;self.invites=[];self.selected=[];self.followed=0;self.accepted=0
    def select_group(self,name):self.selected.append(name);return self.leader
    def home(self):pass
    def ensure_team(self):pass
    def team_count(self):
        if self.counts:self.last=self.counts.pop(0)
        return self.last
    def group_candidates(self,name):return range(4)
    def invite_candidate(self,candidate,name):self.invites.append((candidate,name));return True
    def wait(self,seconds):self.now+=max(seconds,.1)
    def accept_invitation(self):self.accepted+=1
    def follow_tick(self):self.followed+=1


class Mailbox:
    leader_seen=True
    finished=None
    def __init__(self):self.claims=[];self.on_check=lambda:None
    def check(self):self.on_check()
    def claim(self,group,role):self.claims.append((group,role))


class TeamTests(unittest.TestCase):
    def test_catalog_compiles_defaults_and_rejects_invalid_settings(self):
        catalog=Catalog();plan=catalog.compile([{'name':'编组自动组队'}])
        self.assertEqual(TeamOptions.from_override(plan[0]['pipeline_override']),TeamOptions())
        self.assertEqual(catalog.public()['tasks'][-1]['category'],'组队日常')
        for values in ({'好友编组':'','等待秒数':180},{'好友编组':'自动组队','等待秒数':9},
                       {'好友编组':'自动组队','等待秒数':1801}):
            with self.assertRaises(ValueError):catalog.compile([{'name':'编组自动组队','options':{'编组组队设置':values}}])
        self.assertIn('队长',catalog.description('编组自动组队'))

    def test_group_name_matching_is_exact_not_substring(self):
        self.assertEqual(group_label('自动组队(4)'),'自动组队')
        self.assertEqual(group_label('自动组队（4）'),'自动组队')
        self.assertNotEqual(group_label('自动组队备用(4)'),'自动组队')

    def test_leader_reinvites_until_five_and_checks_five_twice(self):
        ui=FakeUI(counts=(1,3,5,4,5,5));mailbox=Mailbox();events=[]
        role=run_teamup(ui,TeamOptions(wait_seconds=30),mailbox,lambda *a,**k:events.append((a,k)),clock=lambda:ui.now)
        self.assertEqual(role,'leader');self.assertGreater(len(ui.invites),4)
        self.assertTrue(all(name=='自动组队' for _,name in ui.invites))
        self.assertEqual(events[-1][1]['members'],5)

    def test_unreadable_or_underfilled_team_never_starts_following_tasks(self):
        for count in (None,1,4):
            ui=FakeUI(counts=(count,));mailbox=Mailbox()
            with self.assertRaisesRegex(ValueError,'组队超时'):
                run_teamup(ui,TeamOptions(wait_seconds=10),mailbox,lambda *a,**k:None,clock=lambda:ui.now)
            self.assertGreaterEqual(ui.now,10)

    def test_ui_failure_does_not_assign_member(self):
        ui=FakeUI();ui.select_group=Mock(side_effect=ValueError('好友菜单识别失败'));mailbox=Mailbox()
        with self.assertRaisesRegex(ValueError,'识别失败'):
            run_teamup(ui,TeamOptions(),mailbox,lambda *a,**k:None)
        self.assertFalse(mailbox.claims)

    def test_member_waits_for_leader_and_does_not_invite(self):
        ui=FakeUI(leader=False,counts=(2,));mailbox=Mailbox()
        def check():
            if ui.followed>=2:mailbox.finished=True
        mailbox.on_check=check
        role=run_teamup(ui,TeamOptions(),mailbox,lambda *a,**k:None,clock=lambda:ui.now)
        self.assertEqual(role,'member');self.assertFalse(ui.invites);self.assertGreaterEqual(ui.followed,2)

    def test_member_timeout_and_stop_are_bounded(self):
        ui=FakeUI(leader=False,counts=(0,));mailbox=Mailbox()
        with self.assertRaisesRegex(ValueError,'等待组队邀请超时'):
            run_teamup(ui,TeamOptions(wait_seconds=10),mailbox,lambda *a,**k:None,clock=lambda:ui.now)
        stop=threading.Event();stop.set()
        with self.assertRaises(TeamStopped):TeamMailbox(stop,lambda *a,**k:None).check()
        stop.clear();box=TeamMailbox(stop,lambda *a,**k:None)
        box.receive({'type':'team_abort','message':'队长冲突'})
        with self.assertRaisesRegex(ValueError,'冲突'):box.check()

    def test_group_dropdown_waits_for_real_stable_menu_before_using_coordinates(self):
        from web.teamup_ui import GameTeamUI
        ui=GameTeamUI(Mock(),Mock(),TeamMailbox(threading.Event(),lambda *a,**k:None))
        contact_list=[TextBox('普通好友',(220,220,100,30))]
        moving=[TextBox('本服好友(4)',(220,370,100,30)),TextBox('全部联系人(4)',(220,440,100,30))]
        stable=[TextBox('本服好友(4)',(220,350,100,30)),TextBox('全部联系人(4)',(220,420,100,30))]
        ui.texts=Mock(side_effect=[contact_list,moving,stable,stable]);ui.wait=Mock()
        items,_=ui.stable_menu()
        self.assertEqual(items,stable)
        ui.texts=Mock(return_value=contact_list)
        with self.assertRaisesRegex(ValueError,'未打开或仍在滚动'):ui.stable_menu()

    def test_invitation_accepts_same_guild_label_but_not_an_unrelated_accept_button(self):
        from web.teamup_ui import GameTeamUI
        ui=GameTeamUI(Mock(),Mock(),TeamMailbox(threading.Event(),lambda *a,**k:None))
        ui.image=Mock(return_value=object());ui.match=Mock(return_value=False);ui.click=Mock()
        accept=TextBox('接 受',(270,320,100,35))
        ui.texts=Mock(return_value=[TextBox('同帮',(130,195,65,20)),TextBox('邀请你加入月宫的队伍。',(20,260,350,25)),
                                   TextBox('拒绝(12)',(70,320,100,35)),accept])
        self.assertTrue(ui.accept_visible_invitation());ui.click.assert_called_once_with(accept)
        ui.click.reset_mock();ui.texts=Mock(return_value=[accept])
        self.assertFalse(ui.accept_visible_invitation());ui.click.assert_not_called()

    def test_png_capture_is_normalized_and_has_a_timeout(self):
        from io import BytesIO
        from unittest.mock import patch
        from PIL import Image
        from web.teamup_ui import GameTeamUI
        data=BytesIO();Image.new('RGB',(1920,1080),(255,0,0)).save(data,'PNG')
        ui=GameTeamUI(Mock(),Mock(),TeamMailbox(threading.Event(),lambda *a,**k:None),{'adb_path':'adb','address':'one'})
        with patch('web.teamup_ui.subprocess.run') as capture:
            capture.return_value.stdout=data.getvalue();image=ui.image()
            self.assertEqual(image.shape,(720,1280,3));self.assertEqual(tuple(image[0,0]),(0,0,255))
            self.assertEqual(capture.call_args.kwargs['timeout'],8)
            capture.side_effect=__import__('subprocess').TimeoutExpired('adb',8)
            with self.assertRaisesRegex(ValueError,'抓屏失败或超时'):ui.image()

    def test_progress_ocr_cannot_make_a_failed_window_template_match_succeed(self):
        from types import SimpleNamespace
        from web.teamup_ui import GameTeamUI
        primary=SimpleNamespace(name='recognition/TemplateMatch/test',recognition=SimpleNamespace(hit=False))
        side=SimpleNamespace(name='__WebReadOnlyTaskPanel',recognition=SimpleNamespace(hit=True))
        task=SimpleNamespace(entry=primary.name,nodes=[side,primary])
        tasker=Mock();tasker.post_recognition.return_value.wait.return_value.get.return_value=task
        ui=GameTeamUI(tasker,Mock(),TeamMailbox(threading.Event(),lambda *a,**k:None))
        self.assertFalse(ui.match(['unused.png'],(0,0,100,100),image=object()))

    def test_assistants_and_unreadable_slots_do_not_count_as_five_players(self):
        def slots(labels):return [TextBox(text,(160+i*220,545,60,30)) for i,text in enumerate(labels)]
        self.assertEqual(slot_count(slots(['月宫','法攻型','物攻型','治疗型','辅助型'])),1)
        self.assertEqual(slot_count(slots(['月宮','🎯魔王寨','方寸山🎧','地府','化生寺'])),5)
        self.assertEqual(slot_count(slots(['月宫','魔王寨','未知','地府','化生寺'])),4)
        self.assertEqual(slot_count(slots(['月宫','魔王寨','方寸山'])),3)
        self.assertIsNone(slot_count(slots(['未知'])))


class CoordinatorTests(unittest.TestCase):
    def test_duplicate_captains_abort_peers_and_completion_is_broadcast(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(directory,Catalog())
            def run(key):
                process=Mock();process.poll.return_value=None
                return {'process':process,'device_id':key,'state':{'status':'running'},'logs':[],
                        'seq':0,'log_path':Path(directory)/(key+'.jsonl')}
            a,b,c=run('a'),run('b'),run('c');manager.runs={'a':a,'b':b,'c':c}
            with unittest.mock.patch.object(manager,'_team_send') as send,unittest.mock.patch.object(manager,'log'):
                manager._team_claim(b,{'group':'自动组队','role':'member'})
                manager._team_claim(a,{'group':'自动组队','role':'leader'})
                self.assertTrue(any(call.args[0] is b and call.args[1]['type']=='team_leader' for call in send.call_args_list))
                a['state']['status']='completed';manager._team_finished(a)
                self.assertTrue(any(call.args[0] is b and call.args[1].get('success') for call in send.call_args_list))
                manager._team_claim(c,{'group':'自动组队','role':'leader'})
                self.assertTrue(any(call.args[1]['type']=='team_abort' for call in send.call_args_list))
                self.assertNotIn('team',c)
            manager.runs={};manager.close()


class TeamPipeTests(unittest.TestCase):
    def test_member_receives_captain_completion_through_real_worker_pipes(self):
        import subprocess,sys,time
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(directory,Catalog())
            captain=manager.add({'name':'leader','address':'127.0.0.1:5555','adb_path':'adb'})['id']
            member=manager.add({'name':'member','address':'127.0.0.1:5556','adb_path':'adb'})['id']
            for key in (captain,member):manager.update(key,{'name':manager.get(key)['name'],'resource':'官服','tasks':[{'name':'编组自动组队'}]})
            worker=Path(directory)/'pipe_worker.py'
            worker.write_text('''import json,sys,time
config=json.loads(sys.stdin.readline());role=config['device']['name']
print('@@WEB@@'+json.dumps({'kind':'team_claim','group':'自动组队','role':role}),flush=True)
reply=json.loads(sys.stdin.readline());assert reply['type']=='team_claim_result' and reply['ok']
if role=='leader':
 time.sleep(.1)
else:
 while True:
  reply=json.loads(sys.stdin.readline())
  if reply['type']=='team_finished':assert reply['success'];break
print('@@WEB@@'+json.dumps({'kind':'status','status':'completed'}),flush=True)
''',encoding='utf-8')
            popen=subprocess.Popen
            try:
                with patch('web.manager.subprocess.Popen',side_effect=lambda command,**kwargs:popen([sys.executable,'-u',str(worker)],**kwargs)):
                    manager.start(member);manager.start(captain)
                deadline=time.monotonic()+5
                while not all(manager.snapshot(key).get('finished_at') for key in (captain,member)) and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual([manager.snapshot(key)['status'] for key in (captain,member)],['completed','completed'])
            finally:manager.close()

if __name__=='__main__':unittest.main()
