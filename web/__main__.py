from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets

from .catalog import ROOT


def main():
    parser = argparse.ArgumentParser(description='MAA MHXY 同机多模拟器 Web 中控')
    parser.add_argument('--host', default='0.0.0.0', help='默认允许局域网访问；设为 127.0.0.1 可仅允许本机')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--data-dir', type=Path, default=ROOT / '.web-data')
    parser.add_argument('--require-token', action='store_true', help='可选：开启访问令牌验证')
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    token = os.environ.get('MHXY_WEB_TOKEN') if args.require_token else None
    if args.require_token and not token:
        token_file = data_dir / 'access-token'
        if not token_file.exists():
            with token_file.open('x', encoding='utf-8') as stream:
                stream.write(secrets.token_urlsafe(32))
            token_file.chmod(0o600)
        token = token_file.read_text(encoding='utf-8').strip()
    if token and len(token) < 16:
        parser.error('访问令牌至少需要 16 个字符')
    from .app import create_app
    import uvicorn

    print(f'\n本机访问：http://127.0.0.1:{args.port}\n监听地址：{args.host}:{args.port}', flush=True)
    print(f'访问令牌：{token}\n' if token else '访问方式：免令牌\n', flush=True)
    uvicorn.run(create_app(data_dir, token), host=args.host, port=args.port, log_level='info')


if __name__ == '__main__':
    main()
