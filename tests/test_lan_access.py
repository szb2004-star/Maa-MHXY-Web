from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from web.app import create_app
from web.catalog import Catalog, TASK_GROUPS


class LANAccessTests(unittest.TestCase):
    def test_no_token_opens_api_and_keeps_same_origin_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory))) as client:
                self.assertFalse(client.get('/health').json()['auth_required'])
                self.assertEqual(client.get('/api/devices').status_code,200)
                self.assertEqual(client.get('/api/profiles').status_code,200)
                response=client.post('/api/profiles',json={'name':'局域网配置','tasks':[{'name':'师门任务'}]})
                self.assertEqual(response.status_code,200)
                self.assertEqual(client.get('/api/devices',headers={'Origin':'http://other.example'}).status_code,403)

    def test_task_categories_partition_every_task_without_changing_saved_names(self):
        catalog=Catalog();public=catalog.public()
        self.assertEqual(public['categories'],['个人日常','组队日常','周常','日常功能','养成服务'])
        grouped=[name for names in TASK_GROUPS.values() for name in names]
        self.assertEqual(len(grouped),len(set(grouped)))
        self.assertEqual(set(grouped),set(catalog.tasks))
        self.assertEqual({task['name'] for task in public['tasks']},set(catalog.tasks))
        self.assertTrue(all(task['category'] in public['categories'] for task in public['tasks']))

    def test_optional_token_mode_still_requires_explicit_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            with TestClient(create_app(Path(directory),'test-only-access-token')) as client:
                self.assertTrue(client.get('/health').json()['auth_required'])
                self.assertEqual(client.get('/api/profiles').status_code,401)
                self.assertEqual(client.get('/api/profiles',headers={'Authorization':'Bearer test-only-access-token'}).status_code,200)


if __name__=='__main__':unittest.main()
