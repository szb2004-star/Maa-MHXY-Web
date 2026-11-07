"""Persist account snapshots and supervise exclusive, read-only game UI scans."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

from .account_data import SECTIONS
from .catalog import ROOT
from .manager import kill_tree, now


class Accounts:
    def __init__(self, manager):
        self.manager=manager
        self.directory=manager.data_dir/'accounts';self.directory.mkdir(exist_ok=True)
        self.records={};self.jobs={};self.processes={};self.closed=False
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='account-capture')
        for path in self.directory.glob('*.json'):
            try:
                record=json.loads(path.read_text(encoding='utf-8'))
                if isinstance(record,dict) and isinstance(record.get('sections'),dict):self.records[path.stem]=record
            except (OSError,ValueError):pass

    def list(self):
        with self.manager.lock:
            return [self.get(key) for key in self.manager.devices]

    def get(self,key):
        with self.manager.lock:
            device=self.manager.get(key)
            record=copy.deepcopy(self.records.get(key,{'sections':{},'updated_at':None}))
            return {'device_id':key,'device_name':device['name'],**record,
                    'capture':copy.deepcopy(self.jobs.get(key,{'status':'idle','active':False}))}

    def avatar_path(self,key):
        with self.manager.lock:
            self.manager.get(key)
            path=self.directory/(key+'-avatar.png')
            if not path.is_file():raise KeyError('该实例还没有采集到头像')
            return path

    def save(self,key):
        path=self.directory/(key+'.json');temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.records[key],ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)

    def section(self,key,event):
        section=event.get('section');status=event.get('status')
        if section not in SECTIONS or status not in ('ok','partial','unavailable','failed'):return
        data=event.get('data',{})
        if not isinstance(data,dict):return
        record=self.records.setdefault(key,{'sections':{},'updated_at':None})
        if section=='identity':
            old=record['sections'].get('identity',{}).get('data',{})
            if (data.get('role_id') and old.get('role_id') and data['role_id'] != old['role_id']
                    or data.get('role_name') and old.get('role_name') and data['role_name'] != old['role_name']):
                record['sections']={}
        previous=record['sections'].get(section)
        if status=='failed' and previous and previous.get('data'):
            previous.update(error=event.get('message','本次采集失败'),last_attempt_at=now())
        else:
            updated={'status':status,'data':data,'message':str(event.get('message',''))[:300],
                     'updated_at':now()}
            if previous and previous.get('data'):
                updated['previous']={'data':previous.get('data',{}),'updated_at':previous.get('updated_at')}
            record['sections'][section]=updated
        record['updated_at']=now();self.save(key)

    def capture(self,key):
        rows=self.manager.list_with_power()
        row=next((item for item in rows if item['id']==key),None)
        if row is None:raise KeyError('实例不存在')
        if (row.get('emulator') or row.get('mumu')) and not row['power']['on']:raise ValueError('该实例未开机，请先打开游戏窗口')
        if not (row.get('emulator') or row.get('mumu')):
            result=subprocess.run([row['adb_path'],'-s',row['address'],'get-state'],capture_output=True,timeout=5)
            if result.returncode or result.stdout.strip()!=b'device':raise ValueError('ADB 设备未在线')
        with self.manager.lock:
            if self.closed or self.manager.closed:raise ValueError('中控正在关闭')
            device=copy.deepcopy(self.manager.get(key))
            if self.manager.active(key) or key in self.manager.power_operations:
                raise ValueError('实例正在执行任务或开关机，请结束后再采集账号资料')
            if key in self.manager.capture_operations:raise ValueError('该实例正在采集账号资料')
            job={'id':uuid.uuid4().hex,'status':'queued','active':True,'phase':'等待采集当前游戏窗口',
                 'started_at':now(),'finished_at':None}
            self.jobs[key]=job;self.manager.capture_operations[key]=job
            self.executor.submit(self._capture,key,device,job)
            return self.get(key)

    def capture_running(self):
        rows=self.manager.list_with_power();result=[]
        for row in rows:
            if not row['power']['on']:continue
            try:result.append({'id':row['id'],'ok':True,'account':self.capture(row['id'])})
            except (ValueError,KeyError) as exc:result.append({'id':row['id'],'ok':False,'error':str(exc)})
        return result

    def _capture(self,key,device,job):
        timer=None;process=None;seen=set();finished=False
        try:
            with self.manager.lock:
                if self.closed:return
                job.update(status='running',phase='正在连接当前游戏窗口')
                directory=self.directory/key/job['id'];directory.mkdir(parents=True)
                process=subprocess.Popen([sys.executable,'-u','-m','web.account_worker'],cwd=ROOT,
                    env={**os.environ, 'PYTHONIOENCODING':'utf-8', 'PYTHONUNBUFFERED':'1'},
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                    encoding='utf-8',errors='replace',start_new_session=(sys.platform!='win32'))
                self.processes[key]=process
                process.stdin.write(json.dumps({'device':device,'directory':str(directory)},ensure_ascii=False)+'\n');process.stdin.flush()
            # Also bounds native SDK calls that do not provide a Python timeout.
            timer=threading.Timer(150,lambda:kill_tree(process) if process.poll() is None else None);timer.daemon=True;timer.start()
            with (directory/'capture.log').open('w',encoding='utf-8') as log:
                for line in process.stdout:
                    log.write(line);log.flush()
                    if not line.startswith('@@ACCOUNT@@'):continue
                    try:event=json.loads(line[11:])
                    except ValueError:continue
                    with self.manager.lock:
                        if event.get('kind')=='progress':job['phase']=str(event.get('message','正在采集'))[:200]
                        elif event.get('kind')=='section':
                            seen.add(event.get('section'));self.section(key,event)
                        elif event.get('kind')=='finished':
                            finished=True;job.update(status=event.get('status','partial'),phase=event.get('message','采集结束'))
            code=process.wait()
            if (directory/'avatar.png').is_file():
                with self.manager.lock:
                    record=self.records.setdefault(key,{'sections':{},'updated_at':None})
                    record['avatar_at']=now()
                    (self.directory/(key+'-avatar.png')).write_bytes((directory/'avatar.png').read_bytes())
                    self.save(key)
            with self.manager.lock:
                if not finished:
                    job.update(status='failed',phase='采集未完成，请检查游戏窗口、ADB 或采集日志')
                elif code:
                    job['status']='failed'
                elif seen != set(SECTIONS):
                    job.update(status='partial',phase='已保存读取到的数据，部分页面未能采集')
        except Exception as exc:
            with self.manager.lock:job.update(status='failed',phase=str(exc)[:250])
        finally:
            if timer:timer.cancel()
            if process:
                if process.poll() is None:kill_tree(process)
                process.stdout.close();process.stdin.close()
            with self.manager.lock:
                self.processes.pop(key,None);job.update(active=False,finished_at=now())
                self.manager.capture_operations.pop(key,None)

    def close(self):
        with self.manager.lock:
            self.closed=True;processes=list(self.processes.values())
        for process in processes:
            if process.poll() is None:kill_tree(process)
        self.executor.shutdown(wait=True,cancel_futures=True)
        with self.manager.lock:
            for job in self.jobs.values():
                if job['active']:job.update(active=False,status='failed',phase='中控关闭，采集中断',finished_at=now())
            self.manager.capture_operations.clear()
