"""One shared ADB capture loop per watched instance, serving bounded MJPEG frames."""
from __future__ import annotations
from io import BytesIO
import os
import subprocess
import threading
import time
from datetime import datetime,timezone

from PIL import Image,ImageDraw


LIVE_INTERVAL=float(os.environ.get('MHXY_STREAM_INTERVAL','0.2'))


def decode_capture(data):
    # 原始 screencap（未压缩 RGBA）比 PNG 快约 3 倍，PNG 仍然兼容。
    if data[:8]==b'\x89PNG\r\n\x1a\n':
        with Image.open(BytesIO(data)) as image:
            return image.convert('RGB')
    if len(data)<12:raise ValueError('画面数据不完整')
    width=int.from_bytes(data[0:4],'little');height=int.from_bytes(data[4:8],'little')
    if width<=0 or height<=0 or width*height*4+12>len(data):raise ValueError('画面数据无效')
    return Image.frombytes('RGBA',(width,height),data[12:12+width*height*4]).convert('RGB')


def jpeg_frame(data):
    image=decode_capture(data)
    image.thumbnail((960,960))
    out=BytesIO();image.save(out,'JPEG',quality=65,optimize=False)
    return out.getvalue()


def placeholder():
    image=Image.new('RGB',(960,540),'#152b33');draw=ImageDraw.Draw(image)
    draw.text((32,245),'Waiting for device...',fill='#94b8ab')
    out=BytesIO();image.save(out,'JPEG',quality=60);return out.getvalue()


class Channel:
    def __init__(self):
        self.condition=threading.Condition();self.clients=0;self.closed=False
        self.sequence=0;self.frame=None;self.status='connecting';self.timestamp=''

    def next_frame(self,after,timeout=2):
        with self.condition:
            self.condition.wait_for(lambda:self.sequence>after or self.closed,timeout)
            if self.sequence<=after:return None
            return self.sequence,self.frame,self.status,self.timestamp


class FrameHub:
    def __init__(self,get_device):
        self.get_device=get_device;self.lock=threading.Lock();self.channels={};self.closed=False
        self.offline=placeholder()

    def subscribe(self,key):
        with self.lock:
            if self.closed:raise ValueError('服务正在关闭')
            channel=self.channels.get(key)
            if channel is not None:
                with channel.condition:
                    if not channel.closed:
                        channel.clients+=1
                        return channel
            channel=Channel();self.channels[key]=channel
            channel.clients=1
            threading.Thread(target=self._capture,args=(key,channel),daemon=True).start()
            return channel

    def unsubscribe(self,channel):
        with channel.condition:
            channel.clients=max(0,channel.clients-1);channel.condition.notify_all()

    def _capture(self,key,channel):
        while True:
            with channel.condition:
                if self.closed or not channel.clients:
                    channel.closed=True;channel.condition.notify_all();return
            started=time.monotonic()
            try:
                d=self.get_device(key)
                result=subprocess.run([d['adb_path'],'-s',d['address'],'exec-out','screencap'],
                                      capture_output=True,timeout=8,check=True)
                frame=jpeg_frame(result.stdout);status='live'
            except Exception:
                frame=self.offline;status='offline'
            with channel.condition:
                channel.frame=frame;channel.status=status;channel.sequence+=1
                channel.timestamp=datetime.now(timezone.utc).isoformat()
                channel.condition.notify_all()
                delay=max(0,(LIVE_INTERVAL if status=='live' else 2)-(time.monotonic()-started))
                # Unsubscribe/shutdown wakes this wait immediately.
                channel.condition.wait_for(lambda:self.closed or not channel.clients,delay)

    def close(self):
        with self.lock:
            self.closed=True
            for channel in self.channels.values():
                with channel.condition:channel.closed=True;channel.condition.notify_all()


def multipart_frame(sequence,frame,status,timestamp):
    headers=(f'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n'
             f'X-Frame-Sequence: {sequence}\r\nX-Frame-Status: {status}\r\nX-Frame-Time: {timestamp}\r\n\r\n')
    return headers.encode('ascii')+frame+b'\r\n'
