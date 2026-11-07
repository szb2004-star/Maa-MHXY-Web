"""Capture idle game activity pages with ADB, or extract icons from saved pages.

Run from the project root:
  python tools/collect_task_icons.py --capture-dir /tmp/mhxy-icons --capture-live
Without --capture-live, only saved screenshots and bundled templates are read.
Full screenshots stay in capture-dir; only individual icons enter web/static.
"""
import argparse
import io
import json
from pathlib import Path
import subprocess
import time
import urllib.request

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
# Keep the entire artwork, including the attached game label on HUD buttons.
# Some upstream recognition templates intentionally contain only half an icon;
# use the full live screenshot for those instead.
SOURCES = [
    ('shimen', ['师门任务'], 'activities.png', (510, 165, 620, 275)),
    ('zhuagui', ['捉鬼（混队）', '捉鬼任务-无限/手动选择执行几轮'], 'activities.png', (1123, 165, 1233, 275)),
    ('active-reward', ['活跃领取'], 'activities.png', (632, 797, 742, 907)),
    ('guild', ['帮派签到'], 'current.png', (1464, 940, 1561, 1053)),
    ('bag', ['整理背包'], 'current.png', (1807, 820, 1917, 937)),
    ('assist', ['特殊助战'], 'current.png', (1686, 940, 1804, 1059)),
    ('mijing', ['秘境降妖'], 'asset:mijing/mijing_rukou.png', (13, 13, 83, 83)),
    ('keju', ['科举乡试'], 'asset:richangdati/kejuxiangshi_weikaishi2.png', (16, 22, 84, 90)),
    ('sanjie', ['三界奇缘'], 'asset:richangdati/sanjieqiyuan_weikaishi3.png', (20, 21, 90, 91)),
    ('wuxing', ['五行修业'], 'asset:wuxing/wuxingxiuye1.png', (9, 10, 79, 80)),
    ('guild-task', ['帮派任务'], 'asset:bangpairenwu/rukou.png', (10, 10, 80, 80)),
    ('jiuli', ['九黎演武'], 'asset:wujian/jiuli_weikaishi1.png', (5, 13, 73, 81)),
    ('treasure', ['宝图任务', '挖宝图'], 'activities.png', (850, 791, 978, 919)),
]


def capture(args):
    rows = json.load(urllib.request.urlopen(args.url.rstrip('/') + '/api/devices', timeout=15))
    candidates = [d for d in rows if d.get('power', {}).get('on') and not d['run']['active']
                  and not (d.get('account_capture') or {}).get('active')
                  and d['power']['status'] == 'running'
                  and (not args.device_id or d['id'] == args.device_id)]
    if len(candidates) != 1:
        raise SystemExit('请用 --device-id 指定一个已进入游戏、空闲的实例')
    device = candidates[0]
    base = [device['adb_path'], '-s', device['address']]

    def adb(*command):
        return subprocess.run([*base, *command], capture_output=True, check=True, timeout=15).stdout

    def screen(name):
        data = adb('exec-out', 'screencap', '-p')
        image = Image.open(io.BytesIO(data))
        if abs(image.width / image.height - 16 / 9) > .04:
            raise SystemExit('请使用横屏 16:9 分辨率')
        image.resize((1920, 1080)).save(args.capture_dir / name)
        return image

    original = screen('current.png')
    import sys
    sys.path.insert(0, str(ROOT))
    from web.readiness import scene_visible
    if not scene_visible((args.capture_dir / 'current.png').read_bytes()):
        raise SystemExit('请先返回游戏主场景，再采集；脚本不会自动处理弹窗或登录')

    def tap(x, y):
        adb('shell', 'input', 'tap', str(round(x * original.width / 1920)),
            str(round(y * original.height / 1080)))
        time.sleep(.8)

    tap(525, 55)
    try:
        tap(320, 180)
        screen('activities.png')
        tap(320, 287)
        screen('challenge.png')
        tap(320, 395)
        screen('leisure.png')
    finally:
        tap(1710, 70)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-dir', type=Path, required=True)
    parser.add_argument('--capture-live', action='store_true')
    parser.add_argument('--device-id')
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    args.capture_dir.mkdir(parents=True, exist_ok=True)
    if args.capture_live:
        capture(args)
    destination = ROOT / 'web/static/task-icons'
    destination.mkdir(exist_ok=True)
    manifest = {}
    for key, tasks, source, box in SOURCES:
        path = ROOT / 'assets/resource/base/image' / source[6:] if source.startswith('asset:') else args.capture_dir / source
        if not path.exists():
            print('Missing source:', source)
            continue
        image = Image.open(path).convert('RGB')
        if box:
            if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                raise ValueError('Invalid crop: ' + source)
            image = image.crop(box)
        image.save(destination / (key + '.png'))
        for task in tasks:
            manifest[task] = {'url': '/static/task-icons/' + key + '.png',
                              'source': source, 'box': box}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Collected icons for', len(manifest), 'tasks')


if __name__ == '__main__':
    main()
