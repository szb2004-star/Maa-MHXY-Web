"""Read-only live checks for receiving a task profile. Never boots or clicks a device."""
from __future__ import annotations
import re
import subprocess

from .catalog import ASSETS


def unavailable(reason):
    return {'ready': False, 'reason': reason}


def busy_reason(device):
    if device.get('run', {}).get('active'):
        return '正在执行配置'
    if (device.get('account_capture') or {}).get('active'):
        return '正在采集账号资料'
    if device.get('power', {}).get('status') in ('starting', 'launching_game', 'logging_in', 'stopping'):
        return '正在开关机或登录'
    return ''


def scene_visible(png):
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return False
    height, width = image.shape[:2]
    if height <= 0 or width <= height or abs(width / height - 16 / 9) > .04:
        return False
    image = cv2.resize(image, (1280, 720), interpolation=cv2.INTER_AREA)
    root = ASSETS / 'resource/base/image'
    def matches(names, roi, threshold=.78):
        x, y, w, h = roi
        area = image[y:y+h, x:x+w]
        for name in names:
            try:
                template = cv2.imdecode(np.frombuffer((root / name).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            except OSError:
                continue
            if template is None or template.shape[0] > area.shape[0] or template.shape[1] > area.shape[1]:
                continue
            _, score, _, _ = cv2.minMaxLoc(cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED))
            if score >= threshold:
                return True
        return False
    # A modal may leave parts of the HUD visible. Require a usable world screen.
    if matches(['qiandao/fuli.png'], (414, 17, 487, 103)):
        return False
    if matches(['r5/haoyou_zhujiemian.png'], (352, 0, 543, 103)):
        return False
    if matches(['duiwu/duiwu-zudui.png', 'duiwu/duiwu-duiwu.png'], (0, 0, 229, 106)):
        return False
    return matches(['zonghe/jiahao.png', 'zonghe/chenghao.png',
                    'zonghe/baoguo.png', 'zonghe/baoguo_man.png'], (1197, 540, 78, 157))


def probe_ready(device, package):
    reason = busy_reason(device)
    if reason:
        return unavailable(reason)
    power = device.get('power', {})
    if power.get('supported') and not power.get('on'):
        return unavailable('未开机' if power.get('status') == 'stopped' else '无法确认开机状态')
    if not device.get('adb_path') or not device.get('address') or device['address'].startswith(('emulator:', 'mumu:')):
        return unavailable('ADB 未连接')
    base = [device['adb_path'], '-s', device['address']]
    try:
        connected = subprocess.run([*base, 'get-state'], capture_output=True, timeout=3)
        if connected.returncode or connected.stdout.strip() != b'device':
            return unavailable('ADB 未连接')
        window = subprocess.run([*base, 'shell', 'dumpsys', 'window'], capture_output=True, timeout=3)
        if window.returncode:
            return unavailable('无法读取游戏状态')
        lines = window.stdout.decode('utf-8', errors='replace').splitlines()
        current = [line for line in lines if 'mCurrentFocus=' in line]
        focus = '\n'.join(current or [line for line in lines if 'mFocusedApp=' in line])
        if not re.search(r'(?<![\w.])' + re.escape(package) + r'/', focus):
            return unavailable('游戏未打开或不在前台')
        screen = subprocess.run([*base, 'exec-out', 'screencap', '-p'], capture_output=True, timeout=4)
        if screen.returncode or not screen.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
            return unavailable('无法获取游戏画面')
        if not scene_visible(screen.stdout):
            return unavailable('尚未确认进入游戏场景，请返回游戏主界面')
        return {'ready': True, 'reason': '已连接并进入游戏场景'}
    except (OSError, subprocess.TimeoutExpired):
        return unavailable('连接或画面检查失败，请检查 ADB')
    except Exception:
        return unavailable('游戏场景检查失败，请重试')
