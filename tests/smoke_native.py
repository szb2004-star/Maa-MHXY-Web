"""Optional native integration: python -m tests.smoke_native (no emulator needed).
Uses real MaaFw 5.14.3, original resources and custom Agent, with synthetic 16:9 images.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np
from maa.agent_client import AgentClient
from maa.controller import CustomController
from maa.resource import Resource
from maa.tasker import Tasker
from maa.toolkit import Toolkit

from web.catalog import Catalog, ROOT


class SyntheticController(CustomController):
    def connect(self): return True
    def request_uuid(self): return 'web-native-smoke'
    def start_app(self, intent): return True
    def stop_app(self, intent): return True
    def screencap(self): return np.zeros((720,1280,3), dtype=np.uint8)
    def click(self, x, y): return True
    def swipe(self, x1,y1,x2,y2,duration): return True
    def touch_down(self, *args): return True
    def touch_move(self, *args): return True
    def touch_up(self, *args): return True
    def click_key(self, *args): return True
    def input_text(self, *args): return True
    def key_down(self, *args): return True
    def key_up(self, *args): return True
    def scroll(self, *args): return True
    def relative_move(self, *args): return True


def main():
    catalog = Catalog()
    with tempfile.TemporaryDirectory() as directory:
        Toolkit.init_option(directory)
        resource = Resource()
        resource.use_cpu()
        agent = AgentClient()
        agent.set_timeout(15000)
        assert agent.bind(resource)
        env = {**os.environ, 'MHXY_INSTANCE_DIR':directory}
        with open(Path(directory)/'agent.log','w+',encoding='utf-8') as logfile:
            child = subprocess.Popen([sys.executable,'-u','-m','web.agent',agent.identifier],cwd=ROOT,env=env,stdout=logfile,stderr=subprocess.STDOUT)
            try:
                assert agent.connect(), 'Agent connection failed'
                assert 'ExpressionRecognition' in agent.custom_recognition_list
                for name in catalog.resources:
                    for path in catalog.resource_paths(name):
                        assert resource.post_bundle(path).wait().succeeded, str(path)
                print(f'Resource load: {len(resource.node_list)} nodes; {len(catalog.resources)} resource variants')
                controller = SyntheticController()
                assert controller.post_connection().wait().succeeded
                tasker = Tasker()
                assert tasker.bind(resource, controller) and tasker.inited
                assert agent.register_sink(resource, controller, tasker)
                assert resource.override_pipeline({'WebNativeSmoke': {
                    'recognition':'Custom', 'custom_recognition':'ExpressionRecognition',
                    'custom_recognition_param':{'expression':'1 == 1'},
                    'action':'DoNothing', 'next':[], 'on_error':[], 'post_delay':0}})
                from web.progress import make_progress_sink
                progress_events=[]
                progress_sink=make_progress_sink(lambda kind,**data:progress_events.append(data))
                progress_sink.begin('师门任务');tasker.add_context_sink(progress_sink)
                job = tasker.post_task('WebNativeSmoke').wait()
                assert job.succeeded, 'Custom recognition task failed'
                assert any(event.get('phase') for event in progress_events), 'Progress context sink did not receive callbacks'
                print('Original Agent + aspect-ratio + progress context sink: PASS')
            except BaseException:
                logfile.flush(); logfile.seek(0); print(logfile.read())
                raise
            finally:
                agent.disconnect()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait()


if __name__ == '__main__':
    main()
