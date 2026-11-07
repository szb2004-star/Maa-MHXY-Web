"""Read-only account collection from an already-running game. Never buys or upgrades."""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys
import threading
import time

from .account_data import (GUILD_SKILL_NAMES, TRAINING_NAMES, one_number, role_header, skills_from_text)
from .catalog import Catalog
from .teamup import TeamMailbox
from .teamup_ui import GameTeamUI, PLAYER_SCHOOLS


def emit(kind,**data):
    print('@@ACCOUNT@@'+json.dumps({'kind':kind,**data},ensure_ascii=False),flush=True)


class Collector:
    def __init__(self,ui,directory):
        self.ui=ui;self.directory=Path(directory);self.level=None

    def title(self,image=None):
        return ''.join(item.text.replace(' ','') for item in self.ui.texts((400,0,600,80),image))

    def snapshot(self,name):
        from PIL import Image
        image=self.ui.image();Image.fromarray(image[:,:,::-1]).save(self.directory/(name+'.png'))
        return image

    def bag_visible(self,image=None):
        return self.ui.match(['beibao/beibao_jiemian_panduan.png'],(335,5,577,68),image,threshold=.7)

    def wait_title(self,word):
        for _ in range(5):
            image=self.ui.image()
            if word=='包裹' and self.bag_visible(image):return
            if word in self.title(image):return
            self.ui.wait(.4)
        raise ValueError(f'未确认打开“{word}”页面')

    def home(self):
        for _ in range(5):
            image=self.ui.image();title=self.title(image)
            if self.bag_visible(image) or any(word in title for word in ('人物属性','人物信息','包裹','技能','修炼')):
                self.ui.click((1083,20,45,50))
            else:
                self.ui.home();return
        raise ValueError('无法返回游戏主界面，请关闭弹窗后再采集')

    def tab(self,label):
        for _ in range(3):
            tab=self.ui.find(self.ui.texts((1100,80,100,550)),label)
            if tab:self.ui.click(tab);return True
            self.ui.wait(.3)
        return False

    def identity(self):
        from PIL import Image
        self.home()
        # 主界面右上角的角色头像，比人物属性面板里的更清晰
        Image.fromarray(self.ui.image()[6:96,1186:1276,::-1]).save(self.directory/'avatar.png')
        self.ui.click((1185,5,91,92));self.wait_title('人物属性')
        image=self.snapshot('identity')
        header_items=self.ui.texts((200,75,340,95),image)
        data=role_header(header_items)
        self.level=data.get('level')
        data.update(school=None,guild_name=None,server=None,vitality=None,vitality_max=None,guild_contribution=None)
        for item in self.ui.texts((800,240,205,50),image):
            match=re.fullmatch(r'(\d+)/(\d+)',item.text.replace(' ',''))
            if match:data.update(vitality=int(match[1]),vitality_max=int(match[2]))
        if self.tab('信息'):
            self.wait_title('人物信息');image=self.snapshot('role-info')
            school=self.ui.texts((708,85,180,55),image)
            for item in school:
                text=re.sub(r'[^\u3400-\u9fff]','',item.text).replace('宮','宫')
                if text in PLAYER_SCHOOLS:data['school']=text
            guild=self.ui.texts((708,160,180,55),image)
            if guild:data['guild_name']=''.join(item.text for item in guild)
            contribution=one_number(self.ui.texts((775,455,105,48),image))
            if contribution:data['guild_contribution']=contribution['value']
        if not data['role_id'] or not data['role_name']:
            emit('log',message='角色资料识别结果：'+' | '.join(item.text for item in header_items))
            raise ValueError('角色姓名或 ID 未识别完整，未保存不确定身份的数据')
        return data,'ok','已从人物属性和人物信息页读取；服务器暂未读取'

    def currency(self):
        self.home();self.ui.click((1197,555,78,88));self.wait_title('包裹')
        image=self.snapshot('currency')
        data={'gold':one_number(self.ui.texts((190,635,150,42),image)),
              'silver':one_number(self.ui.texts((420,635,160,42),image))}
        score=re.search(r'(\d{2,7})',''.join(item.text for item in self.ui.texts((285,578,240,46),image)))
        if score:data['score']=int(score[1])
        success=all(value is not None for value in data.values())
        return data,'ok' if success else 'partial','已读取背包余额' if success else '部分余额未能可靠识别，显示为未识别'

    def open_skills(self):
        if any(word in self.title() for word in ('技能','修炼')):return
        self.home()
        button=self.ui.find(self.ui.texts((880,625,400,95)),'技能')
        if not button:
            self.ui.click((1210,640,60,60))
            for _ in range(5):
                button=self.ui.find(self.ui.texts((880,625,400,95)),'技能')
                if button:break
                self.ui.wait(.4)
        if not button:raise ValueError('当前菜单未识别到技能入口')
        self.ui.click(button);self.wait_title('技能')

    def skill_section(self,kind):
        self.open_skills();label='修炼' if kind=='training' else '帮派'
        if not self.tab(label):
            self.snapshot(kind+'-unavailable')
            level=f'{self.level}级' if self.level is not None else '当前'
            return {'skills':[]},'unavailable',f'{level}角色的技能页未显示“{label}”入口，尚不能采集该项'
        self.ui.wait(.5)
        title=self.title()
        if label not in title and not ('技能' in title and label in ''.join(item.text for item in self.ui.texts((1100,80,100,550)))):
            raise ValueError(f'未确认进入{label}页面')
        names=TRAINING_NAMES if kind=='training' else GUILD_SKILL_NAMES
        skills={};previous=None
        for page in range(6):
            image=self.snapshot(kind+'-'+str(page))
            items=self.ui.texts(image=image)
            observed=skills_from_text(items,names)
            for item in observed:skills[(item['group'],item['name'])]=item
            signature=tuple((item['group'],item['name'],item['level'],item['maximum']) for item in observed)
            if not observed or signature==previous:break
            previous=signature;self.ui.swipe(500,540,500,250)
        if not skills:
            text=' '.join(item.text for item in items)
            reason=next((phrase for phrase in ('未加入帮派','请先加入帮派','尚未开启','尚未开放','未解锁') if phrase in text),None)
            if reason:return {'skills':[]},'unavailable',reason
            return {'skills':[]},'partial','页面已打开，但未识别到可确认的技能等级'
        return {'skills':list(skills.values())},'ok',f'已读取 {len(skills)} 项等级'

    def run(self):
        any_failure=False
        for section,reader in [('identity',self.identity),('currency',self.currency),
                               ('training',lambda:self.skill_section('training')),
                               ('guild_skills',lambda:self.skill_section('guild_skills'))]:
            emit('progress',message={'identity':'正在读取角色资料','currency':'正在读取金币和银币',
                                    'training':'正在读取修炼等级','guild_skills':'正在读取帮派技能'}[section])
            try:
                data,status,message=reader()
                if status=='partial':any_failure=True
                emit('section',section=section,status=status,data=data,message=message)
            except Exception as exc:
                self.ui.mailbox.check()
                any_failure=True;emit('section',section=section,status='failed',data={},message=str(exc))
                if section=='identity':raise
        self.home()
        emit('finished',status='partial' if any_failure else 'completed',
             message='已保存读取到的数据，部分内容尚未识别' if any_failure else '采集完成，已返回游戏主界面')


def main():
    from maa.controller import AdbController
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit
    config=json.loads(sys.stdin.readline());directory=Path(config['directory']);directory.mkdir(parents=True,exist_ok=True)
    Toolkit.init_option(directory)
    resource=Resource();resource.use_cpu()
    for path in Catalog().resource_paths('官服'):
        if not resource.post_bundle(path).wait().succeeded:raise ValueError('账号识别资源加载失败')
    d=config['device'];controller=AdbController(d['adb_path'],d['address'],config=d.get('config',{}),screencap_methods=2)
    if not controller.post_connection().wait().succeeded:raise ValueError('无法连接当前模拟器窗口')
    tasker=Tasker()
    if not tasker.bind(resource,controller):raise ValueError('账号识别初始化失败')
    stopping=threading.Event();mailbox=TeamMailbox(stopping,lambda *a,**k:None)
    ui=GameTeamUI(tasker,controller,mailbox,d);ui.set_deadline(time.monotonic()+125)
    collector=Collector(ui,directory)
    try:
        collector.run()
    except Exception:
        try:
            ui.set_deadline(time.monotonic()+8);collector.home()
        except Exception:
            pass
        raise


if __name__=='__main__':
    try:main()
    except Exception as exc:
        emit('finished',status='failed',message=str(exc));sys.exit(1)
