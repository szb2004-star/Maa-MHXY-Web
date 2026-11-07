"""Local build identity, upstream release check and git fast-forward update."""
from __future__ import annotations

import json
import re
import subprocess
from importlib import metadata
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'gitlihang/Maa_MHXY_MG'
USER_AGENT = 'Maa-MHXY-Web'


def _git(*args, timeout=20):
    result = subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode:
        message = (result.stderr or result.stdout).strip().splitlines()
        raise ValueError((message[-1] if message else 'git 命令失败')[:300])
    return result.stdout.strip()


def _version_key(tag):
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', tag or '')
    return tuple(int(part) for part in match.groups()) if match else None


def kernel():
    try:
        installed = metadata.version('MaaFw')
    except metadata.PackageNotFoundError:
        installed = ''
    required = ''
    requirements = ROOT / 'requirements.txt'
    if requirements.is_file():
        match = re.search(r'^\s*MaaFw\s*==\s*([\w.\-]+)', requirements.read_text(encoding='utf-8'), re.MULTILINE)
        if match:
            required = match.group(1)
    return {'installed': installed, 'required': required,
            'matches': bool(installed and required and installed.lstrip('v') == required.lstrip('v'))}


def current():
    kernel_version = kernel()
    try:
        tag = _git('describe', '--tags', '--always')
        commit = _git('rev-parse', '--short', 'HEAD')
        date = _git('log', '-1', '--format=%cI')
        branch = _git('rev-parse', '--abbrev-ref', 'HEAD')
        dirty = bool(_git('status', '--porcelain'))
    except (OSError, subprocess.SubprocessError, ValueError):
        return {'local': {'version': '', 'commit': '', 'date': '', 'branch': '', 'dirty': False, 'git': False},
                'kernel': kernel_version, 'repository': REPOSITORY}
    return {'local': {'version': tag, 'commit': commit, 'date': date, 'branch': branch,
                      'dirty': dirty, 'git': True},
            'kernel': kernel_version, 'repository': REPOSITORY}


def _release_notes(tag, timeout=8):
    try:
        request = Request(f'https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}',
                          headers={'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github+json'})
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
        return (payload.get('body') or '').strip()[:1500]
    except (URLError, OSError, ValueError):
        return ''


def check_updates(timeout=25):
    info = current()
    try:
        _git('fetch', '--tags', '--quiet', '--force', timeout=timeout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        info['error'] = f'无法连接 GitHub 检查更新：{exc}'
        info['has_update'] = False
        return info
    try:
        tags = [tag for tag in _git('tag', '--sort=-v:refname').splitlines() if _version_key(tag)]
    except ValueError:
        tags = []
    latest = tags[0] if tags else ''
    local_key = _version_key(info['local']['version'])
    latest_key = _version_key(latest)
    info['latest'] = latest
    info['has_update'] = bool(local_key and latest_key and latest_key > local_key)
    info['notes'] = _release_notes(latest) if latest and info['has_update'] else ''
    return info


def apply_update():
    info = current()
    if not info['local']['git']:
        raise ValueError('当前目录不是 git 仓库，无法自动更新')
    before = info['local']['version']
    try:
        output = _git('pull', '--ff-only', timeout=300)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ValueError(f'更新失败：{exc}') from None
    after = current()['local']
    return {'before': before, 'after': after['version'], 'changed': before != after['version'],
            'commit': after['commit'], 'dirty': after['dirty'], 'output': output[-800:],
            'restart': before != after['version']}
