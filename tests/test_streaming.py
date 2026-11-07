from io import BytesIO
import time
import unittest
from unittest.mock import patch
from PIL import Image
from web.streaming import FrameHub,jpeg_frame,multipart_frame

class StreamTests(unittest.TestCase):
    def test_shared_capture_and_last_viewer_cleanup(self):
        out=BytesIO();Image.new('RGB',(1920,1080),'green').save(out,'PNG')
        with patch('web.streaming.subprocess.run') as capture:
            capture.return_value.stdout=out.getvalue()
            hub=FrameHub(lambda key:{'adb_path':'adb','address':key})
            a=hub.subscribe('one');b=hub.subscribe('one')
            self.assertIs(a,b)
            seq,frame,status,stamp=a.next_frame(0)
            self.assertEqual(status,'live')
            self.assertEqual(Image.open(BytesIO(frame)).size,(960,540))
            packet=multipart_frame(seq,frame,status,stamp)
            self.assertIn(f'Content-Length: {len(frame)}'.encode(),packet)
            hub.unsubscribe(a);self.assertEqual(b.clients,1)
            hub.unsubscribe(b)
            deadline=time.monotonic()+2
            while not b.closed and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(b.closed)
            count=capture.call_count;time.sleep(.1);self.assertEqual(capture.call_count,count)
            c=hub.subscribe('one');self.assertIsNot(c,b);hub.unsubscribe(c);hub.close()

    def test_raw_screencap_decodes_and_downscales(self):
        width,height=1280,720
        raw=(width.to_bytes(4,'little')+height.to_bytes(4,'little')+(1).to_bytes(4,'little')
             +bytes([0,255,0,255])*(width*height))
        frame=jpeg_frame(raw)
        image=Image.open(BytesIO(frame))
        self.assertEqual(image.size,(960,540))
        red,green,blue=image.convert('RGB').getpixel((20,20))
        self.assertGreater(green,200);self.assertLess(red,20);self.assertLess(blue,20)

    def test_offline_device_produces_valid_placeholder(self):
        with patch('web.streaming.subprocess.run',side_effect=OSError('offline')):
            hub=FrameHub(lambda key:{'adb_path':'adb','address':key})
            channel=hub.subscribe('one');result=channel.next_frame(0)
            self.assertEqual(result[2],'offline')
            Image.open(BytesIO(result[1])).verify()
            hub.unsubscribe(channel);hub.close()

if __name__=='__main__':unittest.main()
