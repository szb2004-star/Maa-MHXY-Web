from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import ipaddress
import asyncio
import os
from pathlib import Path
import subprocess
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .catalog import Catalog, ROOT
from . import version as buildinfo
from .manager import Manager
from .mumu import MuMu
from .emulators import spec, identity, create as create_emulator, providers
from .streaming import FrameHub, multipart_frame
from .accounts import Accounts


class Device(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9_.:\[\]-]+$')
    adb_path: str = Field(min_length=1, max_length=1024)
    config: dict = Field(default_factory=dict)
    screencap_methods: int | None = None
    input_methods: int | None = None


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    resource: str = '官服'
    tasks: list[dict] = Field(max_length=100)


class TaskProfile(Profile):
    version: int | None = Field(default=None, ge=1)


class ProfileAssignment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str | None = None


class PowerRequest(BaseModel):
    on: bool


class DeviceSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    resource: str = '官服'


class Batch(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=64)
    action: str = Field(pattern='^(start|stop)$')


class MuMuDiscovery(BaseModel):
    app_path: str = Field(default='', max_length=1024)


class EmulatorDiscovery(MuMuDiscovery):
    kind: str = Field(default='mumu', pattern='^(mumu|ldplayer)$')


class EmulatorImport(EmulatorDiscovery):
    indexes: list[int] = Field(min_length=1, max_length=64)


class MuMuImport(MuMuDiscovery):
    indexes: list[int] = Field(min_length=1, max_length=64)


class TaskCategoryMove(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=50)
    before: str | None = Field(default=None, max_length=200)


class Discovery(BaseModel):
    adb_path: str = Field(default='', max_length=1024)


def local_network(host):
    """本机回环或私有网段才返回 True；公网地址一律视为外部。"""
    try:
        address = ipaddress.ip_address(str(host or '').split('%')[0])
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_private or address.is_link_local


def create_app(data_dir=None, token=None):
    directory = Path(data_dir or os.environ.get('MHXY_WEB_DATA', ROOT / '.web-data'))
    catalog = Catalog(layout_file=directory / 'task-layout.json')
    manager = Manager(directory, catalog)
    token = token or None
    accounts = Accounts(manager)

    def stream_device(key):
        with manager.lock:
            return dict(manager.get(key))
    streams = FrameHub(stream_device)

    @asynccontextmanager
    async def lifespan(app):
        yield
        streams.close()
        accounts.close()
        manager.close()

    app = FastAPI(title='MAA MHXY Web 中控', lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.manager = manager
    app.state.streams = streams
    app.state.accounts = accounts

    @app.middleware('http')
    async def access(request: Request, call_next):
        # Same-origin only: blocks browser CSRF and cross-origin token use.
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': '不允许跨域请求'}, status_code=403)
        if token and request.url.path.startswith('/api/'):
            auth = request.headers.get('authorization', '')
            if not hmac.compare_digest(auth.encode(), ('Bearer ' + token).encode()):
                return JSONResponse({'detail': '请填写正确的访问令牌'}, status_code=401)
        if request.headers.get('content-length', '0').isdigit() and int(request.headers.get('content-length', 0)) > 1024 * 1024:
            return JSONResponse({'detail': '请求过大'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; img-src 'self' blob: data:; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail': str(exc.args[0])}, status_code=404)

    @app.get('/health')
    def health(request: Request):
        return {'status': 'ok', 'auth_required': bool(token),
                'monitor': local_network(request.client.host if request.client else '')}

    @app.get('/api/version')
    def version_info():
        return buildinfo.current()

    @app.get('/api/version/check')
    def version_check():
        return buildinfo.check_updates()

    @app.post('/api/version/update')
    def version_update():
        return buildinfo.apply_update()

    @app.get('/api/activity')
    def activity(limit: Annotated[int, Query(ge=1, le=200)] = 80, device: str | None = None):
        return {'runs': manager.activity(limit, device)}

    @app.get('/api/accounts')
    def account_list():
        return {'accounts': accounts.list()}

    @app.post('/api/accounts/capture-running')
    def account_capture_running():
        return {'results': accounts.capture_running()}

    @app.get('/api/accounts/{key}')
    def account_detail(key: str):
        return accounts.get(key)

    @app.post('/api/accounts/{key}/capture')
    def account_capture(key: str):
        return accounts.capture(key)

    @app.get('/avatar/{key}.png')
    def account_avatar(key: str):
        return FileResponse(accounts.avatar_path(key), media_type='image/png')

    @app.get('/api/catalog')
    def get_catalog():
        return catalog.public()

    @app.put('/api/catalog/task-category')
    def move_task_category(body: TaskCategoryMove):
        return catalog.move_task(body.name, body.category, body.before)

    @app.get('/api/description')
    def description(name: str):
        return {'text': catalog.description(name)}

    @app.get('/api/devices')
    def devices():
        return manager.list_with_power()

    @app.get('/api/profiles')
    def profiles():
        return manager.list_profiles()

    @app.post('/api/profiles')
    def create_profile(body: TaskProfile):
        return manager.save_profile(None, body.model_dump(exclude={'version'}))

    @app.put('/api/profiles/{key}')
    def update_profile(key: str, body: TaskProfile):
        return manager.save_profile(key, body.model_dump(exclude={'version'}), body.version)

    @app.post('/api/profiles/{key}/duplicate')
    def duplicate_profile(key: str):
        return manager.duplicate_profile(key)

    @app.delete('/api/profiles/{key}')
    def delete_profile(key: str):
        manager.delete_profile(key)
        return {'ok': True}

    @app.put('/api/devices/{key}/profile')
    def assign_profile(key: str, body: ProfileAssignment):
        return manager.assign_profile(key, body.profile_id)

    @app.patch('/api/devices/{key}/settings')
    def update_settings(key: str, body: DeviceSettings):
        return manager.update_settings(key, body.model_dump())

    @app.post('/api/discover')
    def discover(body: Discovery):
        try:
            from maa.toolkit import Toolkit
            found = Toolkit.find_adb_devices(body.adb_path or None)
            return [{'name': d.name, 'adb_path': str(d.adb_path), 'address': d.address,
                     'config': d.config, 'screencap_methods': int(d.screencap_methods),
                     'input_methods': int(d.input_methods)} for d in found]
        except Exception as exc:
            raise HTTPException(503, f'设备扫描失败：{exc}') from None

    @app.get('/api/emulators')
    def emulator_providers():
        return providers()

    @app.post('/api/emulators/discover')
    def discover_emulators(body: EmulatorDiscovery):
        rows = create_emulator({'kind': body.kind, 'app_path': body.app_path}).discover()
        with manager.lock:
            added = {identity(d) for d in manager.devices.values() if spec(d)}
        return [{**row, 'added': identity(row) in added} for row in rows]

    @app.post('/api/emulators/import')
    def import_emulators(body: EmulatorImport):
        rows = create_emulator({'kind': body.kind, 'app_path': body.app_path}).discover()
        by_index = {spec(d)['index']: d for d in rows}
        indexes = list(dict.fromkeys(body.indexes))
        if any(i not in by_index for i in indexes):
            raise ValueError('选中的模拟器实例已不存在，请刷新列表')
        manager.ensure_capacity(len(indexes))
        return [manager.import_emulator(by_index[i]) for i in indexes]

    @app.post('/api/mumu/discover')
    def discover_mumu(body: MuMuDiscovery):
        instances = MuMu(body.app_path).discover()
        with manager.lock:
            added = {identity(d) for d in manager.devices.values() if spec(d)}
        return [{**row, 'added': identity(row) in added}
                for row in instances]

    @app.post('/api/mumu/import')
    def import_mumu(body: MuMuImport):
        instances = MuMu(body.app_path).discover()
        by_index = {spec(d)['index']: d for d in instances}
        indexes = list(dict.fromkeys(body.indexes))
        if any(i not in by_index for i in indexes):
            raise ValueError('选中的 MuMu 实例已不存在，请刷新实例列表')
        manager.ensure_capacity(len(indexes))
        return [manager.import_mumu(by_index[i]) for i in indexes]

    @app.get('/api/profiles/{key}/targets')
    def profile_send_targets(key: str):
        return manager.profile_send_targets(key)

    @app.put('/api/devices/{key}/receive-profile')
    def receive_profile(key: str, body: ProfileAssignment):
        return manager.receive_profile(key, body.profile_id)

    @app.post('/api/devices')
    def add(body: Device):
        return manager.add(body.model_dump())

    @app.put('/api/devices/{key}')
    def update(key: str, body: Profile):
        return manager.update(key, body.model_dump())

    @app.delete('/api/devices/{key}')
    def delete(key: str):
        manager.delete(key)
        return {'ok': True}

    @app.put('/api/devices/{key}/power')
    def power(key: str, body: PowerRequest):
        return manager.set_power(key, body.on)

    @app.post('/api/devices/{key}/start')
    def start(key: str):
        with manager.lock:
            if not manager.effective_device(manager.get(key))['tasks']:
                raise ValueError('请先为实例选择任务配置')
        return manager.start(key)

    @app.post('/api/devices/{key}/stop')
    def stop(key: str):
        return manager.stop(key)

    @app.post('/api/batch')
    def batch(body: Batch):
        result = []
        for key in dict.fromkeys(body.ids):
            try:
                if body.action == 'start':
                    with manager.lock:
                        if not manager.effective_device(manager.get(key))['tasks']:
                            raise ValueError('请先为实例选择任务配置')
                state = getattr(manager, body.action)(key)
                result.append({'id': key, 'ok': True, 'run': state})
            except (KeyError, ValueError) as exc:
                result.append({'id': key, 'ok': False, 'error': str(exc.args[0])})
        return result

    @app.get('/api/devices/{key}/logs')
    def logs(key: str, after: Annotated[int, Query(ge=0)] = 0):
        return manager.logs(key, after)

    @app.get('/api/devices/{key}/stream')
    def stream(key: str, request: Request):
        if not local_network(request.client.host if request.client else ''):
            raise HTTPException(403, '监控中心仅支持本机或局域网访问')
        stream_device(key)  # Validate before starting the response.
        channel = streams.subscribe(key)
        async def frames():
            sequence = 0
            try:
                while not await request.is_disconnected():
                    frame = await asyncio.to_thread(channel.next_frame, sequence)
                    if frame is None:
                        if channel.closed:break
                        continue
                    sequence, jpeg, status, timestamp = frame
                    yield multipart_frame(sequence, jpeg, status, timestamp)
            finally:
                streams.unsubscribe(channel)
        return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame',
                                 headers={'X-Accel-Buffering':'no'})

    @app.get('/api/devices/{key}/screenshot')
    def screenshot(key: str):
        with manager.lock:
            d = dict(manager.get(key))
        try:
            result = subprocess.run([d['adb_path'], '-s', d['address'], 'exec-out', 'screencap', '-p'],
                                    capture_output=True, timeout=15, check=True)
            if not result.stdout.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('设备未返回 PNG 截图')
            return Response(result.stdout, media_type='image/png')
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise HTTPException(503, f'截图失败：{exc}') from None

    @app.get('/')
    def index():
        # 每次都用资源文件的修改时间做版本号，避免浏览器拿到旧 HTML/JS 组合后界面卡住。
        static = Path(__file__).parent / 'static'
        html = (static / 'index.html').read_text(encoding='utf-8')
        for asset in ('app.js', 'style.css'):
            path = static / asset
            html = html.replace(f'/static/{asset}', f'/static/{asset}?v={int(path.stat().st_mtime)}')
        return HTMLResponse(html)

    app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')
    return app
