"""Bounded login into the existing selected role; no credentials or daily tasks."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .catalog import ROOT, Catalog


def enter_game(device, directory, report, timeout=120, stopping=None):
    """Stream real stages to the card; supervise and cancel the native login process."""
    import queue
    import threading
    from .manager import kill_tree
    if stopping is not None and stopping.is_set():
        raise ValueError('登录已取消')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = {'device': device, 'directory': str(directory), 'timeout': timeout,
               'resources': [str(p) for p in Catalog().resource_paths('官服')]}
    report('正在识别游戏登录状态…')
    process = subprocess.Popen([sys.executable, '-u', '-m', 'web.game_login'], cwd=ROOT,
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
        errors='replace', start_new_session=(os.name != 'nt'))
    lines = queue.Queue()
    def read():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)
    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout + 35
    outcome = None
    try:
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
        process.stdin.flush()
        process.stdin.close()
        with (directory / 'login-output.log').open('w', encoding='utf-8') as logfile:
            written = 0
            while True:
                if stopping is not None and stopping.is_set():
                    raise ValueError('登录已取消')
                if time.monotonic() >= deadline:
                    raise ValueError('登录等待超时，请检查当前游戏画面；诊断保存在 ' + str(directory))
                try:
                    line = lines.get(timeout=.2)
                except queue.Empty:
                    continue
                if line is None:
                    break
                if written < 1024 * 1024:
                    logfile.write(line); written += len(line)
                if not line.startswith('@@LOGIN@@'):
                    continue
                event = json.loads(line[9:])
                if event.get('event') == 'phase':
                    report(event['message'])
                else:
                    outcome = event
        process.wait(timeout=5)
        if process.returncode or not outcome or not outcome.get('success'):
            raise ValueError((outcome or {}).get('message', '登录执行失败，请检查诊断：' + str(directory)))
        report('已登录，已关闭登录弹窗并确认进入游戏场景')
        return True
    finally:
        if process.poll() is None:
            kill_tree(process)
        thread.join(timeout=2)
        process.stdout.close()


def login(config, report=None):
    from maa.controller import AdbController
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.toolkit import Toolkit

    directory=Path(config['directory']);directory.mkdir(parents=True,exist_ok=True)
    last_phase = None
    image = None
    def phase(message):
        nonlocal last_phase
        if message == last_phase:
            return
        last_phase = message
        with (directory / 'stages.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'time': time.time(), 'message': message}, ensure_ascii=False) + '\n')
        snapshot()
        if report:
            report(message)
    def snapshot():
        if image is not None:
            from PIL import Image
            Image.fromarray(image[:, :, ::-1]).save(directory / 'last-screen.png')

    Toolkit.init_option(directory)
    resource=Resource();resource.use_cpu()
    for path in config['resources']:
        if not resource.post_bundle(path).wait().succeeded:raise ValueError('登录识别资源加载失败')
    from maa.pipeline import JTemplateMatch, JOCR
    scene_param=JTemplateMatch(template=['zonghe/jiahao.png','zonghe/chenghao.png',
        'zonghe/baoguo.png','zonghe/baoguo_man.png'],roi=(1197,540,78,157))
    friends_param=JTemplateMatch(template=['r5/haoyou_zhujiemian.png'],roi=(352,0,543,103))
    team_param=JTemplateMatch(template=['duiwu/duiwu-zudui.png','duiwu/duiwu-duiwu.png'],roi=(0,0,229,106))
    character_param=JOCR(expected=['人物属性'],roi=(450,0,450,85),threshold=.7)
    welfare_param = JTemplateMatch(template=['qiandao/fuli.png'], roi=(414,17,487,103))
    welfare_title = JOCR(expected=['^福利$'], roi=(520,15,240,85), threshold=.8)
    monthly_title = JOCR(expected=['月卡每日返利'], roi=(400,55,480,100), threshold=.8)
    dismiss_param = JOCR(expected=['点击.*空白.*关闭.*界面'], roi=(330,625,640,90), threshold=.8)
    monthly_dismiss = JOCR(expected=['点击.*空白.*领取本日奖励'], roi=(380,625,530,80), threshold=.8)
    login_param=JOCR(expected=['登录游戏','进入游戏','开始游戏'],roi=(350,400,600,280),threshold=.7)
    blocked_param=JOCR(expected=['验证码','安全验证','扫码登录','手机登录'],roi=(250,80,800,500),threshold=.75)
    def recognize(kind,param,image):
        task=tasker.post_recognition(kind,param,image).wait().get()
        return next((n.recognition for n in task.nodes if n.recognition and n.recognition.hit),None) if task else None
    d=config['device'];controller=AdbController(d['adb_path'],d['address'],config=d.get('config',{}),
        **{key:d[key] for key in ('screencap_methods','input_methods') if d.get(key) is not None})
    if not controller.post_connection().wait().succeeded:raise ValueError('登录时无法连接模拟器')
    tasker=Tasker()
    if not tasker.bind(resource,controller):raise ValueError('无法初始化登录识别器')
    deadline=time.monotonic()+config['timeout'];last_click=0;consecutive=0
    popup_attempts = {}
    phase('正在识别登录页、登录弹窗和游戏主界面')
    try:
        while time.monotonic()<deadline:
            image=controller.post_screencap().wait().get()
            if image is None:
                raise ValueError('登录时未能获取游戏截图')
            # Inspect overlays before the HUD: HUD buttons can remain visible behind a modal.
            panel_target = None
            panel_phase = None
            if recognize('TemplateMatch', welfare_param, image) or recognize('OCR', welfare_title, image):
                panel_target = (1154, 58)
                panel_phase = '已登录，正在关闭福利弹窗'
            elif recognize('OCR', monthly_title, image):
                prompt = recognize('OCR', monthly_dismiss, image)
                if prompt and prompt.box:
                    panel_target = (int(prompt.box.x + prompt.box.w / 2), int(prompt.box.y + prompt.box.h / 2))
                    panel_phase = '已登录，正在收取本日月卡奖励并关闭遮罩'
                else:
                    phase('已登录，正在等待月卡弹窗动画结束')
                    consecutive = 0
                    time.sleep(.5)
                    continue
            else:
                prompt = recognize('OCR', dismiss_param, image)
                if prompt and prompt.box:
                    panel_target = (int(prompt.box.x + prompt.box.w / 2), int(prompt.box.y + prompt.box.h / 2))
                    panel_phase = '已登录，正在关闭登录公告'
                elif recognize('TemplateMatch',friends_param,image):
                    panel_target=(1143,47); panel_phase='已登录，正在关闭好友窗口'
                elif recognize('TemplateMatch',team_param,image):
                    panel_target=(1204,34); panel_phase='已登录，正在关闭队伍窗口'
                elif recognize('OCR',character_param,image):
                    panel_target=(1105,45); panel_phase='已登录，正在关闭人物窗口'
            if panel_target:
                consecutive = 0
                phase(panel_phase)
                popup_attempts[panel_phase] = popup_attempts.get(panel_phase, 0) + 1
                if popup_attempts[panel_phase] > 6:
                    raise ValueError('登录弹窗未能关闭：' + panel_phase + '；截图：' + str(directory / 'last-screen.png'))
                if not controller.post_click(*panel_target).wait().succeeded:
                    raise ValueError('关闭登录弹窗失败')
                time.sleep(.7)
                continue
            scene=recognize('TemplateMatch',scene_param,image)
            if scene and scene.hit:
                consecutive+=1
                phase('正在连续确认游戏场景，等待登录弹窗全部结束')
                if consecutive>=3:
                    phase('已进入游戏场景，主界面连续确认成功')
                    return
                time.sleep(1)
                continue
            consecutive=0
            blocked=recognize('OCR',blocked_param,image)
            if blocked and blocked.hit:
                raise ValueError('登录需要账号或验证码，请在模拟器中手动完成后重试')
            button=recognize('OCR',login_param,image)
            if button and button.hit and button.box:
                phase('已找到登录按钮，正在登录并等待进入游戏')
                if time.monotonic()-last_click>=10:
                    x,y,w,h=button.box.x,button.box.y,button.box.w,button.box.h
                    if not controller.post_click(int(x+w/2),int(y+h/2)).wait().succeeded:
                        raise ValueError('点击登录游戏失败')
                    last_click=time.monotonic()
            else:
                phase('等待游戏加载或角色登录界面；尚未确认进入场景')
            time.sleep(1)
        raise ValueError('进入场景超时；最后状态：' + str(last_phase) + '；截图：' + str(directory / 'last-screen.png'))
    except Exception:
        snapshot()
        raise


def main():
    try:
        config=json.loads(sys.stdin.readline())
        login(config, lambda message: print('@@LOGIN@@' + json.dumps({'event':'phase','message':message},ensure_ascii=False),flush=True))
        print('@@LOGIN@@'+json.dumps({'success':True}),flush=True)
    except Exception as exc:
        print('@@LOGIN@@'+json.dumps({'success':False,'message':str(exc)},ensure_ascii=False),flush=True)
        sys.exit(1)


if __name__=='__main__':main()
