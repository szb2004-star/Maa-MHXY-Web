"""Exercise the actual bounded login with native OCR, template matching and synthetic input."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from tests.smoke_native import SyntheticController
from web.catalog import Catalog,ROOT
from web.game_login import login


def main():
    button=Image.new('RGB',(1280,720),'#172832')
    ImageDraw.Draw(button).text((520,500),'登录游戏',fill='white',
        font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',32))
    scene=Image.new('RGB',(1280,720),'#172832')
    template=Image.open(ROOT/'assets/resource/base/image/zonghe/baoguo.png').convert('RGB')
    scene.paste(template,(1200,600))
    cases=[(button,None)]
    friends=Image.new('RGB',(1280,720),'#172832')
    friends.paste(Image.open(ROOT/'assets/resource/base/image/r5/haoyou_zhujiemian.png').convert('RGB'),(400,20))
    cases.append((friends,(1143,47)))
    team=Image.new('RGB',(1280,720),'#172832')
    team.paste(Image.open(ROOT/'assets/resource/base/image/duiwu/duiwu-zudui.png').convert('RGB'),(20,10))
    cases.append((team,(1204,34)))
    # An overlay can leave the main HUD visible: it must still be dismissed first.
    welfare = scene.copy()
    draw = ImageDraw.Draw(welfare)
    draw.text((600,40),'福利',fill='white',font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',32))
    cases.append((welfare,(1154,58)))
    monthly = scene.copy()
    draw = ImageDraw.Draw(monthly)
    draw.text((450,80),'月卡每日返利',fill='white',font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',32))
    draw.text((450,660),'点击空白处领取本日奖励',fill='white',font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',26))
    cases.append((monthly,None))
    for initial,expected in cases:
        controller=SyntheticController();controller.get_features=lambda:0;clicks=[]
        controller.screencap=lambda:np.asarray(scene if clicks else initial)[:,:,::-1].copy()
        def click(x,y):clicks.append((x,y));return True
        controller.click=click
        with tempfile.TemporaryDirectory() as directory,patch('maa.controller.AdbController',return_value=controller):
            login({'directory':directory,'device':{'adb_path':'synthetic','address':'synthetic'},
                   'resources':[str(p) for p in Catalog().resource_paths('官服')],'timeout':15})
        assert len(clicks)==1,clicks
        if expected:assert clicks[0]==expected,clicks
        elif initial is button:assert 510<clicks[0][0]<680 and 495<clicks[0][1]<545,clicks
        else:assert 450<clicks[0][0]<850 and 650<clicks[0][1]<700,clicks
    print('PASS: login OCR, known-window recovery, and overlay priority and three consecutive game-scene confirmations')

if __name__=='__main__':main()
