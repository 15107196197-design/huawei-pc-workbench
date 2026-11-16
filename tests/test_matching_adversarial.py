"""Adversarial business invariants; all products/evidence/models are synthetic."""
import unittest
import asyncio
from unittest.mock import AsyncMock, patch

from huawei_agent import workflow
from huawei_agent.task_context import apply_message, apply_model_understanding, ensure_context
from huawei_agent.matching import MatchResponse, assess, default_plan, validate_plan


def fixture(field='system', value='Windows', strength='hard', *, fact_text='屏幕为14英寸', category='屏幕'):
    task = {'id': 'adversarial', 'brief': {'audience': '工科新生', 'scenario': 'school', 'goal': '比较选型',
            'budget': '', 'software': '', 'product': '', 'platform': 'moments'}, 'messages': [],
            'facts': [{'id': 'screen', 'product_ref': 'product-one', 'product_id': 'product-one',
                       'model': 'MateBook A 2026 Windows版', 'category': category, 'excerpt': fact_text,
                       'claim': fact_text, 'verified': True}],
            'product_catalog': [{'product_ref': 'product-one', 'model': 'MateBook A 2026 Windows版', 'documents': []}],
            'assets': [], 'evidence': [], 'evidence_refs': []}
    context = ensure_context(task)
    context['conditions'] = [{'id': 'req-one', 'field': field, 'value': value, 'state': 'stated',
                              'source_ids': ['submitted-one'], 'reason': '合成明确要求', 'strength': strength}]
    return task


def proposal(status='satisfied', *, contrary=False):
    return MatchResponse.model_validate({'candidates': [{'product_ref': 'product-one', 'fit_assessments': [
        {'requirement_id': 'req-one', 'status': status, 'contrary_fact_ids' if contrary else 'fact_ids': ['screen'],
         'explanation': '合成模型提议，后端仍须核对依据'}]}]})


class MatchingAdversarial(unittest.TestCase):
    def test_screen_fact_cannot_satisfy_system_requirement(self):
        task = fixture()
        assess(task, proposal())
        self.assertEqual(task['fit_assessments'][0]['status'], 'unknown')
        self.assertEqual(task['candidates'][0]['status'], 'conditional')

    def test_screen_fact_cannot_prove_hard_minimum_memory(self):
        task = fixture('environment', '内存至少32GB')
        assess(task, proposal())
        self.assertEqual(task['fit_assessments'][0]['status'], 'unknown')

    def test_screen_fact_cannot_establish_system_conflict_and_exclude_product(self):
        task = fixture()
        assess(task, proposal('conflict', contrary=True))
        self.assertEqual(task['fit_assessments'][0]['status'], 'unknown')
        self.assertNotEqual(task['candidates'][0]['status'], 'excluded')

    def test_negative_compatibility_original_cannot_satisfy_software_requirement(self):
        task = fixture('software', 'AutoCAD', fact_text='当前系统不支持AutoCAD。', category='软件限制')
        assess(task, proposal())
        self.assertNotEqual(task['fit_assessments'][0]['status'], 'satisfied')
        self.assertNotEqual(task['candidates'][0]['status'], 'recommendable')

    def test_model_cannot_make_actual_soft_task_not_applicable_without_evidence(self):
        task = fixture('use_tasks', '建模', 'soft')
        assess(task, proposal('not_applicable'))
        self.assertEqual(task['fit_assessments'][0]['status'], 'unknown')
        self.assertEqual(task['candidates'][0]['status'], 'conditional')

    def test_missing_selected_product_does_not_fall_back_to_comparison_product(self):
        task = fixture()
        task['task_context']['product_intent'].update(mode='compare', selected=['MateBook Unknown 2099'],
                                                     compare=['MateBook A 2026 Windows版'])
        assess(task)
        plan = default_plan(task)
        self.assertEqual(plan['selling_points'], [])
        self.assertEqual(plan['next_action'], 'stop')

    def test_true_quote_does_not_make_unrelated_model_assumption_stated_and_hard(self):
        task = fixture()
        event = apply_message(task, '只使用网页版AI，给工科新生写朋友圈。', workflow.parse_brief_rules('只使用网页版AI，给工科新生写朋友圈。', task['brief']))
        apply_model_understanding(task, {'task_context': [{'field': 'system', 'value': '必须Windows',
            'state': 'stated', 'strength': 'hard', 'evidence_quote': '只使用网页版AI，给工科新生写朋友圈。'}]}, event)
        systems = [x for x in task['task_context']['conditions'] if x['field'] == 'system']
        self.assertFalse(any(x['value'] == '必须Windows' and x['state'] == 'stated' and x['strength'] == 'hard' for x in systems))
        self.assertTrue(any(x['value'] == 'Windows' and x['state'] == 'stated' and x['strength'] == 'hard' for x in systems))

    def test_model_targeted_task_replacement_preserves_unrelated_valid_tasks(self):
        task = fixture('use_tasks', '文档学习', 'soft')
        task['task_context']['conditions'].append({'id': 'modeling', 'field': 'use_tasks', 'value': '建模',
            'state': 'inferred', 'strength': 'soft', 'source_ids': ['old'], 'reason': '旧推断'})
        event = apply_message(task, '建模改为编程。', workflow.parse_brief_rules('建模改为编程。', task['brief']))
        apply_model_understanding(task, {'task_context': [{'operation': 'replace', 'target_id': 'modeling',
            'field': 'use_tasks', 'value': '编程', 'state': 'stated', 'evidence_quote': '建模改为编程。'}]}, event)
        self.assertIn('文档学习', [x['value'] for x in task['task_context']['conditions']])
        self.assertNotIn('建模', [x['value'] for x in task['task_context']['conditions']])

    def test_numeric_model_suffix_preserved_in_selected_intent(self):
        task = fixture()
        text = '指定MateBook 14s 2025，写朋友圈。'
        apply_message(task, text, workflow.parse_brief_rules(text, task['brief']))
        self.assertEqual(task['task_context']['product_intent']['selected'], ['MateBook 14s 2025'])

    def test_explicit_stop_decision_does_not_enter_writing_or_retrieval(self):
        task = fixture()
        task['title'] = '已有任务'
        retrieval = AsyncMock(return_value=task)
        model = AsyncMock(return_value={'intent': 'stop', 'next_action': 'stop', 'decision_reason': '用户明确暂不生成'})
        with patch.object(workflow, 'load_settings', return_value={'deepseek_api_key': 'synthetic'}), \
             patch.object(workflow, 'json_chat', model), \
             patch.object(workflow, 'save_task', side_effect=lambda value, *args, **kwargs: value), \
             patch.object(workflow, 'retrieve_task', retrieval):
            result = asyncio.run(workflow.chat_task(task, '先停下，不要生成。'))
        retrieval.assert_not_awaited()
        self.assertEqual(model.await_count, 1)  # Only interpretation, never the writing model.
        self.assertIsNone(result.get('draft'))

    def test_model_understood_budget_correction_updates_legacy_generator_brief(self):
        task = fixture('budget', '8000', 'hard')
        task['brief']['budget'] = '8000'
        text = '预算改成5000。'
        event = apply_message(task, text, workflow.parse_brief_rules(text, task['brief']))
        apply_model_understanding(task, {'task_context': [{'operation': 'replace', 'field': 'budget',
            'value': '5000', 'state': 'stated', 'evidence_quote': '预算改成5000。'}]}, event)
        self.assertEqual(next(x['value'] for x in task['task_context']['conditions'] if x['field'] == 'budget'), '5000')
        self.assertEqual(task['brief']['budget'], '5000')

    def test_selling_plan_cannot_turn_screen_fact_into_modeling_performance_permission(self):
        task = fixture('use_tasks', '建模', 'soft')
        assess(task)
        plan = validate_plan(task, {'selling_points': [{'task_ids': ['req-one'], 'product_ref': 'product-one',
            'fact_ids': ['screen'], 'value_explanation': '适合复杂建模', 'allowed_expression': '可流畅运行AutoCAD和专业渲染'}]})
        self.assertNotIn('可流畅运行AutoCAD和专业渲染', str(plan))


if __name__ == '__main__':
    unittest.main()
