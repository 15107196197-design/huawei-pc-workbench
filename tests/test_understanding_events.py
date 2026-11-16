"""Submitted-event understanding regressions; synthetic models, no network."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from huawei_agent import providers, store, workflow
from huawei_agent.task_context import P1, apply_brief_save, apply_message, apply_model_understanding


class UnderstandingEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for module, field, value in (
            (store, 'DATA', Path(tmp.name)),
            (workflow, 'load_settings', lambda: {'deepseek_api_key': 'synthetic-not-a-key'}),
            (providers.httpx, 'AsyncClient', AssertionError('本测试禁止外部HTTP调用')),
        ):
            if field == 'AsyncClient':
                mock = patch.object(module, field, side_effect=value)
            else:
                mock = patch.object(module, field, value)
            mock.start(); self.addCleanup(mock.stop)
        self.addCleanup(workflow.LOCKS.clear)

    def message(self, task, text):
        task['messages'].append({'role': 'user', 'content': text})
        return apply_message(task, text, workflow.parse_brief_rules(text, task['brief']))

    def test_reference_is_neither_selection_nor_exclusion(self):
        task = store.create_task()
        self.message(task, '只是引用 MateBook X Pro 2026 的名字，不要选定它。')
        pi = task['task_context']['product_intent']
        self.assertEqual(pi['selected'], [])
        self.assertEqual(pi['exclude'], [])
        self.assertEqual(pi['references'], ['MateBook X Pro 2026'])
        self.assertEqual(task['brief']['product'], '')

    def test_reference_preserves_previously_selected_product(self):
        task = store.create_task()
        self.message(task, '指定 MateBook 14 2025。')
        self.message(task, '文中只是引用 MateBook X Pro 2026 的名字，不要选定它。')
        self.assertEqual(task['task_context']['product_intent']['selected'], ['MateBook 14 2025'])
        self.assertEqual(task['brief']['product'], 'MateBook 14 2025')

    def test_model_reference_can_correct_same_event_rule_selection(self):
        task = store.create_task()
        event = self.message(task, '文中将出现 MateBook X Pro 2026 的名字。')
        self.assertEqual(task['task_context']['product_intent']['selected'], ['MateBook X Pro 2026'])
        apply_model_understanding(task, {
            'product_intent': {'mode': 'reference', 'products': ['MateBook X Pro 2026'],
                               'evidence_quote': '文中将出现 MateBook X Pro 2026 的名字'},
        }, event)
        self.assertEqual(task['task_context']['product_intent']['selected'], [])
        self.assertEqual(task['brief']['product'], '')

    def test_explicit_withdrawal_retires_modeling_and_records_source(self):
        task = store.create_task()
        self.message(task, '可能需要建模，也写文档。')
        old = next(c for c in task['task_context']['conditions'] if c['field'] == 'use_tasks' and c['value'] == '建模')
        event = self.message(task, '不需要建模，只写文档。')
        self.assertNotIn('建模', [c['value'] for c in task['task_context']['conditions'] if c['field'] == 'use_tasks'])
        retired = next(c for c in task['task_context']['retired_conditions'] if c['id'] == old['id'])
        self.assertEqual(retired['retired_by'], event['id'])

    def test_model_remove_accepts_plain_negative_without_requiring_technical_wording(self):
        task = store.create_task()
        self.message(task, '可能要建模。')
        old = next(c for c in task['task_context']['conditions'] if c['value'] == '建模')
        event = self.message(task, '不建模，只写文档。')
        apply_model_understanding(task, {
            'intent': 'correct',
            'task_context': [{'operation': 'remove', 'target_id': old['id'], 'field': 'use_tasks', 'value': '建模',
                              'state': 'stated', 'evidence_quote': '不建模'}],
        }, event)
        self.assertFalse(any(c['value'] == '建模' for c in task['task_context']['conditions']))

    def test_unanchored_model_remove_cannot_delete_user_task(self):
        task = store.create_task()
        event = self.message(task, '必须建模，也写文档。')
        old = next(c for c in task['task_context']['conditions'] if c['value'] == '建模')
        apply_model_understanding(task, {'intent': 'correct', 'task_context': [
            {'operation': 'remove', 'target_id': old['id'], 'field': 'use_tasks', 'value': '建模',
             'state': 'stated', 'evidence_quote': '不需要建模'}]}, event)
        self.assertTrue(any(c['id'] == old['id'] for c in task['task_context']['conditions']))

    def test_model_cannot_override_explicit_manual_field_by_attaching_unrelated_valid_quote(self):
        task = store.create_task()
        self.message(task, '给学生写条朋友圈。')
        old = deepcopy(task['brief'])
        task['brief']['audience'] = '企业采购负责人'
        apply_brief_save(task, old)
        event = task['requirement_events'][-1]
        apply_model_understanding(task, {'task_context': [
            {'field': 'audience', 'value': '学生', 'state': 'stated', 'evidence_quote': '企业采购负责人'}]}, event)
        self.assertEqual([c['value'] for c in task['task_context']['conditions'] if c['field'] == 'audience'], ['企业采购负责人'])

    def synthetic_retrieve(self, captured):
        async def retrieve(task, query='', refresh=False):
            captured.append(deepcopy(task['task_context']))
            model = 'MateBook 14 2025 Windows版'
            task['facts'] = [{'id': 'f1', 'product_id': 'p1', 'product_ref': 'p1', 'model': model,
                              'category': '屏幕', 'claim': '屏幕为14英寸', 'excerpt': '屏幕为14英寸',
                              'document_id': 'doc1', 'verified': True}]
            task['assets'] = [{'id': 'asset1', 'product_id': 'p1', 'model': model, 'name': 'synthetic.png',
                               'caption': '产品图', 'verified': True}]
            task['evidence_refs'] = [{'id': 'ev1', 'fact_id': 'f1', 'product_ref': 'p1',
                                      'document_ref': 'doc1', 'excerpt': '屏幕为14英寸'}]
            task['candidates'] = [{'product_ref': 'p1', 'model': model, 'status': 'conditional'}]
            task['selling_point_plan'] = {'selling_points': [{'product_ref': 'p1', 'fact_ids': ['f1']}],
                                          'context_version': task['task_context']['version'], 'evidence_version': 'synthetic-evidence'}
            task['matching_key'] = task['task_context']['matching_key']
            return task
        return retrieve

    def synthetic_model(self, understood):
        async def model(prompt, payload, **kwargs):
            if prompt == P1:
                understood.append(deepcopy(payload))
                # The old message says students; this quote is absent from the
                # newer save event and must not overwrite the manual correction.
                return {'task_context': [{'field': 'audience', 'value': '学生', 'state': 'stated', 'evidence_quote': '学生'}],
                        'next_action': 'retrieve'}
            if prompt.startswith('你是证据审校员'):
                return {'passed': True, 'issues': [], 'notes': []}
            return {'title': '产品比较方向', 'lead': '先看目标读者的实际任务', 'body': '屏幕为14英寸。广告，AI辅助内容。',
                    'cta': '了解具体配置', 'tags': [], 'images': [{'id': 'asset1', 'caption': '产品图', 'position': '正文后'}], 'fact_ids': ['f1']}
        return model

    async def test_manual_save_then_generate_uses_p1_once_and_old_chat_cannot_override(self):
        task = store.create_task()
        self.message(task, '给学生写条朋友圈。')
        old = deepcopy(task['brief'])
        task['brief']['audience'] = '企业采购负责人'
        apply_brief_save(task, old)
        task = store.save_task(task)
        event = task['requirement_events'][-1]
        understood, retrieved = [], []
        with patch.object(workflow, 'json_chat', new_callable=AsyncMock, side_effect=self.synthetic_model(understood)), \
             patch.object(workflow, 'retrieve_task', side_effect=self.synthetic_retrieve(retrieved)):
            task = await workflow.generate_task(task)
            task = await workflow.generate_task(task)
        self.assertEqual(len(understood), 1)
        self.assertEqual(understood[0]['submitted_event']['kind'], 'brief_save')
        self.assertEqual(understood[0]['submitted_event']['id'], event['id'])
        self.assertIn('学生', str(understood[0]['history']))
        self.assertEqual(task['brief']['audience'], '企业采购负责人')
        audience = [c for c in task['task_context']['conditions'] if c['field'] == 'audience']
        self.assertEqual([c['value'] for c in audience], ['企业采购负责人'])
        self.assertEqual(audience[0]['source_ids'], [event['id']])
        self.assertTrue(task['draft'])

    async def test_chat_and_saved_brief_use_the_same_understanding_schema(self):
        task = store.create_task()
        understood, retrieved = [], []
        with patch.object(workflow, 'json_chat', new_callable=AsyncMock, side_effect=self.synthetic_model(understood)), \
             patch.object(workflow, 'retrieve_task', side_effect=self.synthetic_retrieve(retrieved)):
            result = await workflow.chat_task(task, '给企业采购负责人写条朋友圈。')
        self.assertEqual(len(understood), 1)
        self.assertEqual(understood[0]['submitted_event']['kind'], 'message')
        self.assertIn('product_intent', understood[0]['schema']['properties'])
        self.assertIn('operation', understood[0]['schema']['$defs']['ConditionUpdate']['properties'])
        self.assertTrue(result['draft'])


if __name__ == '__main__':
    unittest.main()
