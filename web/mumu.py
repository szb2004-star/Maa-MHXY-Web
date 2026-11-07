"""MuMu for Mac integration using its official, installed mumutool CLI."""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time


class MuMu:
    label = 'MuMu'

    def __new__(cls, app_path='', **kwargs):
        if cls is MuMu and sys.platform == 'win32':
            from .windows_emulators import WindowsMuMu
            return object.__new__(WindowsMuMu)
        return super().__new__(cls)

    def __init__(self, app_path='', *, data_root=None):
        if sys.platform != 'darwin':
            raise ValueError('MuMu 实例直连目前支持 macOS；其他系统请使用下方 ADB 添加')
        candidates = [Path(app_path).expanduser()] if app_path else [
            Path('/Applications/MuMuPlayer.app'), Path.home() / 'Applications/MuMuPlayer.app']
        self.app = next((p.resolve() for p in candidates
                         if (p / 'Contents/MacOS/mumutool').is_file()), None)
        if self.app is None:
            raise ValueError('未找到 MuMuPlayer.app，请填写应用完整路径，或使用 ADB 添加')
        self.tool = self.app / 'Contents/MacOS/mumutool'
        self.adb = self.app / 'Contents/MacOS/MuMuEmulator.app/Contents/MacOS/tools/adb'
        if not self.adb.is_file():
            alternate = self.app / 'Contents/MacOS/adb'
            self.adb = alternate if alternate.is_file() else Path(shutil.which('adb') or '')
        if not self.adb.is_file():
            raise ValueError('未找到 MuMu 自带的 ADB，请检查 MuMu 安装是否完整')
        self.data_root = Path(data_root) if data_root else Path.home() / 'Library/Application Support/com.netease.mumu.nemux'

    def command(self, *args, timeout=10):
        try:
            result = subprocess.run([str(self.tool), *map(str, args)], capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f'MuMu 命令执行失败：{exc}') from None
        if result.returncode:
            raise ValueError((result.stderr or result.stdout or 'MuMu 命令失败').strip()[:500])
        try:
            data = json.loads(result.stdout)
        except ValueError:
            raise ValueError('MuMu 返回了无法识别的数据，请更新 MuMu 后重试') from None
        if data.get('errcode', 0) != 0:
            raise ValueError(f'MuMu：{data.get("message") or data["errcode"]}')
        return data.get('return', {})

    def info(self, index='all'):
        result = self.command('info', index)
        return [result] if 'index' in result else result.get('results', [])

    def discover(self, open_manager=True):
        try:
            rows = self.info()
        except ValueError as exc:
            if not open_manager or 'invalidPort' not in str(exc):
                raise
            # Opening the manager does not boot any Android instance.
            try:
                subprocess.run(['open', '-g', '-a', str(self.app)], check=True, timeout=10,
                               capture_output=True)
            except (OSError, subprocess.SubprocessError):
                raise ValueError('无法打开 MuMu 管理器，请手动打开后重试') from None
            deadline = time.monotonic() + 20
            while True:
                try:
                    rows = self.info()
                    break
                except ValueError as retry:
                    if 'invalidPort' not in str(retry) or time.monotonic() >= deadline:
                        raise ValueError('无法连接 MuMu 管理器，请先打开 MuMu 后重试') from None
                    time.sleep(.5)
        return [self.normalize(row) for row in rows]

    def normalize(self, row):
        index = int(row['index'])
        if index < 0:
            raise ValueError('MuMu 返回了无效实例编号')
        port = self.port(row)
        return {'name': row['name'], 'address': f'127.0.0.1:{port}' if port else '',
                'adb_path': str(self.adb), 'config': {}, 'state': row.get('state', 'unknown'),
                'mumu': {'app_path': str(self.app), 'index': index}}

    def port(self, row):
        # Use reported/configured ports; cloned instances may have custom ports.
        # Never derive a port from an instance number.
        raw = row.get('adb_port')
        if raw is None:
            path = self.data_root / 'vms' / str(int(row['index'])) / 'setting/vm.json'
            if path.is_file():
                try:
                    raw = json.loads(path.read_text(encoding='utf-8')).get('customAdbPort')
                except (OSError, ValueError):
                    pass
        try:
            port = int(raw)
            return port if 0 < port < 65536 else None
        except (TypeError, ValueError):
            return None

    def ensure_running(self, index, stopping: threading.Event, log, timeout=180):
        if stopping.is_set():
            return None
        rows = self.info(index)
        if stopping.is_set():
            return None
        if len(rows) != 1 or int(rows[0]['index']) != index:
            raise ValueError(f'{self.label} 实例不存在，请重新导入实例')
        if rows[0].get('state') not in ('running', 'starting'):
            log(f'正在启动 {self.label} 实例 #{index}：{rows[0]["name"]}')
            self.command('open', index, timeout=20)
        else:
            log(f'{self.label} 实例 #{index} 已运行，正在等待 Android 就绪…')
        deadline = time.monotonic() + timeout
        while not stopping.is_set():
            if time.monotonic() >= deadline:
                raise ValueError(f'等待 {self.label} 启动超时，请在模拟器窗口检查启动状态和 ADB 开关')
            rows = self.info(index)
            if not rows:
                raise ValueError(f'{self.label} 实例已被移除')
            port = self.port(rows[0])
            if port and rows[0].get('state') == 'running':
                address = f'127.0.0.1:{port}'
                try:
                    subprocess.run([str(self.adb), 'connect', address], capture_output=True, timeout=5)
                    boot = subprocess.run([str(self.adb), '-s', address, 'shell', 'getprop', 'sys.boot_completed'],
                                          capture_output=True, timeout=5)
                    if boot.returncode == 0 and boot.stdout.strip() == b'1':
                        log(f'{self.label} #{index} 已就绪，ADB 已连接：{address}')
                        return address
                except (OSError, subprocess.TimeoutExpired):
                    pass
            stopping.wait(1)
        return None

    def adb_shell(self, address, *args):
        try:
            result = subprocess.run([str(self.adb), '-s', address, 'shell', *args],
                                    capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f'读取 Android 状态失败：{exc}') from None
        if result.returncode:
            raise ValueError((result.stderr or result.stdout or 'ADB 命令失败').strip()[:500])
        return result.stdout.strip()

    def game_in_foreground(self, address, package):
        windows = self.adb_shell(address, 'dumpsys', 'window')
        focus = '\n'.join(line for line in windows.splitlines()
                          if 'mCurrentFocus=' in line or 'mFocusedApp=' in line)
        return bool(re.search(r'(?<![\w.])' + re.escape(package) + r'/', focus))

    def screen_size(self, address):
        result = subprocess.run([str(self.adb), '-s', address, 'exec-out', 'screencap', '-p'],
                                capture_output=True, timeout=10, check=True)
        if len(result.stdout) < 24 or not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Android 未返回有效截图，无法确认画面方向')
        return struct.unpack('>II', result.stdout[16:24])

    def launch_game(self, index, address, package, stopping, log, timeout=60):
        if stopping.is_set():
            return False
        if not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+', package):
            raise ValueError('游戏包名无效')
        installed = self.adb_shell(address, 'pm', 'path', package)
        if not any(line.startswith('package:') for line in installed.splitlines()):
            raise ValueError(f'实例中未安装 {package}，请检查游戏客户端与资源包是否匹配')
        if stopping.is_set():
            return False
        if self.game_in_foreground(address, package):
            log(f'梦幻西游已在前台：{package}')
        else:
            log(f'正在打开梦幻西游：{package}')
            self.command('control', index, '--action', 'open_app', '--package', package, timeout=20)
        deadline = time.monotonic() + timeout
        warned = False
        while not stopping.is_set():
            if self.game_in_foreground(address, package):
                width, height = self.screen_size(address)
                if width > height and abs(width / height - 16 / 9) <= 16 / 9 * .02:
                    log(f'游戏已打开，画面为 {width}×{height} 横屏 16:9')
                    return True
                if not warned:
                    log(f'游戏已打开，当前画面 {width}×{height}，正在等待横屏…')
                    warned = True
            if time.monotonic() >= deadline:
                raise ValueError('未确认游戏横屏就绪，请检查模拟器中的游戏窗口、弹窗及横屏设置')
            stopping.wait(1)
        return False
