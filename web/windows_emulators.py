"""Windows CLI adapters. Only explicit instance indexes are ever mutated."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .mumu import MuMu


def decode(value):
    if isinstance(value, str):
        return value
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            pass
    return value.decode('utf-8', errors='replace')


def registry_paths():
    import winreg
    paths = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 0, winreg.KEY_READ | view) as root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                            try:
                                name = winreg.QueryValueEx(key, 'DisplayName')[0].lower()
                                if not any(x in name for x in ('mumu', 'ldplayer', '雷电')):
                                    continue
                                for field in ('InstallLocation', 'UninstallString'):
                                    try:
                                        value = winreg.QueryValueEx(key, field)[0].strip('"')
                                        if field == 'UninstallString':
                                            value = str(Path(value.split('.exe')[0] + '.exe').parent)
                                        paths.append(Path(value))
                                    except OSError:
                                        pass
                            except OSError:
                                pass
            except OSError:
                pass
    return paths


class WindowsEmulator(MuMu):
    kind = ''
    names = ()

    def __init__(self, app_path=''):
        if sys.platform != 'win32':
            raise ValueError('此模拟器接入需要在 Windows 中控上运行')
        roots = [Path(app_path).expanduser()] if app_path else registry_paths()
        if not app_path:
            for drive in ('C:', 'D:', 'E:'):
                roots.extend(Path(drive + '/') / path for path in (
                    'Program Files/Netease/MuMu Player 12', 'Program Files/Netease/MuMuPlayer-12.0',
                    'LDPlayer/LDPlayer9', 'LDPlayer/LDPlayer14', 'leidian/LDPlayer9'))
            roots.extend(Path(os.environ[k]) / sub for k in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA') if os.environ.get(k)
                         for sub in ('Netease/MuMu Player 12', 'Netease/MuMuPlayer-12.0', 'LDPlayer/LDPlayer9', 'LDPlayer/LDPlayer14'))
            roots.extend(Path(found) for name in self.names if (found := shutil.which(name)))
        candidates = []
        for root in roots:
            if root.is_file() and root.name.lower() in [n.lower() for n in self.names]:
                candidates.append(root)
            else:
                candidates.extend(root / sub / name for sub in ('', 'nx_main', 'shell') for name in self.names)
        self.tool = next((p.resolve() for p in candidates if p.is_file()), None)
        if self.tool is None:
            raise ValueError('未找到模拟器命令行工具，请填写安装目录或 ' + ' / '.join(self.names) + ' 的完整路径')
        self.app = self.tool
        self.adb = next((p for p in (self.tool.parent / 'adb.exe', self.tool.parent / 'adb_server.exe') if p.is_file()), None)
        if self.adb is None:
            raise ValueError('未找到模拟器自带的 adb.exe，请检查安装目录')

    def run_cli(self, args, timeout=10):
        try:
            result = subprocess.run([str(self.tool), *map(str, args)], cwd=str(self.tool.parent),
                                    capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f'模拟器命令执行失败：{exc}') from None
        out, err = decode(result.stdout), decode(result.stderr)
        if result.returncode:
            raise ValueError((err or out or '模拟器命令失败').strip()[:500])
        return out.strip()

    def discover(self, open_manager=True):
        return [self.normalize(row) for row in self.info()]

    def normalize(self, row):
        index = int(row['index'])
        if not 0 <= index < 99999:
            raise ValueError('模拟器返回了无效实例编号')
        port = self.port(row)
        return {'name': row['name'], 'address': f'127.0.0.1:{port}' if port else '',
                'adb_path': str(self.adb), 'config': {}, 'state': row['state'],
                'emulator': {'kind': self.kind, 'app_path': str(self.app), 'index': index}}

    def port(self, row):
        try:
            port = int(row.get('adb_port', 0))
            return port if 0 < port < 65536 else None
        except (ValueError, TypeError):
            return None


class WindowsMuMu(WindowsEmulator):
    kind = 'mumu'
    names = ('mumu-cli.exe', 'MuMuManager.exe')

    def info(self, index='all'):
        try:
            data = json.loads(self.run_cli(['info', '--vmindex', index]))
        except json.JSONDecodeError:
            raise ValueError('MuMu 返回了无法识别的信息，请更新 MuMu 后重试') from None
        if isinstance(data, dict) and (data.get('error_code') or data.get('errcode')):
            raise ValueError(f'MuMu：{data.get("message", data)}')
        if isinstance(data, dict) and 'return' in data:
            data = data['return']
        if isinstance(data, dict) and 'results' in data:
            data = data['results']
        if isinstance(data, dict):
            data = [data] if 'index' in data else list(data.values())
        if not isinstance(data, list) or any(not isinstance(row, dict) or 'index' not in row or 'name' not in row for row in data):
            raise ValueError('MuMu 实例列表格式不兼容，请更新模拟器')
        rows = []
        for row in data:
            if row.get('error_code'):
                raise ValueError(f'MuMu 实例错误：{row["error_code"]}')
            state = 'running' if row.get('is_android_started') else 'starting' if row.get('is_process_started') else 'stopped'
            rows.append({**row, 'index': int(row['index']), 'state': state})
        return rows if index == 'all' else [row for row in rows if row['index'] == int(index)]

    def command(self, action, index, *args, timeout=10):
        if action in ('open', 'close'):
            cli = ['control', '--vmindex', int(index), 'launch' if action == 'open' else 'shutdown']
        elif action == 'control' and args[:2] == ('--action', 'open_app'):
            cli = ['control', '--vmindex', int(index), 'app', 'launch', '--package', args[3]]
        else:
            raise ValueError('不支持的 MuMu 控制命令')
        output = self.run_cli(cli, timeout)
        if output.startswith('{'):
            try:
                result = json.loads(output)
            except ValueError:
                raise ValueError('MuMu 控制命令返回了无效 JSON') from None
            if result.get('error_code') or result.get('errcode'):
                raise ValueError(f'MuMu 控制失败：{result.get("message", output)}')
        return output


class LDPlayer(WindowsEmulator):
    label = '雷电'
    kind = 'ldplayer'
    names = ('ldconsole.exe', 'dnconsole.exe')

    def info(self, index='all'):
        rows = []
        for fields in csv.reader(io.StringIO(self.run_cli(['list2']))):
            if not fields or not any(fields):
                continue
            # A title can contain commas; the numeric suffix is fixed at 5 or 8 fields.
            suffix = 8 if len(fields) >= 10 and all(x.strip().lstrip('-').isdigit() for x in fields[-8:]) else 5
            try:
                number = int(fields[0]); tail = fields[-suffix:]
                if len(fields) < suffix + 2 or len(tail) != suffix or not all(x.strip().lstrip('-').isdigit() for x in tail):
                    raise ValueError()
                if not 0 <= number < 99999:
                    continue
                running = int(tail[2]) == 1
                started = running or int(tail[3]) > 0
                rows.append({'index': number, 'name': ','.join(fields[1:-suffix]),
                             'state': 'running' if running else 'starting' if started else 'stopped',
                             'adb_port': 5555 + number * 2})
            except (ValueError, IndexError):
                raise ValueError('雷电 list2 返回了无法识别的信息，请更新雷电后重试') from None
        return rows if index == 'all' else [row for row in rows if row['index'] == int(index)]

    def command(self, action, index, *args, timeout=10):
        if action in ('open', 'close'):
            cli = ['launch' if action == 'open' else 'quit', '--index', int(index)]
        elif action == 'control' and args[:2] == ('--action', 'open_app'):
            cli = ['runapp', '--index', int(index), '--packagename', args[3]]
        else:
            raise ValueError('不支持的雷电控制命令')
        return self.run_cli(cli, timeout)
