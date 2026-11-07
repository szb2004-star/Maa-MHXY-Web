from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from .catalog import ROOT
from .emulators import spec, identity, create as create_emulator


STOP_GRACE_SECONDS = 15
MAX_DEVICES = 10


def now():
    return datetime.now(timezone.utc).isoformat()


def kill_tree(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


class Manager:
    def __init__(self, data_dir, catalog):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.catalog = catalog
        self.lock = threading.RLock()
        self.runs = {}
        self.closed = False
        self.power_operations = {}
        self.capture_operations = {}
        self.power_messages = {}
        self.power_results = {}
        self.power_cache = {}
        self.power_cache_at = 0
        self.power_scan_lock = threading.Lock()
        self.config_file = self.data_dir / 'devices.json'
        self.devices = json.loads(self.config_file.read_text(encoding='utf-8')) if self.config_file.exists() else {}
        self.profiles_file = self.data_dir / 'profiles.json'
        self.profiles = json.loads(self.profiles_file.read_text(encoding='utf-8')) if self.profiles_file.exists() else {}
        self.activity_dir = self.data_dir / 'activity'
        self.activity_dir.mkdir(parents=True, exist_ok=True)
        self._normalize_official()
        self._migrate_profiles()

    def _normalize_official(self):
        device_changed = False
        profile_changed = False
        for device in self.devices.values():
            if device.get('resource') != '官服':
                device['resource'] = '官服'
                device_changed = True
        for profile in self.profiles.values():
            if profile.get('resource') != '官服':
                profile.update(resource='官服', version=profile.get('version', 1) + 1, updated_at=now())
                profile_changed = True
        if profile_changed:
            self.save_profiles()
        if device_changed:
            self.save()

    def save_profiles(self):
        temp = self.profiles_file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.profiles, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.profiles_file)

    def _migrate_profiles(self):
        changed = False
        for device in self.devices.values():
            if device.get('profile_id') or not device.get('tasks'):
                continue
            matching = next((p for p in self.profiles.values()
                             if p['resource'] == device['resource'] and p['tasks'] == device['tasks']), None)
            if matching is None:
                matching = self.save_profile(None, {
                    'name': self.unique_profile_name(device['name'] + '的原配置'),
                    'resource': device['resource'], 'tasks': device['tasks']})
            device['profile_id'] = matching['id']
            changed = True
        if changed:
            self.save()

    def unique_profile_name(self, base):
        base = base[:90]
        names = {p['name'].casefold() for p in self.profiles.values()}
        name, suffix = base, 2
        while name.casefold() in names:
            name = f'{base} {suffix}'
            suffix += 1
        return name

    def save_profile(self, key, profile, expected_version=None):
        name = profile['name'].strip()
        if not name:
            raise ValueError('请填写配置名称')
        self.catalog.resource_paths(profile['resource'])
        self.catalog.compile(profile['tasks'])
        with self.lock:
            previous = None
            if key is not None:
                if key not in self.profiles:
                    raise KeyError('任务配置不存在')
                previous = self.profiles[key]
                if expected_version is not None and previous['version'] != expected_version:
                    raise ValueError('这份配置已被其他操作更新，请重新打开后再保存')
            if any(p['id'] != key and p['name'].casefold() == name.casefold()
                   for p in self.profiles.values()):
                raise ValueError('配置名称已存在，请换一个名称')
            key = key or uuid.uuid4().hex
            self.profiles[key] = {
                'id': key, 'name': name, 'resource': profile['resource'],
                'tasks': copy.deepcopy(profile['tasks']),
                'version': previous['version'] + 1 if previous else 1,
                'created_at': previous['created_at'] if previous else now(), 'updated_at': now()}
            self.save_profiles()
            return copy.deepcopy(self.profiles[key])

    def list_profiles(self):
        with self.lock:
            return [{**copy.deepcopy(profile),
                     'devices': [{'id': d['id'], 'name': d['name']} for d in self.devices.values()
                                 if d.get('profile_id') == profile['id']]}
                    for profile in self.profiles.values()]

    def duplicate_profile(self, key):
        with self.lock:
            if key not in self.profiles:
                raise KeyError('任务配置不存在')
            profile = copy.deepcopy(self.profiles[key])
            profile['name'] = self.unique_profile_name(profile['name'] + ' 副本')
            return self.save_profile(None, profile)

    def delete_profile(self, key):
        with self.lock:
            if key not in self.profiles:
                raise KeyError('任务配置不存在')
            bound = [d['name'] for d in self.devices.values() if d.get('profile_id') == key]
            if bound:
                raise ValueError('配置正在被以下实例使用，请先在实例卡片切换配置：' + '、'.join(bound))
            del self.profiles[key]
            self.save_profiles()

    def effective_device(self, device):
        result = copy.deepcopy(device)
        key = device.get('profile_id')
        if key:
            if key not in self.profiles:
                raise ValueError('实例绑定的任务配置不存在，请重新选择配置')
            profile = self.profiles[key]
            result.update(resource=profile['resource'], tasks=copy.deepcopy(profile['tasks']),
                          profile_name=profile['name'], profile_version=profile['version'])
        return result

    def assign_profile(self, key, profile_id):
        with self.lock:
            device = self.get(key)
            if key in self.capture_operations:
                raise ValueError('该实例正在采集账号资料，请等待采集结束')
            if self.active(key) or key in self.power_operations:
                raise ValueError('请先停止实例，再切换任务配置')
            if profile_id is not None and profile_id not in self.profiles:
                raise KeyError('任务配置不存在')
            resource = self.profiles[profile_id]['resource'] if profile_id else self.effective_device(device)['resource']
            device.update(profile_id=profile_id, resource=resource, tasks=[])
            self.save()
            return self.effective_device(device)

    def profile_send_targets(self, profile_id):
        from .readiness import probe_ready
        with self.lock:
            if profile_id not in self.profiles:
                raise KeyError('任务配置不存在')
            package = self.catalog.game_package(self.profiles[profile_id]['resource'])
        rows = self.list_with_power(force=True)
        def inspect(row):
            return {'id': row['id'], 'device_state': {field: row.get(field) for field in
                    ('run', 'power', 'account_capture')}, **probe_ready(row, package)}
        # Only the send dialog polls this endpoint; the main device poll stays cheap.
        with ThreadPoolExecutor(max_workers=4) as executor:
            return list(executor.map(inspect, rows))

    def receive_profile(self, key, profile_id):
        from .readiness import probe_ready
        with self.lock:
            device = copy.deepcopy(self.get(key))
            if profile_id not in self.profiles:
                raise ValueError('请选择有效的任务方案')
            if self.active(key) or key in self.power_operations or key in self.capture_operations:
                raise ValueError('实例正在执行配置、开关机或采集，不能接收方案')
            package = self.catalog.game_package(self.profiles[profile_id]['resource'])
        row = next((d for d in self.list_with_power(force=True) if d['id'] == key), None)
        if row is None:
            raise KeyError('设备不存在')
        result = probe_ready(row, package)
        if not result['ready']:
            raise ValueError(result['reason'])
        with self.lock:
            current = self.get(key)
            if self.closed:
                raise ValueError('中控正在关闭')
            if any(current.get(field) != device.get(field) for field in ('address', 'adb_path', 'emulator', 'mumu')):
                raise ValueError('实例连接已变化，请重新检查状态后发送')
            # Recheck busy state under the same lock as the write: a run/capture
            # may have started while the read-only ADB check was in progress.
            return self.assign_profile(key, profile_id)

    def save(self):
        temp = self.config_file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.devices, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.config_file)

    def ensure_capacity(self, count=1):
        with self.lock:
            current = len(self.devices)
        remaining = MAX_DEVICES - current
        if count > remaining:
            raise ValueError(f'最多支持 {MAX_DEVICES} 个模拟器实例，当前已有 {current} 个，本次最多还能添加 {max(0, remaining)} 个')

    def add(self, device):
        with self.lock:
            self.ensure_capacity(1)
            for old in self.devices.values():
                if old['address'] == device['address']:
                    raise ValueError('该 ADB 地址已添加')
            key = uuid.uuid4().hex
            self.devices[key] = {'id': key, **device, 'resource': next(iter(self.catalog.resources)), 'tasks': []}
            self.save()
            return copy.deepcopy(self.devices[key])

    def import_mumu(self, instance):
        return self.import_emulator(instance)

    def import_emulator(self, instance):
        device = {k: copy.deepcopy(v) for k, v in instance.items() if k != 'state'}
        # Unknown ports are allowed until boot, using a stable non-ADB identity.
        device['address'] = device['address'] or 'emulator:' + uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(identity(device))).hex
        with self.lock:
            for old in self.devices.values():
                if identity(old) == identity(device):
                    return copy.deepcopy(old)
                if old['address'] == device['address']:
                    if spec(old):
                        raise ValueError('不同模拟器实例配置了相同的 ADB 端口，请在模拟器中修正后再导入')
                    if self.active(old['id']):
                        raise ValueError('此地址的设备正在运行，请先停止再导入')
                    old['emulator'] = copy.deepcopy(spec(device))
                    old['adb_path'] = device['adb_path']
                    self.save()
                    return copy.deepcopy(old)
            return self.add(device)

    def get(self, key):
        if key not in self.devices:
            raise KeyError('设备不存在')
        return self.devices[key]

    def active(self, key):
        run = self.runs.get(key)
        return run is not None and run['process'].poll() is None

    def update(self, key, profile):
        self.catalog.resource_paths(profile['resource'])
        if profile['tasks']:
            self.catalog.compile(profile['tasks'])
        with self.lock:
            device = self.get(key)
            if key in self.capture_operations:
                raise ValueError('该实例正在采集账号资料，请等待采集结束')
            if self.active(key) or key in self.power_operations:
                raise ValueError('请先停止设备，再修改配置')
            device.update(copy.deepcopy(profile))
            # The legacy per-device API creates an independent configuration.
            device['profile_id'] = None
            self.save()
            return copy.deepcopy(device)

    def delete(self, key):
        with self.lock:
            self.get(key)
            if key in self.capture_operations:
                raise ValueError('该实例正在采集账号资料，请等待采集结束')
            if self.active(key) or key in self.power_operations:
                raise ValueError('请先停止设备，再删除')
            del self.devices[key]
            self.runs.pop(key, None)
            self.save()

    def update_settings(self, key, settings):
        name = settings['name'].strip()
        if not name:
            raise ValueError('请填写实例名称')
        self.catalog.resource_paths(settings['resource'])
        with self.lock:
            device = self.get(key)
            if key in self.capture_operations:
                raise ValueError('该实例正在采集账号资料，请等待采集结束')
            if self.active(key) or key in self.power_operations:
                raise ValueError('请先停止实例，再修改设置')
            if device.get('profile_id') and settings['resource'] != self.effective_device(device)['resource']:
                raise ValueError('资源包由所选任务配置决定，请先编辑配置或取消选择')
            device.update(name=name, resource=settings['resource'])
            self.save()
            return self.effective_device(device)

    def list(self):
        with self.lock:
            return [{**self.effective_device(device), 'run': self.snapshot(key)} for key, device in self.devices.items()]

    def list_with_power(self, *, force=False):
        rows = self.list()
        if (force or time.monotonic() - self.power_cache_at > 2) and self.power_scan_lock.acquire(blocking=force):
            try:
                states = {}
                groups = {(spec(d).get('kind', 'mumu'), spec(d)['app_path']) for d in rows if spec(d)}
                for kind, app in groups:
                    try:
                        found = create_emulator({'kind': kind, 'app_path': app}).discover(open_manager=False)
                        for item in found:
                            states[(kind, app, spec(item)['index'])] = item['state']
                    except ValueError:
                        pass
                with self.lock:
                    self.power_cache = states
                    self.power_cache_at = time.monotonic()
            finally:
                self.power_scan_lock.release()
        with self.lock:
            for device in rows:
                mumu = spec(device)
                state = self.power_cache.get(identity(device), 'unknown') if mumu else 'unsupported'
                device['account_capture'] = copy.deepcopy(self.capture_operations.get(device['id']))
                device['power'] = {'status': self.power_operations.get(device['id'], state),
                                   'on': state in ('running', 'starting'), 'supported': bool(mumu),
                                   'phase': self.power_messages.get(device['id'], ''),
                                   'scene_status': self.power_results.get(device['id'], 'unknown') if state in ('running', 'starting') else 'unknown'}
        return rows

    def set_power(self, key, on):
        with self.lock:
            if self.closed:
                raise ValueError('服务正在关闭')
            device = copy.deepcopy(self.get(key))
            if not spec(device):
                raise ValueError('请先通过 MuMu / 雷电实例列表导入，才能开关机')
            if key in self.capture_operations:
                raise ValueError('该实例正在采集账号资料，请等待采集结束')
            if key in self.power_operations:
                raise ValueError('该实例正在开关机，请稍后')
            run = self.runs.get(key) if self.active(key) else None
            if on and run:
                raise ValueError('配置正在运行或启动模拟器，请稍候')
            self.power_operations[key] = 'starting' if on else 'stopping'
            self.power_results[key] = 'loading' if on else 'unknown'
            self.power_messages.pop(key, None)
            if not on and run:
                self.stop(key)
        try:
            if not on and run:
                self._stop_later(run)
            mumu = create_emulator(spec(device))
            index = spec(device)['index']
            if on:
                def report(message):
                    with self.lock:
                        self.power_messages[key] = message
                mumu.discover()
                stop_event = threading.Event()
                address = mumu.ensure_running(index, stop_event, report)
                if not address:
                    raise ValueError('模拟器启动已取消')
                with self.lock:
                    self.devices[key]['address'] = address
                    self.save()
                    self.power_operations[key] = 'launching_game'
                if not mumu.launch_game(index, address, self.catalog.game_package('官服'), stop_event, report):
                    raise ValueError('游戏启动已取消')
                from .game_login import enter_game
                with self.lock:
                    self.power_operations[key] = 'logging_in'
                login_device = {**device, 'address': address}
                enter_game(login_device, self.data_dir / 'logins' / key / uuid.uuid4().hex, report)
                with self.lock:
                    self.power_cache[identity(device)] = 'running'
                    self.power_cache_at = time.monotonic()
                with self.lock:
                    self.power_results[key] = 'ready'
                return {'on': True, 'status': 'running', 'game_started': True, 'scene_ready': True}
            rows = mumu.info(index)
            if not rows:
                raise ValueError('模拟器实例不存在，请重新导入')
            target = 'running' if on else 'stopped'
            if rows[0].get('state') != target:
                mumu.command('close', index, timeout=20)
            deadline = time.monotonic() + 45
            while rows[0].get('state') != target:
                if time.monotonic() > deadline:
                    raise ValueError('等待模拟器开关机超时，请检查模拟器窗口')
                time.sleep(.5)
                rows = mumu.info(index)
                if not rows:
                    raise ValueError('无法确认模拟器实例状态')
            with self.lock:
                self.power_cache[identity(device)] = target
                self.power_cache_at = time.monotonic()
            return {'on': on, 'status': target}
        except Exception as exc:
            with self.lock:
                self.power_results[key] = 'error'
                self.power_messages[key] = '启动/登录失败：' + str(exc)
            raise
        finally:
            with self.lock:
                self.power_operations.pop(key, None)
                if self.power_results.get(key) != 'error':
                    self.power_messages.pop(key, None)

    def snapshot(self, key):
        run = self.runs.get(key)
        if run is None:
            return {'status': 'idle', 'current': 0, 'total': 0, 'task': '', 'active': False}
        return {**run['state'], 'active': self.active(key)}

    def log(self, run, message):
        run['seq'] += 1
        message = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', message)
        item = {'seq': run['seq'], 'time': now(), 'message': message[:8000]}
        run['logs'].append(item)
        # Persist logs for this run. Buffers and files are bounded by one run; older
        # run files are retained for diagnosis and may be removed by the operator.
        with run['log_path'].open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(item, ensure_ascii=False) + '\n')

    def start(self, key):
        with self.lock:
            if self.closed:
                raise ValueError('服务正在关闭')
            device = self.effective_device(self.get(key))
            if key in self.capture_operations:
                raise ValueError('该实例正在采集账号资料，请等待采集结束')
            if key in self.power_operations:
                raise ValueError('模拟器正在开关机，请稍后再启动配置')
            if self.active(key) or key in self.power_operations:
                raise ValueError('该模拟器已有任务运行')
            plan = self.catalog.compile(device['tasks']) if device['tasks'] or not spec(device) else []
            paths = self.catalog.resource_paths(device['resource'])
            run_id = uuid.uuid4().hex
            instance_dir = self.data_dir / 'runs' / key / run_id
            instance_dir.mkdir(parents=True)
            env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8',
                   'MHXY_INSTANCE_DIR': str(instance_dir),
                   'MHXY_INSTANCE_DATA_DIR': str(self.data_dir / 'instances' / key)}
            process = subprocess.Popen([sys.executable, '-u', '-m', 'web.worker'], cwd=ROOT,
                                       env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                       start_new_session=(os.name != 'nt'))
            run = {'process': process, 'logs': deque(maxlen=2000), 'seq': 0, 'device_id': key,
                   'stop_lock': threading.Lock(),
                   'log_path': instance_dir / 'web.jsonl',
                   'state': {'id': run_id, 'status': 'starting', 'current': 0, 'total': len(plan),
                             'profile_name': device.get('profile_name', ''),
                             'profile_version': device.get('profile_version'),
                             'task': '', 'started_at': now()}}
            self.runs[key] = run
            self._record_start(run, key, device, plan)
            try:
                process.stdin.write(json.dumps({'device': device, 'plan': plan,
                                               'resource_paths': [str(p) for p in paths],
                                               'game_package': self.catalog.game_package(device['resource'])}, ensure_ascii=False) + '\n')
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                kill_tree(process)
                run['state']['status'] = 'failed'
                self.log(run, '启动执行进程失败')
                raise ValueError('启动执行进程失败') from None
            threading.Thread(target=self._watch, args=(run,), daemon=True).start()
            return self.snapshot(key)

    def _watch(self, run):
        process = run['process']
        try:
            for line in process.stdout:
                line = line.rstrip()
                with self.lock:
                    if line.startswith('@@WEB@@'):
                        try:
                            event = json.loads(line[7:])
                        except ValueError:
                            self.log(run, line)
                            continue
                        kind = event.pop('kind', '')
                        if kind == 'progress':
                            if run['state']['status'] != 'stopping':
                                run['state']['status'] = 'running'
                            run['state'].update(event)
                            run['state'].update(task_detail='', sub_current=None, sub_total=None, phase='', detail_updated_at=None)
                            self.log(run, f'任务 {event["current"]}/{event["total"]}：{event["task"]}')
                            self._mark_task(run, event['current'] - 1)
                        elif kind == 'task_detail':
                            allowed = {k: event[k] for k in ('task_detail', 'sub_current', 'sub_total', 'phase', 'detail_updated_at', 'detail_source') if k in event}
                            run['state'].update(allowed)
                        elif kind == 'team_claim':
                            self._team_claim(run, event)
                        elif kind == 'team_state':
                            team = run.get('team', {})
                            if team and team.get('group') == event.get('group'):
                                run['state']['team'] = {**team, 'message': event.get('message', ''),
                                                        'members': event.get('members')}
                                record = run.get('record', {})
                                tasks = record.get('tasks', [])
                                index = run['state'].get('current', 0) - 1
                                if 0 <= index < len(tasks):
                                    tasks[index]['team_role'] = team['role']
                                    tasks[index]['detail'] = event.get('message', '')
                                    self._save_record(record)
                        elif kind == 'task_skipped':
                            tasks = run.get('record', {}).get('tasks', [])
                            index = event.get('index')
                            if isinstance(index, int) and 0 <= index < len(tasks) and tasks[index]['status'] == 'pending':
                                tasks[index].update(status='skipped', detail=str(event.get('reason', ''))[:160])
                                self._save_record(run['record'])
                        elif kind == 'device':
                            key = run['device_id']
                            if self.runs.get(key) is run and key in self.devices:
                                self.devices[key]['address'] = event['address']
                                self.save()
                        elif kind == 'scene_ready':
                            key = run['device_id']
                            if self.runs.get(key) is run:
                                self.power_results[key] = 'ready'
                                self.power_messages.pop(key, None)
                        elif kind == 'status':
                            run['state']['status'] = event['status']
                        elif kind == 'log':
                            self.log(run, event['message'])
                    elif line:
                        self.log(run, line)
            code = process.wait()
            with self.lock:
                state = run['state']
                if state['status'] not in ('completed', 'failed', 'stopped', 'ready'):
                    state['status'] = 'stopped' if state['status'] == 'stopping' else 'failed'
                if code != 0 and state['status'] == 'completed':
                    state['status'] = 'failed'
                state['finished_at'] = now()
                self.log(run, f'执行结束：{state["status"]}（退出码 {code}）')
                self._finish_record(run)
                self._team_finished(run)
        finally:
            process.stdout.close()
            process.stdin.close()

    def _team_send(self, run, message):
        try:
            run['process'].stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            run['process'].stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def _team_claim(self, run, event):
        group, role = event.get('group'), event.get('role')
        if not isinstance(group, str) or not group or role not in ('leader', 'member'):
            self._team_send(run, {'type':'team_claim_result', 'ok':False, 'message':'无效的组队角色'})
            return
        peers = [peer for peer in self.runs.values() if peer is not run
                 and peer.get('team', {}).get('group') == group and peer['process'].poll() is None]
        leaders = [peer for peer in peers if peer['team']['role'] == 'leader']
        if role == 'leader' and leaders:
            message = f'编组“{group}”存在多个队长，请仅在一个账号保留此编组后重试'
            for peer in peers:
                self._team_send(peer, {'type':'team_abort', 'message':message})
            self._team_send(run, {'type':'team_claim_result', 'ok':False, 'message':message})
            self.log(run, message)
            return
        run['team'] = {'group':group, 'role':role}
        run['state']['team'] = dict(run['team'])
        self._team_send(run, {'type':'team_claim_result', 'ok':True,
                              'leader':leaders[0]['device_id'] if leaders else (run['device_id'] if role == 'leader' else None)})
        if role == 'leader':
            for peer in peers:
                self._team_send(peer, {'type':'team_leader', 'leader':run['device_id']})
        elif not leaders:
            # A member may finish menu scanning just after its already-started leader exits.
            recent = [peer for peer in self.runs.values() if peer is not run
                      and peer.get('team') == {'group':group, 'role':'leader'}
                      and peer['state'].get('finished_at', '') >= run['state'].get('started_at', '~')]
            if recent:
                leader = max(recent, key=lambda peer:peer['state']['finished_at'])
                self._team_send(run, {'type':'team_finished', 'success':leader['state']['status']=='completed',
                                     'message':'队长配置失败或已停止，结束跟队'})
        self.log(run, f'编组“{group}”：已确认{"队长" if role == "leader" else "队员"}')

    def _team_finished(self, run):
        team = run.get('team', {})
        if team.get('role') != 'leader':
            return
        success = run['state']['status'] == 'completed'
        for peer in self.runs.values():
            if (peer is not run and peer.get('team', {}).get('group') == team['group']
                    and peer.get('team', {}).get('role') == 'member' and peer['process'].poll() is None):
                self._team_send(peer, {'type':'team_finished', 'success':success,
                                     'message':'队长配置失败或已停止，结束跟队'})

    def _record_start(self, run, key, device, plan):
        run['record'] = {
            'id': run['state']['id'], 'device_id': key, 'device_name': device['name'],
            'profile_name': device.get('profile_name', ''), 'profile_version': device.get('profile_version'),
            'status': 'starting', 'started_at': run['state']['started_at'], 'finished_at': None,
            'tasks': [{'name': task['name'], 'entry': task.get('entry', ''), 'status': 'pending',
                       'started_at': None, 'finished_at': None, 'seconds': None} for task in plan]}
        self._save_record(run['record'])

    def _save_record(self, record):
        try:
            path = self.activity_dir / f"{record['id']}.json"
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, path)
            files = sorted(self.activity_dir.glob('*.json'), key=lambda item: item.stat().st_mtime, reverse=True)
            for stale in files[400:]:
                stale.unlink(missing_ok=True)
        except OSError:
            pass

    def _mark_task(self, run, index):
        record = run.get('record')
        if not record:
            return
        tasks, stamp = record['tasks'], now()
        current = datetime.fromisoformat(stamp)
        for task in tasks:
            if task['status'] == 'running':
                task['status'] = 'completed'
                task['finished_at'] = stamp
                if task['started_at']:
                    task['seconds'] = round((current - datetime.fromisoformat(task['started_at'])).total_seconds(), 1)
        if 0 <= index < len(tasks):
            tasks[index].update(status='running', started_at=stamp, finished_at=None, seconds=None)
        if run['state'].get('status') != 'stopping':
            record['status'] = 'running'
        self._save_record(record)

    def _finish_record(self, run):
        record = run.get('record')
        if not record:
            return
        state = run['state']
        status = state.get('status', 'stopped')
        stamp = state.get('finished_at') or now()
        record['status'] = status
        record['finished_at'] = stamp
        if status == 'failed':
            for item in reversed(run['logs']):
                message = (item or {}).get('message', '')
                if message and not message.startswith('执行结束'):
                    record['error'] = message[:300]
                    break
        finished = datetime.fromisoformat(stamp)
        for task in record['tasks']:
            if task['status'] == 'running':
                task['status'] = {'completed': 'completed', 'failed': 'failed',
                                  'stopped': 'stopped'}.get(status, 'stopped')
                task['finished_at'] = stamp
                if task['started_at']:
                    task['seconds'] = round((finished - datetime.fromisoformat(task['started_at'])).total_seconds(), 1)
            elif task['status'] == 'pending':
                task['status'] = 'skipped'
        self._save_record(record)

    def activity(self, limit=80, device=None):
        limit = max(1, min(int(limit), 200))
        with self.lock:
            records = {}
            for path in self.activity_dir.glob('*.json'):
                try:
                    record = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if isinstance(record, dict) and record.get('id'):
                    records[record['id']] = record
            for run in self.runs.values():
                record = run.get('record')
                if record:
                    records[record['id']] = record
            rows = [copy.deepcopy(record) for record in records.values()
                    if not device or record.get('device_id') == device]
            rows.sort(key=lambda record: record.get('started_at') or '', reverse=True)
            return rows[:limit]

    def logs(self, key, after=0):
        with self.lock:
            self.get(key)
            run = self.runs.get(key)
            return {'run': self.snapshot(key), 'logs': [x for x in run['logs'] if x['seq'] > after] if run else []}

    def stop(self, key):
        with self.lock:
            self.get(key)
            run = self.runs.get(key)
            if not self.active(key):
                return self.snapshot(key)
            if run['state']['status'] == 'stopping':
                return self.snapshot(key)
            run['state']['status'] = 'stopping'
            self.log(run, '收到停止请求，等待当前动作退出；15 秒后仍未退出则终止进程组')
            try:
                run['process'].stdin.write('stop\n')
                run['process'].stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            threading.Thread(target=self._stop_later, args=(run,), daemon=True).start()
            return self.snapshot(key)

    def _stop_later(self, run):
        # Stop requests and server shutdown can overlap. Only one thread may
        # terminate a given process tree; others observe its final return code.
        with run['stop_lock']:
            try:
                run['process'].wait(timeout=STOP_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                kill_tree(run['process'])

    def close(self):
        with self.lock:
            self.closed = True
            keys = [key for key in self.runs if self.active(key)]
            for key in keys:
                self.stop(key)
            runs = [self.runs[key] for key in keys]
        with ThreadPoolExecutor(max_workers=max(1, len(runs))) as pool:
            list(pool.map(self._stop_later, runs))
