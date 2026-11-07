"""Native regression: successful task-panel OCR must not turn a failed team-window match into success."""
from pathlib import Path
import tempfile
import threading
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit
from tests.smoke_native import SyntheticController
from web.catalog import Catalog
from web.progress import make_progress_sink
from web.teamup import TeamMailbox
from web.teamup_ui import GameTeamUI


def main():
    candidates=['/System/Library/Fonts/STHeiti Medium.ttc','C:/Windows/Fonts/msyh.ttc',
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    font=ImageFont.truetype(next(path for path in candidates if Path(path).is_file()),24)
    image=Image.new('RGB',(1280,720),'#172832')
    ImageDraw.Draw(image).text((1020,130),'师门任务(3/10)',font=font,fill='white')
    events=[]
    with tempfile.TemporaryDirectory() as directory:
        Toolkit.init_option(directory)
        resource=Resource();resource.use_cpu()
        for path in Catalog().resource_paths('官服'):assert resource.post_bundle(path).wait().succeeded
        controller=SyntheticController();controller.screencap=lambda:np.asarray(image)[:,:,::-1].copy()
        assert controller.post_connection().wait().succeeded
        tasker=Tasker();assert tasker.bind(resource,controller)
        sink=make_progress_sink(lambda kind,**data:events.append(data));sink.begin('师门任务');tasker.add_context_sink(sink)
        ui=GameTeamUI(tasker,controller,TeamMailbox(threading.Event(),lambda *a,**k:None))
        assert not ui.team_visible(),'Task-panel OCR leaked into team-window detection'
        assert any(event.get('sub_total')==10 for event in events),events
    print('PASS: real native team-window miss stays false despite a successful nested progress OCR')

if __name__=='__main__':main()
