"""Read-only task-panel telemetry; never estimate an unobserved count."""
from datetime import datetime, timezone
import re
import time

ALIASES = {'师门': ('师门',), '捉鬼': ('捉鬼', '抓鬼'), '秘境': ('秘境', '降妖'),
           '宝图': ('宝图',), '运镖': ('运镖', '镖银'), '帮派': ('帮派',),
           '副本': ('副本', '侠士'), '门派': ('门派',),
           '考古': ('考古',), '任务链': ('任务链', '跑环')}


def panel_progress(text, task):
    aliases = next((words for name, words in ALIASES.items() if name in task), (task,))
    lines = [re.sub(r'\s+', '', line) for line in text.splitlines() if line.strip()]
    start = next((i for i, line in enumerate(lines) if any(word and word in line for word in aliases)), None)
    if start is None:
        return None
    chosen = [lines[start]]
    other = tuple(word for values in ALIASES.values() for word in values if word not in aliases)
    for line in lines[start+1:start+3]:
        if any(word in line for word in other):
            break
        chosen.append(line)
    detail = ' · '.join(chosen)[:180]
    numerator = denominator = None
    match = re.search(r'(\d{1,3})[/／](\d{1,3})', ''.join(chosen))
    if match:
        current, total = map(int, match.groups())
        if 0 <= current <= total and total > 0:
            numerator, denominator = current, total
    return {'task_detail': detail, 'sub_current': numerator, 'sub_total': denominator,
            'detail_source': 'game_task_panel',
            'detail_updated_at': datetime.now(timezone.utc).isoformat()}


def make_progress_sink(emit):
    # Native imports stay lazy so parser tests do not require an emulator or IPC.
    from maa.context import ContextEventSink
    from maa.event_sink import NotificationType

    class ProgressSink(ContextEventSink):
        def __init__(self):
            self.task = ''
            self.last_read = 0
            self.reading = False
            self.last_phase = ''

        def begin(self, task):
            self.task = task
            self.last_read = 0
            self.last_phase = ''

        def on_node_recognition(self, context, noti_type, detail):
            if self.reading or not self.task or noti_type not in (NotificationType.Succeeded, NotificationType.Failed):
                return
            phase = detail.focus if isinstance(detail.focus, str) else detail.name
            if not re.search(r'[\u4e00-\u9fff]', phase):
                phase = '正在处理当前任务'
            if phase != self.last_phase:
                emit('task_detail', phase=phase[:160])
                self.last_phase = phase
            if time.monotonic() - self.last_read < 5:
                return
            self.last_read = time.monotonic()
            self.reading = True
            try:
                image = context.tasker.controller.cached_image
                if image is None:
                    return
                height, width = image.shape[:2]
                # Same right-hand task panel used by the upstream shimen recognizer.
                x, y = int(width * .79), int(height * .14)
                node = '__WebReadOnlyTaskPanel'
                result = context.run_recognition(node, image, pipeline_override={node: {
                    'recognition': 'OCR', 'roi': [x, y, width-x, int(height*.58)],
                    'expected': [''], 'threshold': .6}})
                if not result or not result.all_results:
                    return
                parts = sorted(result.all_results, key=lambda r: (r.box[1], r.box[0]))
                text = '\n'.join(r.text for r in parts if hasattr(r, 'text'))
                progress = panel_progress(text, self.task)
                if progress:
                    emit('task_detail', **progress)
            except Exception:
                # Telemetry must not interrupt gameplay or the original task chain.
                pass
            finally:
                self.reading = False
    return ProgressSink()
