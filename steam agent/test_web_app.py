"""Flask 离线测试：不调用真实 Agent/API。"""
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch
from web_app import app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        patcher = patch('web_app.run_agent', return_value='中文 Game 1\n第二行')
        self.agent = patcher.start()
        self.addCleanup(patcher.stop)

    def test_home(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Steam 榜单分析 Agent', response.get_data(as_text=True))
        self.agent.assert_not_called()

    def test_success(self):
        response = self.client.post('/api/chat', json={'message': ' Top 5 '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'ok': True, 'answer': '中文 Game 1\n第二行'})
        self.agent.assert_called_once_with('Top 5')

    def test_empty(self):
        self.assertEqual(self.client.post('/api/chat', json={'message': ''}).status_code, 400)
        self.agent.assert_not_called()

    def test_whitespace(self):
        self.assertEqual(self.client.post('/api/chat', json={'message': ' \n '}).status_code, 400)
        self.agent.assert_not_called()

    def test_missing(self):
        self.assertEqual(self.client.post('/api/chat', json={}).status_code, 400)
        self.agent.assert_not_called()

    def test_wrong_type(self):
        for value in (1, True, None, [], {}):
            self.assertEqual(self.client.post('/api/chat', json={'message': value}).status_code, 400)
        self.agent.assert_not_called()

    def test_non_json(self):
        self.assertEqual(self.client.post('/api/chat', data='hello').status_code, 415)
        self.agent.assert_not_called()

    def test_malformed_json(self):
        self.assertEqual(self.client.post('/api/chat', data='{bad', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post('/api/chat', json=[]).status_code, 400)

    def test_error_is_safe(self):
        secret = 'test-only-secret'
        self.agent.side_effect = RuntimeError('WinError test ' + secret)
        with patch.dict(os.environ, {'SILICONFLOW_API_KEY': secret}), self.assertLogs(app.logger, level='ERROR') as logs:
            response = self.client.post('/api/chat', json={'message': 'test'})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json, {'ok': False, 'error': '本次分析失败，请稍后重试。'})
        self.assertNotIn(secret, str(logs.output))
        self.assertNotIn('WinError', response.get_data(as_text=True))

    def test_empty_agent_answer(self):
        self.agent.return_value = ''
        with self.assertLogs(app.logger, level='ERROR'):
            self.assertEqual(self.client.post('/api/chat', json={'message': 'test'}).status_code, 502)

    def test_payload_limit(self):
        response = self.client.post('/api/chat', json={'message': 'x' * 40000})
        self.assertEqual(response.status_code, 413)
        self.assertFalse(response.json['ok'])
        self.agent.assert_not_called()

    def test_static_assets(self):
        for path in ('/static/style.css', '/static/app.js'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_home_control_and_welcome_examples(self):
        from bs4 import BeautifulSoup
        page = BeautifulSoup(self.client.get('/').get_data(as_text=True), 'html.parser')
        home = page.select_one('button#home')
        self.assertIsNotNone(home)
        self.assertEqual(home.get('type'), 'button')
        self.assertEqual(home.get('aria-label'), '返回首页')
        self.assertEqual(home.get('title'), '返回首页')
        self.assertEqual(len(page.select('#welcome button[data-question]')), 4)
        self.assertIsNotNone(page.select_one('label[for="message"]'))

    def test_diagnostic_stages_and_status(self):
        with redirect_stdout(StringIO()) as output:
            self.client.post('/api/chat', json={'message': 'private question'})
        text = output.getvalue()
        stages = ['收到 /api/chat 请求', '请求校验完成', '正在调用 run_agent...',
                  'run_agent 调用成功', 'HTTP status: 200']
        self.assertEqual(sorted(text.index(stage) for stage in stages),
                         [text.index(stage) for stage in stages])
        self.assertNotIn('private question', text)
        with redirect_stdout(StringIO()) as output:
            self.client.post('/api/chat', json={'message': ''})
        self.assertIn('HTTP status: 400', output.getvalue())
        self.assertNotIn('正在调用 run_agent', output.getvalue())

    def test_safe_traceback_has_location_without_sensitive_details(self):
        def fail(message):
            raise RuntimeError('diagnostic failure Authorization: Bearer private-token payload private-body')
        self.agent.side_effect = fail
        with self.assertLogs(app.logger, level='ERROR') as logs, redirect_stdout(StringIO()) as output:
            response = self.client.post('/api/chat', json={'message': 'private question'})
        text = '\n'.join(logs.output)
        self.assertIn('RuntimeError: diagnostic failure', text)
        self.assertIn('Traceback', text)
        self.assertIn('web_app.py, line', text)
        self.assertIn('in fail', text)
        for secret in ('private-token', 'private-body', 'private question', 'Authorization:'):
            self.assertNotIn(secret, text)
        self.assertIn('HTTP status: 502', output.getvalue())
        self.assertNotIn('Traceback', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
