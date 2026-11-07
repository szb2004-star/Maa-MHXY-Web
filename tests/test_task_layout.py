import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from web.app import create_app
from web.catalog import Catalog, TASK_GROUPS


class TaskLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.file=self.root/'task-layout.json';self.catalog=Catalog(layout_file=self.file)

    def tearDown(self):
        self.temp.cleanup()

    def test_move_between_categories_persists_without_changing_task_plan(self):
        plan=self.catalog.compile([{'name':'宝图任务'}])
        original=set(self.catalog.tasks)
        self.catalog.move_task('宝图任务','组队日常',before='编组自动组队')
        reloaded=Catalog(layout_file=self.file);groups=reloaded.grouped_tasks()
        self.assertEqual(groups['组队日常'][0],'宝图任务')
        self.assertNotIn('宝图任务',groups['个人日常'])
        all_tasks=[t for names in groups.values() for t in names]
        self.assertEqual(set(all_tasks),original);self.assertEqual(len(all_tasks),len(original))
        self.assertEqual(reloaded.compile([{'name':'宝图任务'}]),plan)

    def test_same_category_reorder_and_invalid_drop_are_atomic(self):
        self.catalog.move_task('宝图任务','个人日常',before='师门任务')
        self.assertEqual(self.catalog.grouped_tasks()['个人日常'][:2],['宝图任务','师门任务'])
        saved=self.file.read_bytes()
        for args in [('宝图任务','不存在',None),('未知任务','个人日常',None),('宝图任务','个人日常','编组自动组队')]:
            with self.assertRaises(ValueError):self.catalog.move_task(*args)
            self.assertEqual(self.file.read_bytes(),saved)

    def test_empty_category_can_receive_a_task_again(self):
        for name in list(self.catalog.grouped_tasks()['周常']):self.catalog.move_task(name,'日常功能')
        self.assertEqual(self.catalog.grouped_tasks()['周常'],[])
        self.catalog.move_task('宝图任务','周常')
        self.assertEqual(Catalog(layout_file=self.file).grouped_tasks()['周常'],['宝图任务'])

    def test_saved_layout_ignores_removed_and_duplicate_entries(self):
        self.file.write_text(json.dumps({'个人日常':['宝图任务','未知任务','宝图任务'],'组队日常':['宝图任务']}))
        groups=Catalog(layout_file=self.file).grouped_tasks()
        names=[name for items in groups.values() for name in items]
        self.assertEqual(names.count('宝图任务'),1);self.assertNotIn('未知任务',names)
        self.assertEqual(set(names),set(self.catalog.tasks))
        self.assertEqual(list(groups),list(TASK_GROUPS))

    def test_category_api_auth_and_reloading_saved_layout(self):
        token='task-layout-test-access-token';headers={'Authorization':'Bearer '+token}
        with TestClient(create_app(self.root/'api',token)) as client:
            body={'name':'宝图任务','category':'组队日常','before':'编组自动组队'}
            self.assertEqual(client.put('/api/catalog/task-category',json=body).status_code,401)
            moved=client.put('/api/catalog/task-category',json=body,headers=headers)
            self.assertEqual(moved.status_code,200,moved.text)
            task=next(t for t in moved.json()['tasks'] if t['name']=='宝图任务')
            self.assertEqual((task['category'],task['category_order']),('组队日常',0))
            self.assertEqual(client.put('/api/catalog/task-category',json={**body,'category':'不存在'},headers=headers).status_code,400)
        with TestClient(create_app(self.root/'api',token)) as client:
            tasks=client.get('/api/catalog',headers=headers).json()['tasks']
            self.assertEqual(next(t for t in tasks if t['name']=='宝图任务')['category'],'组队日常')
