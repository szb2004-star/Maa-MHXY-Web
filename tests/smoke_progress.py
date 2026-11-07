"""Native read-only OCR/event test; no emulator input or gameplay actions."""
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

from tests.smoke_native import SyntheticController
from web.catalog import Catalog
from web.progress import make_progress_sink


def main():
    candidates=['/System/Library/Fonts/STHeiti Medium.ttc',
                'C:/Windows/Fonts/msyh.ttc','/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    font_path=next((p for p in candidates if Path(p).is_file()),None)
    if not font_path:raise RuntimeError('Native OCR smoke test needs a Chinese font')
    image=Image.new('RGB',(1280,720),'#172832')
    draw=ImageDraw.Draw(image);font=ImageFont.truetype(font_path,24)
    draw.text((1020,130),'师门任务(3/10)',font=font,fill='white')
    draw.text((1020,170),'上交烹饪',font=font,fill='white')
    events=[]
    with tempfile.TemporaryDirectory() as directory:
        Toolkit.init_option(directory)
        resource=Resource();resource.use_cpu()
        for path in Catalog().resource_paths('官服'):
            assert resource.post_bundle(path).wait().succeeded
        assert resource.override_pipeline({'__ProgressTick':{
            'recognition':'DirectHit','action':'DoNothing','next':[], 'on_error':[], 'post_delay':0}})
        controller=SyntheticController()
        controller.screencap=lambda: np.asarray(image)[:,:,::-1].copy()
        assert controller.post_connection().wait().succeeded
        assert controller.post_screencap().wait().succeeded
        tasker=Tasker();assert tasker.bind(resource,controller)
        sink=make_progress_sink(lambda kind,**data:events.append((kind,data)))
        sink.begin('师门任务');tasker.add_context_sink(sink)
        assert tasker.post_task('__ProgressTick').wait().succeeded
        actual=[data for kind,data in events if data.get('sub_total')]
        assert actual, repr(events)
        assert actual[-1]['sub_current']==3 and actual[-1]['sub_total']==10,actual
        print('Native context callback + read-only task-panel OCR: PASS',actual[-1]['task_detail'])


if __name__=='__main__':main()
