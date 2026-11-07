"""Translate the upstream ProjectInterface v2 tasks into validated task plans."""
from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path

TASK_GROUPS = {
    '个人日常': ['师门任务', '宝图任务', '秘境降妖', '三界奇缘', '趣闻鉴赏', '福利签到', '帮派签到', '运镖普通', '科举乡试', '活跃领取'],
    '组队日常': ['编组自动组队', '副本320(69)', '副本520(89/115)', '捉鬼任务-无限/手动选择执行几轮', '捉鬼（混队）'],
    '周常': ['帮派任务', '迷魂塔', '门派闯关', '召唤灵海底', '九黎演武'],
    '日常功能': ['启动游戏', '启动app', '停止游戏', '创建队伍', '邀请队员', '队员挂机', '队长踢人', '退出队伍', '整理背包', '出售商会', '挖宝图', '家园整理'],
    '养成服务': ['宠物祈福', '五行修业', '任务链（高级功能）', '工坊考古', '活力打工', '特殊助战', '帮派守护兽'],
}

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'


def merge(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


class Catalog:
    def __init__(self, assets=ASSETS, layout_file=None):
        self.layout_file = Path(layout_file) if layout_file else None
        self.layout_lock = threading.RLock()
        self.layout = {}
        if self.layout_file and self.layout_file.exists():
            self.layout = json.loads(self.layout_file.read_text(encoding="utf-8"))
        self.assets = Path(assets)
        self.interface = json.loads((self.assets / 'interface.json').read_text(encoding='utf-8'))
        self.tasks, self.options = {}, {}
        for filename in self.interface.get('import', []):
            data = json.loads((self.assets / filename).read_text(encoding='utf-8'))
            self.options.update(data.get('option', {}))
            for task in data.get('task', []):
                self.tasks[task['name']] = task
        web_tasks = json.loads((Path(__file__).parent / 'teamup_task.json').read_text(encoding='utf-8'))
        self.options.update(web_tasks['option'])
        self.tasks.update({task['name']: task for task in web_tasks['task']})
        self.resources = {
            item['name']: item for item in self.interface['resource']
            if item['name'] == '官服' and 'ADB' in item.get('controller', [])
        }

    def grouped_tasks(self):
        defaults = {name: group for group, names in TASK_GROUPS.items() for name in names}
        groups = {group: [] for group in TASK_GROUPS}
        seen = set()
        for group in groups:
            names = self.layout.get(group, [])
            if not isinstance(names, list):
                continue
            for name in names:
                if isinstance(name, str) and name in self.tasks and name not in seen:
                    groups[group].append(name)
                    seen.add(name)
        for group, names in TASK_GROUPS.items():
            for name in names:
                if name in self.tasks and name not in seen:
                    groups[group].append(name)
                    seen.add(name)
        for name in self.tasks:
            if name not in seen:
                groups[defaults.get(name, '日常功能')].append(name)
        return groups

    def public(self):
        with self.layout_lock:
            groups = self.grouped_tasks()
            positions = {name: (group, index) for group, names in groups.items() for index, name in enumerate(names)}
            return {'tasks': [{**task, 'category': positions[task['name']][0],
                               'category_order': positions[task['name']][1]} for task in self.tasks.values()],
                    'categories': list(TASK_GROUPS), 'options': self.options, 'project': self.interface['name']}

    def move_task(self, name, category, before=None):
        with self.layout_lock:
            if name not in self.tasks or category not in TASK_GROUPS:
                raise ValueError('任务或分类不存在')
            groups = self.grouped_tasks()
            if before == name:
                return self.public()
            for names in groups.values():
                if name in names:
                    names.remove(name)
            target = groups[category]
            if before is not None and before not in target:
                raise ValueError('目标任务位置已变化，请刷新后重试')
            target.insert(target.index(before) if before is not None else len(target), name)
            if self.layout_file:
                self.layout_file.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.layout_file.with_suffix('.tmp')
                temporary.write_text(json.dumps(groups, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                temporary.replace(self.layout_file)
            self.layout = groups
            return self.public()

    def resource_paths(self, name):
        if name not in self.resources:
            raise ValueError('请选择有效的 ADB 资源包')
        return [(self.assets / p.removeprefix('./')).resolve()
                for p in self.resources[name]['path']]

    def game_package(self, name):
        # Apply channel overlays in the same order as the native resource bundles.
        node = {}
        for directory in self.resource_paths(name):
            path = directory / 'pipeline/start.json'
            if path.is_file():
                data = json.loads(path.read_text(encoding='utf-8'))
                merge(node, data.get('启动游戏', {}))
        package = node.get('package', '')
        if not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+', package):
            raise ValueError('资源包没有有效的游戏启动包名')
        return package

    def description(self, name):
        task = self.tasks.get(name)
        if task is None:
            raise ValueError('任务不存在')
        path = task.get('description', '')
        if not path:
            return '该任务暂无说明。'
        resolved = (ROOT / path).resolve()
        if not resolved.is_relative_to(ROOT / 'docs') or not resolved.is_file():
            return '该任务暂无说明。'
        return resolved.read_text(encoding='utf-8')

    def compile(self, requested):
        if not isinstance(requested, list) or not 1 <= len(requested) <= 100:
            raise ValueError('请选择 1 至 100 个任务')
        auto_positions = [i for i, item in enumerate(requested) if isinstance(item, dict) and item.get('name') == '编组自动组队']
        if auto_positions and auto_positions != [0]:
            raise ValueError('编组自动组队须放在配置第一项，且只能添加一次')
        plan = []
        for item in requested:
            if not isinstance(item, dict) or item.get('name') not in self.tasks:
                raise ValueError('任务不存在')
            task = self.tasks[item['name']]
            values = item.get('options', {})
            if not isinstance(values, dict):
                raise ValueError('任务选项必须为对象')
            overrides = {}
            for option in task.get('option', []):
                self._option(option, values, overrides, set())
            if task.get('execution') == 'web_teamup':
                from .teamup import TeamOptions
                TeamOptions.from_override(overrides)
            plan.append({'name': task['name'], 'entry': task['entry'],
                         'pipeline_override': overrides})
        return plan

    def _option(self, name, values, overrides, ancestors):
        if name in ancestors or name not in self.options:
            raise ValueError(f'任务选项引用错误：{name}')
        ancestors = ancestors | {name}
        spec = self.options[name]
        selected = values.get(name)
        if spec.get('type') == 'input':
            if selected is None:
                selected = {}
            if not isinstance(selected, dict):
                raise ValueError(f'{name}：请输入有效参数')
            replacements = {}
            for field in spec['inputs']:
                value = selected.get(field['name'], field.get('default', ''))
                if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                    raise ValueError(f'{field["name"]}：参数类型错误')
                if field.get('verify') and not re.fullmatch(field['verify'], str(value)):
                    raise ValueError(f'{field["name"]}：格式不符合要求')
                try:
                    if field.get('pipeline_type') == 'int':
                        value = int(str(value))
                    else:
                        value = str(value)
                except ValueError:
                    raise ValueError(f'{field["name"]}：需要填写整数') from None
                replacements['{' + field['name'] + '}'] = value

            def substitute(value):
                if isinstance(value, str):
                    if value in replacements:
                        return replacements[value]
                    for placeholder, replacement in replacements.items():
                        value = value.replace(placeholder, str(replacement))
                    return value
                if isinstance(value, list):
                    return [substitute(x) for x in value]
                if isinstance(value, dict):
                    return {k: substitute(v) for k, v in value.items()}
                return value
            merge(overrides, substitute(spec.get('pipeline_override', {})))
            return
        cases = spec.get('cases', [])
        default = spec.get('default_case', spec.get('default'))
        checkbox = spec.get('type') == 'checkbox'
        if selected is None:
            selected = default if default is not None else ([] if checkbox else cases[0]['name'])
        if checkbox:
            if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
                raise ValueError(f'{name}：请选择有效选项')
            chosen = selected
        else:
            if not isinstance(selected, str):
                raise ValueError(f'{name}：请选择有效选项')
            chosen = [selected]
        if any(x not in {c['name'] for c in cases} for x in chosen):
            raise ValueError(f'{name}：未知选项')
        for case in cases:
            if case['name'] not in chosen:
                continue
            merge(overrides, case.get('pipeline_override', {}))
            for child in case.get('option', []):
                self._option(child, values, overrides, ancestors)
