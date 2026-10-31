import io
import json
import unittest
from unittest.mock import patch

from sitestarter.credentials import Secret
from sitestarter.live_model import LiveModelError, make_live_model
from sitestarter.live_run import DEFAULT_MODEL, make_live_runner
from sitestarter.run_store import RunStore
from test_run_store import FORM
from sitestarter.coordinator import prepare_brief
from sitestarter.recorded_run import DESIGN


class LiveIntegrationTests(unittest.TestCase):
    def test_keychain_loader_injected_without_environment_export(self):
        requests = []
        def opener(request, timeout):
            requests.append(request)
            body = json.loads(request.data)
            self.assertEqual(body['model'], DEFAULT_MODEL)
            self.assertEqual(body['max_tokens'], 4096)
            return io.BytesIO(json.dumps({'stop_reason':'end_turn','content':[{'type':'text','text':'ok'}]}).encode())
        with patch.dict('os.environ', {}, clear=True):
            call = make_live_model(DEFAULT_MODEL, opener, credential_loader=lambda: Secret('FAKE-ONLY'), max_tokens=4096)
            self.assertEqual(call([{'role':'user','content':'hello'}]), 'ok')
        self.assertEqual(requests[0].get_header('X-api-key'), 'FAKE-ONLY')
        self.assertNotIn('FAKE-ONLY', requests[0].data.decode())

    def test_truncated_provider_response_is_rejected(self):
        def opener(*args, **kwargs):
            return io.BytesIO(json.dumps({'stop_reason':'max_tokens','content':[{'type':'text','text':'{}'}]}).encode())
        call = make_live_model('mock-model', opener, credential_loader=lambda: Secret('FAKE'))
        with self.assertRaises(LiveModelError):
            call([])

    def test_keychain_failure_is_sanitized(self):
        def denied(): raise RuntimeError('PRIVATE-SECRET')
        call = make_live_model('mock-model', credential_loader=denied)
        with self.assertRaises(LiveModelError) as error:
            call([])
        self.assertNotIn('PRIVATE', str(error.exception))

    def test_constructing_live_runner_does_not_load_key(self):
        with patch('sitestarter.live_run.load_anthropic_key') as loader:
            make_live_runner()
            loader.assert_not_called()

    def test_keychain_read_once_for_all_tasks_and_retry_steps(self):
        brief = prepare_brief(FORM)['brief']
        def fake_model(messages):
            return '{}'
        def fake_loop(brief, content, design):
            task = {'kind':'plan','brief':brief,'request_id':brief['request_id']}
            for callback in (content, design, content, design):
                callback(task)
            return {'status':'failed'}
        with patch('sitestarter.live_run.load_anthropic_key', return_value=Secret('FAKE')) as loader, \
             patch('sitestarter.live_run.make_live_model', return_value=fake_model) as factory, \
             patch('sitestarter.live_run.run_planning_loop', side_effect=fake_loop):
            runner = make_live_runner()
            loader.assert_not_called()
            runner(brief, lambda _: None)
            loader.assert_called_once_with()
            self.assertEqual(factory.call_args.kwargs['credential_loader']().reveal(), 'FAKE')

    def test_denied_keychain_access_is_not_retried_by_planning_loop(self):
        with patch('sitestarter.live_run.load_anthropic_key', side_effect=RuntimeError('denied')) as loader, \
             patch('sitestarter.live_run.run_planning_loop') as loop:
            with self.assertRaises(RuntimeError):
                make_live_runner()(prepare_brief(FORM)['brief'], lambda _:None)
            loader.assert_called_once_with()
            loop.assert_not_called()

    def test_full_live_callback_wiring_uses_harness_and_real_builder(self):
        tasks = []
        def mocked_model(messages):
            task = json.loads(messages[1]['content'].split('\n',1)[1]); tasks.append(task)
            content = 'Content Agent' in messages[0]['content']
            if task['kind'] == 'plan':
                if content:
                    value = {'request_id':task['request_id'],'agent_name':'content_agent','status':'complete',
                             'heading':'Example studio','about_text':task['brief']['about'],'contact':task['brief']['contact'],
                             'missing_information':[],'warnings':[]}
                else: value = dict(DESIGN, request_id=task['request_id'])
            else:
                value = {'request_id':task['request_id'],'agent_name':'content_agent' if content else 'design_agent',
                         'round':task['round'],'verdict':'agree','requests':[]}
            return json.dumps(value)
        brief=prepare_brief(FORM)['brief']; store=RunStore();sid,rid=store.start(brief,mode='live')
        store.execute(sid,rid,make_live_runner(call_model=mocked_model))
        self.assertEqual(store.snapshot(sid,rid)['status'],'ready')
        self.assertIn(FORM['about'],store.output(sid,rid))
        self.assertEqual(len(tasks),4)
        self.assertEqual([t['kind'] for t in tasks],['plan','plan','review','review'])

    def test_store_deadline_discards_late_success(self):
        now=[0];store=RunStore(clock=lambda:now[0]);brief=prepare_brief(FORM)['brief'];sid,rid=store.start(brief)
        def late(*args):
            now[0]=241
            return {'status':'ready','html':'late page','calls':[]}
        store.execute(sid,rid,late)
        self.assertEqual(store.snapshot(sid,rid)['status'],'timed_out')
        with self.assertRaises(PermissionError):store.output(sid,rid)
