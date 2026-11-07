"""One isolated MaaFramework + custom Agent pair for each emulator run."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import traceback

from .catalog import ROOT


def emit(kind, **data):
    print('@@WEB@@' + json.dumps({'kind': kind, **data}, ensure_ascii=False), flush=True)


def run(config):
    from maa.agent_client import AgentClient
    from maa.controller import AdbController
    from maa.resource import Resource
    from maa.tasker import Tasker, TaskerEventSink
    from maa.toolkit import Toolkit

    instance_dir = Path(os.environ['MHXY_INSTANCE_DIR'])
    instance_dir.mkdir(parents=True, exist_ok=True)
    Toolkit.init_option(instance_dir)
    stopping = threading.Event()
    tasker = Tasker()
    from .teamup import TeamMailbox
    team_mailbox = TeamMailbox(stopping, emit)

    class Events(TaskerEventSink):
        def on_raw_notification(self, tasker, msg, details):
            # Node names aid diagnosis; never forward attach/custom parameters (API keys).
            node = details.get('name', details.get('entry', ''))
            emit('log', message=f'{msg} {node}')

    sink = Events()
    tasker.add_sink(sink)
    from .progress import make_progress_sink
    progress_sink = make_progress_sink(emit)
    tasker.add_context_sink(progress_sink)

    def commands():
        # Keep listening for coordinator replies; stop and EOF still interrupt every wait.
        for line in sys.stdin:
            if line.strip() == 'stop':
                break
            try:
                command = json.loads(line)
                if isinstance(command, dict):
                    team_mailbox.receive(command)
                    if command.get('type') == 'team_abort':
                        tasker.post_stop()
            except ValueError:
                break
        stopping.set()
        tasker.post_stop()

    threading.Thread(target=commands, daemon=True).start()
    device = config['device']
    from .emulators import spec, create as create_emulator
    if spec(device) and any(task['entry'] == 'WebAutoTeam' for task in config['plan']) and device.get('screencap_methods') is None:
        from maa.define import MaaAdbScreencapMethodEnum
        device['screencap_methods'] = int(MaaAdbScreencapMethodEnum.Encode)
    if spec(device):
        mumu = create_emulator(spec(device))
        # The manager may have been closed after importing the instance.
        mumu.discover()
        def report(message):
            emit('log', message=message)
            emit('task_detail', phase=message)
        address = mumu.ensure_running(spec(device)['index'], stopping, report)
        if stopping.is_set():
            return 'stopped'
        device['address'] = address
        emit('device', address=address)
        from .catalog import Catalog
        package = config.get('game_package') or Catalog().game_package(device['resource'])
        if not mumu.launch_game(spec(device)['index'], address, package, stopping,
                                report):
            return 'stopped'
        from .game_login import enter_game
        try:
            enter_game(device, instance_dir / 'login', report, stopping=stopping)
        except ValueError:
            if stopping.is_set():
                return 'stopped'
            raise
        if stopping.is_set():
            return 'stopped'
        emit('scene_ready')
        if not config['plan']:
            emit('log', message='模拟器和游戏已打开；未配置任务，本次不执行日常任务')
            return 'ready'
    client = AgentClient()
    client.set_timeout(30000)
    agent = None
    try:
        resource = Resource()
        if not client.bind(resource):
            raise RuntimeError('绑定自定义 Agent 失败')
        agent = subprocess.Popen([sys.executable, '-u', '-m', 'web.agent', client.identifier],
                                 cwd=ROOT, stdin=subprocess.DEVNULL)
        if not client.connect():
            raise RuntimeError('连接自定义 Agent 失败，请检查依赖和运行日志')
        for path in config['resource_paths']:
            if stopping.is_set():
                return 'stopped'
            if not resource.post_bundle(path).wait().succeeded:
                raise RuntimeError(f'加载资源失败：{path}')
        device = config['device']
        controller = AdbController(device['adb_path'], device['address'],
                                   config=device.get('config', {}),
                                   **{k: device[k] for k in ('screencap_methods', 'input_methods') if device.get(k) is not None})
        emit('log', message='正在连接模拟器并测试控制方式…')
        if not controller.post_connection().wait().succeeded:
            raise RuntimeError('连接模拟器失败，请确认 ADB 已启用且设备在线')
        if not tasker.bind(resource, controller) or not tasker.inited:
            raise RuntimeError('初始化任务执行器失败')
        if not client.register_sink(resource, controller, tasker):
            raise RuntimeError('注册原项目事件检查器失败')
        for index, task in enumerate(config['plan']):
            if stopping.is_set():
                return 'stopped'
            progress_sink.begin(task['name'])
            emit('progress', current=index + 1, total=len(config['plan']), task=task['name'])
            if task['entry'] == 'WebAutoTeam':
                progress_sink.begin('')  # Team assembly reports its own phase and real member count.
                from .teamup import TeamOptions, TeamStopped, run_teamup
                from .teamup_ui import GameTeamUI
                try:
                    role = run_teamup(GameTeamUI(tasker, controller, team_mailbox, device),
                                      TeamOptions.from_override(task['pipeline_override']), team_mailbox, emit)
                except TeamStopped:
                    return 'stopped'
                if role == 'member':
                    # The remainder of this shared profile is the leader's task sequence.
                    for skipped in range(index + 1, len(config['plan'])):
                        emit('task_skipped', index=skipped, reason='队员由队长带队，跳过后续队长流程')
                    return 'completed'
                continue
            job = tasker.post_task(task['entry'], task['pipeline_override']).wait()
            if stopping.is_set():
                return 'stopped'
            team_mailbox.check()
            if not job.succeeded:
                raise RuntimeError(f'任务失败或被原项目检查器停止：{task["name"]}')
        return 'completed'
    finally:
        if tasker.running:
            tasker.post_stop().wait()
        client.disconnect()
        if agent:
            try:
                agent.wait(timeout=5)
            except subprocess.TimeoutExpired:
                agent.terminate()
                try:
                    agent.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    agent.kill()
                    agent.wait()


def main():
    config = json.loads(sys.stdin.readline())
    try:
        status = run(config)
        emit('status', status=status)
    except Exception as exc:
        emit('log', message=str(exc))
        # Tracebacks contain source locations only, not config/locals.
        traceback.print_exc()
        emit('status', status='failed')
        sys.exit(1)


if __name__ == '__main__':
    main()
