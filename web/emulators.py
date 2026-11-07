"""Provider identity, including the original Mac MuMu device format."""
import sys


def spec(device):
    return device.get('emulator') or device.get('mumu')


def identity(device):
    value = spec(device)
    return (value.get('kind', 'mumu'), value['app_path'], value['index']) if value else None


def create(value):
    if value.get('kind', 'mumu') == 'mumu':
        from .mumu import MuMu
        return MuMu(value['app_path'])
    if value['kind'] == 'ldplayer':
        from .windows_emulators import LDPlayer
        return LDPlayer(value['app_path'])
    raise ValueError('不支持的模拟器类型')


def providers():
    return {'platform': sys.platform, 'providers': [
        {'kind': 'mumu', 'name': 'MuMu', 'supported': sys.platform in ('darwin', 'win32')},
        {'kind': 'ldplayer', 'name': '雷电', 'supported': sys.platform == 'win32'}]}
