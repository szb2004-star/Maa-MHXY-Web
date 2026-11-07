"""Verified 1280x720 game UI adapter for group-based assembly (MaaFramework)."""
from __future__ import annotations
from dataclasses import dataclass
import re
import time
import subprocess
from io import BytesIO

from .teamup import TeamStopped, group_label


@dataclass(frozen=True)
class TextBox:
    text: str
    box: tuple


PLAYER_SCHOOLS = ('阴曹地府','大唐官府','魔王寨','方寸山','化生寺','普陀山','狮驼岭',
                  '小雷音','花果山','女儿村','须弥海','月宫','龙宫','地府')
ASSISTANT_TYPES = {'物攻型','法攻型','治疗型','辅助型','封印型'}


def slot_count(items):
    """Actual players have a school label; their top caption is blank, not 队员."""
    slots = {}
    for item in items:
        # School icons can be recognized as emoji; they are not part of the school.
        text = re.sub(r'[^\u3400-\u9fff]', '', item.text).replace('宮','宫')
        x,y,w,h = item.box
        if not 540 <= y+h/2 <= 585:
            continue
        index = int((x+w/2-80)//220)
        if not 0 <= index < 5:
            continue
        if text in ASSISTANT_TYPES:
            slots[index] = False
        elif any(text.startswith(school) and len(text) <= len(school)+2 for school in PLAYER_SCHOOLS):
            slots[index] = True
    # Members see empty slots where only the leader sees assistants. Count only
    # positively recognized human schools; 5 still requires five distinct schools.
    humans = sum(slots.values())
    return humans if humans else None


class GameTeamUI:
    def __init__(self, tasker, controller, mailbox, device=None):
        self.tasker = tasker
        self.device = device
        self.controller = controller
        self.mailbox = mailbox
        self.group_size = None
        self.deadline = None
        self.last_count = None

    def set_deadline(self, deadline):
        self.deadline = deadline

    def check(self):
        self.mailbox.check()
        if self.deadline is not None and time.monotonic() >= self.deadline:
            count = self.last_count if self.last_count is not None else '未知'
            raise ValueError(f'组队等待超时：当前 {count}/5，未确认满员，未执行后续任务')

    def wait(self, seconds):
        self.check()
        self.mailbox.stopping.wait(seconds)
        self.check()

    def image(self):
        self.check()
        if self.device:
            # RawWithGzip can block indefinitely on MuMu macOS. Use the same bounded
            # lossless PNG capture as the monitor, then normalize to the resource canvas.
            from PIL import Image
            import numpy as np
            for attempt in range(3):
                self.check()
                try:
                    result = subprocess.run([self.device['adb_path'],'-s',self.device['address'],
                                             'exec-out','screencap','-p'],capture_output=True,timeout=8,check=True)
                    with Image.open(BytesIO(result.stdout)) as frame:
                        if abs(frame.width/frame.height-16/9) > .03:
                            raise ValueError('组队识别需要横屏 16:9，请检查模拟器分辨率')
                        image=np.asarray(frame.convert('RGB').resize((1280,720),Image.Resampling.BOX))[:,:,::-1].copy()
                    break
                except (subprocess.SubprocessError, OSError) as exc:
                    if attempt == 2:
                        raise ValueError('模拟器抓屏失败或超时，请检查 ADB 和模拟器状态') from exc
                    self.wait(.3)
        else:
            image = self.controller.post_screencap().wait().get()
        self.check()
        if image is None or abs(image.shape[1]/image.shape[0]-16/9) > .03:
            raise ValueError('组队识别需要横屏 16:9，请检查模拟器分辨率')
        return image

    def recognize(self, kind, parameter, image=None):
        self.check()
        task = self.tasker.post_recognition(kind, parameter, self.image() if image is None else image).wait().get()
        self.check()
        if not task:
            raise ValueError('组队画面识别执行失败')
        # Context event sinks can append their own OCR nodes to this task.
        # A side observation must never turn a failed template match into a hit.
        return [node.recognition for node in task.nodes
                if node.recognition and node.name == task.entry]

    def texts(self, roi=(0, 0, 1280, 720), image=None):
        from maa.pipeline import JOCR
        details = self.recognize('OCR', JOCR(roi=roi, threshold=.65), image)
        return [TextBox(item.text, tuple(item.box)) for detail in details
                for item in detail.all_results if getattr(item, 'score', 0) >= .65]

    @staticmethod
    def find(items, expression):
        return next((item for item in items if re.fullmatch(expression, re.sub(r'\s+', '', item.text))), None)

    def click(self, target):
        self.check()
        x, y, w, h = target.box if isinstance(target, TextBox) else target
        if not self.controller.post_click(int(x+w/2), int(y+h/2)).wait().succeeded:
            raise ValueError('组队操作点击失败')
        self.wait(.65)

    def swipe(self, x1, y1, x2, y2):
        self.check()
        if not self.controller.post_swipe(x1, y1, x2, y2, 350).wait().succeeded:
            raise ValueError('组队列表滑动失败')
        self.wait(.4)

    def match(self, templates, roi, image=None, threshold=.8, green_mask=False):
        from maa.pipeline import JTemplateMatch
        details = self.recognize('TemplateMatch', JTemplateMatch(template=templates, roi=roi, threshold=[threshold], green_mask=green_mask), image)
        return any(detail.hit for detail in details)

    def friends_visible(self, image=None):
        image = self.image() if image is None else image
        if self.match(['r5/haoyou_zhujiemian.png'], (352,0,543,103), image, threshold=.7):
            return True
        text = ''.join(item.text.replace(' ','') for item in self.texts((450,0,350,80), image))
        return '我的好友' in text

    def team_visible(self, image=None):
        return self.match(['duiwu/duiwu-zudui.png', 'duiwu/duiwu-duiwu.png'], (0, 0, 229, 106), image)

    def home(self):
        for _ in range(4):
            image = self.image()
            if self.friends_visible(image):
                self.click((1120, 20, 46, 55))
            elif self.team_visible(image):
                self.click((1184, 15, 40, 38))
            elif self.find(self.texts((450,0,450,85), image), '人物属性.*'):
                self.click((1083,20,45,50))
            elif self.match(['zonghe/chenghao.png', 'zonghe/jiahao.png', 'zonghe/baoguo.png',
                             'zonghe/baoguo_man.png'], (1197, 540, 78, 157), image, threshold=.7):
                return
            else:
                # Animation and panel transitions may produce one intermediate frame.
                self.wait(.6)
                continue
        raise ValueError('未确认游戏主界面，请关闭其他弹窗后重试')

    def open_friends(self):
        if not self.friends_visible():
            self.home()
            self.click((0, 435, 84, 80))
            for _ in range(4):
                if self.friends_visible():
                    break
                self.wait(.5)
            else:
                raise ValueError('好友窗口打开失败，不能据此判定为队员')
        contact = self.find(self.texts((340, 80, 120, 65)), '联系人')
        if not contact:
            raise ValueError('好友页未识别到“联系人”标签')
        self.click(contact)

    @staticmethod
    def menu_signature(items):
        defaults = {'亲密好友','本服好友','全部联系人','屏蔽名单','屏新名单','黑名单'}
        labels = {group_label(item.text) for item in items}
        if len(labels & defaults) < 2:
            return None
        return tuple(sorted((group_label(item.text), round((item.box[1]+item.box[3]/2)/4))
                            for item in items if group_label(item.text)))

    def stable_menu(self):
        previous = None
        for _ in range(6):
            items = self.texts((160, 210, 275, 380))
            signature = self.menu_signature(items)
            if signature is not None and signature == previous:
                return items, signature
            previous = signature
            self.wait(.45)
        raise ValueError('好友编组菜单未打开或仍在滚动，不能据此判定为队员')

    def select_group(self, name):
        for attempt in range(3):
            self.open_friends()
            if not self.texts((155, 145, 225, 60)):
                raise ValueError('未识别到联系人编组下拉菜单')
            self.click((155, 150, 225, 50))
            seen = set()
            for page in range(16):
                # Never swipe a contact list while assuming the dropdown is open.
                # Also wait for inertial scrolling to settle before clicking a group row.
                items, signature = self.stable_menu()
                found = next((item for item in items if group_label(item.text) == name), None)
                if found:
                    suffix = re.search(r'[（(](\d+)[)）]', found.text)
                    self.group_size = int(suffix.group(1)) if suffix else None
                    self.click(found)
                    for _ in range(3):
                        selected = self.texts((155, 145, 225, 60))
                        if any(group_label(item.text) == name for item in selected):
                            return True
                        self.wait(.4)
                    # Retry opening the menu; never invite from the accidentally selected group.
                    break
                labels = {group_label(item.text) for item in items}
                if any('屏蔽名单' in text or '屏新名单' in text or '黑名单' in text for text in labels):
                    self.click((155, 150, 225, 50))
                    return False
                if signature in seen:
                    raise ValueError('未确认好友编组菜单已到底，不能据此判定为队员')
                seen.add(signature)
                self.swipe(320, 520, 320, 285)
            else:
                raise ValueError('好友编组过多，请将目标编组放到前面')
        raise ValueError(f'未确认切换到编组“{name}”，已停止邀请')

    def in_group(self, name):
        image = self.image()
        if not self.friends_visible(image):
            return False
        selected = self.texts((155,145,225,60), image)
        text = ''.join(item.text.replace(' ','') for item in selected)
        return group_label(text) == name

    def require_group(self, name):
        if not self.in_group(name):
            raise ValueError('当前不在指定好友编组，已停止邀请')

    def group_candidates(self, name):
        self.require_group(name)
        # Scrolling to the top can reveal a search row and shifts all contact rows.
        # Detect each contact's arrow rather than relying on fixed row coordinates.
        for _ in range(2):
            self.swipe(360, 280, 360, 540)
        seen = set()
        visited = set()
        for _ in range(16):
            if not self.in_group(name):
                return
            from maa.pipeline import JTemplateMatch
            image = self.image()
            details = self.recognize('TemplateMatch', JTemplateMatch(
                template=['r5/zhankai_renyuanxinxi.png'], roi=(480,205,75,395), threshold=[.8]), image)
            arrows = sorted({tuple(result.box) for detail in details for result in detail.filtered_results}, key=lambda box:box[1])
            rows = []
            for box in arrows:
                x,y,w,h = box
                # Ignore partial rows at the clipping edges.
                center = y+h/2
                if center < 225 or center > 575:
                    continue
                names = self.texts((215,max(205,int(center-34)),260,38), image)
                text = ' '.join(item.text for item in sorted(names,key=lambda item:item.box[0]))
                if text:
                    rows.append((box, text))
            signature = tuple(text for box,text in rows)
            if signature in seen:
                return
            seen.add(signature)
            for box,text in rows:
                if text in visited:
                    continue
                visited.add(text)
                yield (box, text)
            if self.group_size is not None and len(visited) >= self.group_size:
                return
            self.swipe(360, 545, 360, 255)

    def invite_candidate(self, candidate, name):
        if not self.in_group(name):
            return False
        arrow, expected = candidate
        x,y,w,h = arrow
        # Contact order and animated emoji can change between frames. The scope is
        # the verified group, so revalidate its row arrow instead of fuzzy name matching.
        roi = (max(480,x-5), max(205,y-5), min(75,w+10), min(395,h+10))
        if not self.match(['r5/zhankai_renyuanxinxi.png'], roi):
            return False
        self.click(arrow)
        items = self.texts((550, 230, 310, 390))
        invite = self.find(items, '邀请入队')
        result = bool(invite)
        if invite:
            self.click(invite)
        if self.friends_visible():
            self.click((930, 660, 20, 20))
        return result

    def open_team(self):
        if self.team_visible():
            return
        self.home()
        for _ in range(2):
            if self.team_visible():
                return
            self.click((1161, 104, 119, 65))
        if not self.team_visible():
            raise ValueError('无法打开队伍详情，未确认人数')

    def ensure_team(self):
        self.open_team()
        items = self.texts((80, 625, 200, 75))
        create = self.find(items, '创建队伍')
        if create:
            self.click(create)
        if not self.find(self.texts((80, 625, 200, 75)), '退出队伍'):
            raise ValueError('未确认队伍创建成功，已停止邀请')
        self.home()

    def team_count(self):
        self.open_team()
        if self.find(self.texts((80, 625, 200, 75)), '创建队伍'):
            self.last_count = 0
            self.home()
            return 0
        count = slot_count(self.texts((80, 530, 1100, 60)))
        self.last_count = count
        self.home()
        return count

    def accept_invitation(self):
        # The left invitation can expire in seconds: inspect it before any window navigation.
        return self.accept_visible_invitation()

    def accept_visible_invitation(self):
        image = self.image()
        if self.match(['r5/yaoqing1.png'], (0,109,495,295), image, threshold=.7, green_mask=True):
            self.click((260,320,181,46))
            return True
        items = self.texts((0,109,495,295), image)
        accept = self.find(items, '接受')
        # The relationship label may be 好友/同帮; match the invitation sentence and
        # both controls rather than depending on the old screenshot's label.
        if (accept and self.find(items, '拒绝.*')
                and any('邀请你加入' in item.text.replace(' ','') for item in items)):
            self.click(accept)
            return True
        return False

    def follow_tick(self):
        # Do not interrupt combat or pending instance readiness by opening Team.
        items = self.texts((700, 595, 260, 115))
        ready = self.find(items, '准备')
        if ready:
            self.click(ready)
            return
        self.accept_visible_invitation()
