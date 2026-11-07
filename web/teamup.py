"""Group-based team assembly. Game operations and coordinator are injectable."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import queue
import re
import time

ENTRY = 'WebAutoTeam'
TASK_NAME = '编组自动组队'


class TeamStopped(Exception):
    pass


@dataclass(frozen=True)
class TeamOptions:
    group: str = '自动组队'
    wait_seconds: int = 360

    @classmethod
    def from_override(cls, overrides):
        data = overrides.get(ENTRY, {}).get('attach', {})
        group = data.get('group', '自动组队')
        seconds = data.get('wait_seconds', 360)
        if not isinstance(group, str) or not group.strip() or len(group.strip()) > 20:
            raise ValueError('好友编组名称须为 1 至 20 个字符')
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 10 <= seconds <= 1800:
            raise ValueError('组队等待时间须为 10 至 1800 秒')
        return cls(group.strip(), seconds)


def group_label(text):
    """Strip the game's friend-count suffix, preserving the actual group name."""
    return re.sub(r'[（(]\s*\d+\s*(?:[/／]\s*\d+\s*)?[)）]\s*$', '', text).strip()


class TeamMailbox:
    """Replies arrive over the existing supervisor stdin pipe; no network token needed."""
    def __init__(self, stopping, emit):
        self.stopping = stopping
        self.emit = emit
        self.messages = queue.Queue()
        self.error = None
        self.finished = None
        self.leader_seen = False

    def receive(self, message):
        self.messages.put(message)

    def check(self):
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            kind = message.get('type')
            if kind == 'team_abort':
                self.error = message.get('message', '组队已终止')
            elif kind == 'team_leader':
                self.leader_seen = True
            elif kind == 'team_finished':
                self.leader_seen = True
                self.finished = message.get('success', False)
                if not self.finished:
                    self.error = message.get('message', '队长配置失败或已停止，结束跟队')
            elif kind == 'team_claim_result':
                self.claim_result = message
                if message.get('leader'):
                    self.leader_seen = True
        if self.error:
            raise ValueError(self.error)
        if self.stopping.is_set():
            raise TeamStopped()

    def claim(self, group, role):
        self.claim_result = None
        self.emit('team_claim', group=group, role=role)
        deadline = time.monotonic() + 10
        while self.claim_result is None:
            self.check()
            if time.monotonic() >= deadline:
                raise ValueError('中控未确认组队角色，已停止，避免重复创建队伍')
            self.stopping.wait(.05)
        if not self.claim_result.get('ok'):
            raise ValueError(self.claim_result.get('message', '组队角色冲突'))


def run_teamup(ui, options, mailbox, emit, clock=time.monotonic):
    """Return leader after 5/5 verification; member after leader finishes or team dissolves."""
    def status(message, count=None, role=None):
        data = {'phase': message, 'task_detail': message, 'detail_source': 'game_team_panel',
                'detail_updated_at': datetime.now(timezone.utc).isoformat()}
        if count is not None:
            data.update(sub_current=count, sub_total=5)
        emit('task_detail', **data)
        emit('team_state', group=options.group, role=role, message=message, members=count)

    mailbox.check()
    # False is allowed only after the complete, verified group menu was scanned.
    status(f'正在检查好友编组“{options.group}”…')
    leader = ui.select_group(options.group)
    role = 'leader' if leader else 'member'
    mailbox.claim(options.group, role)
    status(f'识别为{"队长" if leader else "队员"} · 编组：{options.group}', role=role)
    ui.home()
    deadline = clock() + options.wait_seconds
    if hasattr(ui, 'set_deadline'):
        ui.set_deadline(deadline)
    if leader:
        ui.ensure_team()
        while True:
            mailbox.check()
            count = ui.team_count()
            if count == 5:
                ui.wait(.6)
                if ui.team_count() == 5:
                    if hasattr(ui, 'set_deadline'):
                        ui.set_deadline(None)
                    ui.home()
                    status('队伍已满员 5/5，继续队长配置', 5, role)
                    return role
            if clock() >= deadline:
                raise ValueError(f'组队超时：编组“{options.group}”，当前 {count if count is not None else "未知"}/5，未执行后续任务')
            status(f'队长循环邀请 · 当前 {count if count is not None else "未知"}/5', count, role)
            # A fresh group selection is required for every pass: never invite from All Contacts.
            if not ui.select_group(options.group):
                raise ValueError(f'邀请期间找不到编组“{options.group}”，已停止')
            invited = 0
            for candidate in ui.group_candidates(options.group):
                mailbox.check()
                if clock() >= deadline:
                    break
                if ui.invite_candidate(candidate, options.group):
                    emit('log', message=f'编组“{options.group}”：已点击邀请入队（本轮第 {invited+1} 人）')
                    invited += 1
                    if invited >= 4:
                        break
                # Bound each pass to four successful invitation actions.
            ui.home()
            ui.wait(min(3, max(0, deadline-clock())))
    else:
        joined = False
        absent = 0
        checked_existing = False
        invitation_pending = False
        while True:
            mailbox.check()
            if mailbox.finished is True:
                if not joined:
                    count = ui.team_count()
                    joined = count is not None and count >= 2
                if not joined:
                    raise ValueError('队长已结束，但未确认本实例入队，请检查邀请及编组成员')
                ui.home()
                status('队长配置已结束，队员跟队完成', role=role)
                return role
            if not joined:
                invitation_pending = ui.accept_invitation() or invitation_pending
                if invitation_pending or not checked_existing:
                    count = ui.team_count()
                    checked_existing = True
                    joined = count is not None and count >= 2
                if joined:
                    if hasattr(ui, 'set_deadline'):
                        ui.set_deadline(None)
                    status('已入队，跟随队长执行任务', count, role)
                elif clock() >= deadline:
                    raise ValueError(f'等待组队邀请超时：编组“{options.group}”，未确认入队')
            else:
                ui.follow_tick()
                # With a local leader, its explicit completion controls the end of following.
                if not mailbox.leader_seen:
                    count = ui.team_count()
                    absent = absent + 1 if count in (0, 1) else 0
                    if absent >= 2:
                        ui.home()
                        status('队伍已解散或已离队，跟队结束', role=role)
                        return role
            ui.wait(2)
