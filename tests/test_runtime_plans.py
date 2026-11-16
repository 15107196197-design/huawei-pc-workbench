"""Bounded P2/P3/P4 execution; all models, documents and clocks are synthetic."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from huawei_agent import matching, providers, store, workflow
from huawei_agent.task_context import apply_message


MODEL = 'MateBook 14 2025 Windows版'


def packet(suffix='1', *, reads=1, model=MODEL, product='p1', category='屏幕', excerpt='屏幕为14英寸'):
    return {
        'catalog': [{'product_ref': product, 'model': model, 'documents': [
            {'document_ref': 'doc'+suffix, 'title': '产品事实.md', 'kind': 'product_fact'}]}],
        'facts': [{'id': 'f'+suffix, 'product_ref': product, 'product_id': product, 'model': model,
                   'category': category, 'excerpt': excerpt, 'claim': excerpt, 'verified': True,
                   'document_id': 'doc'+suffix, 'source_url': 'https://example.invalid/facts'}],
        'assets': [{'id': 'asset-'+product, 'product_id': product, 'model': model, 'name': 'synthetic.png',
                    'caption': '产品图', 'verified': True}],
        'evidence': [], 'evidence_refs': [{'id': 'ev'+suffix, 'fact_id': 'f'+suffix, 'product_ref': product,
                                         'document_ref': 'doc'+suffix, 'excerpt': excerpt}],
        'gaps': [], 'warnings': [], 'budget': {'reads': reads},
    }


def plan(fact='f1', *, excerpt='屏幕为14英寸'):
    return {'next_action': 'generate', 'selling_points': [
        {'task_ids': [], 'product_ref': 'p1', 'fact_ids': [fact], 'value_explanation': '供对照学习时的查看需求',
         'allowed_expression': excerpt, 'required_qualifiers': [], 'prohibited_extensions': []}]}


def draft(fact='f2'):
    return {'title': '对照实际任务了解电脑', 'lead': '先比较有原文依据的规格', 'body': '屏幕为14英寸。广告，AI辅助内容。',
            'cta': '了解具体配置', 'tags': [], 'images': [{'id': 'asset-p1', 'caption': '产品图', 'position': '正文后'}],
            'fact_ids': [fact]}


class RuntimePlanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        for module, field, value in ((store, 'DATA', Path(tmp.name)),
                                     (workflow, 'load_settings', lambda: {'deepseek_api_key': 'synthetic-not-a-key'})):
            p = patch.object(module, field, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(providers.httpx, 'AsyncClient', side_effect=AssertionError('本测试禁止外部HTTP调用'))
        p.start(); self.addCleanup(p.stop)
        self.addCleanup(workflow.LOCKS.clear)

    def task(self, message='给学生写条朋友圈，主要处理文档。'):
        task = store.create_task()
        self.message(task, message)
        return task

    def message(self, task, text):
        task['messages'].append({'role': 'user', 'content': text})
        event = apply_message(task, text, workflow.parse_brief_rules(text, task['brief']))
        # These tests exercise the plan executor, independent of P1 behavior.
        task.setdefault('understood_events', []).append(event['id'])
        return event

    def service(self, initial=None, extra=None):
        return SimpleNamespace(discover=AsyncMock(return_value=deepcopy(initial or packet())),
                               read_documents=AsyncMock(return_value=deepcopy(extra or packet('2'))))

    async def test_P2_soft_unknown_can_continue_without_turning_into_a_questionnaire(self):
        task = self.task('给工科新生写朋友圈，可能建模，也想用AI。')
        service = self.service()
        chat = AsyncMock(side_effect=[{'next_action': 'ask', 'clarification': '主要是课程练习还是专业建模项目？'}, plan()])
        result = await matching.prepare_matching(task, service, chat)
        self.assertFalse('pending_clarification' in result, '软需求可继续，不应追问')
        self.assertTrue(result['selling_point_plan']['selling_points'])
        self.assertTrue(all(c['status'] == 'conditional' for c in result['candidates']))

    async def test_P2_hard_unknown_asks_one_meaningful_question_after_retrieval(self):
        task = self.task('给学生写朋友圈，必须运行AutoCAD。')
        service = self.service()
        chat = AsyncMock(return_value={'next_action': 'ask', 'clarification': '课程必须使用桌面程序，还是可以用网页版完成？'})
        result = await matching.prepare_matching(task, service, chat)
        service.discover.assert_awaited_once()
        self.assertEqual(chat.await_count, 1)  # P3 must wait for this consequential answer.
        question = result['pending_clarification']['question']
        with patch.object(workflow, 'knowledge', service), patch.object(workflow, 'json_chat', chat):
            result = await workflow.generate_task(result)
        self.assertEqual(result['status'], 'needs_input')
        self.assertEqual([m['content'] for m in result['messages'] if m['role'] == 'assistant'], [question])
        self.assertIsNone(result['draft'])

    async def test_P2_key_version_difference_may_ask_without_a_blanket_SKU_requirement(self):
        task = self.task('指定MateBook 14，给学生写朋友圈，重点介绍系统。')
        initial = packet('windows', model='MateBook 14 2025 Windows版', product='windows', category='系统', excerpt='操作系统为Windows 11')
        other = packet('harmony', model='MateBook 14 2025 鸿蒙版', product='harmony', category='系统', excerpt='操作系统为HarmonyOS')
        for key in ('catalog', 'facts', 'assets', 'evidence_refs'):
            initial[key].extend(other[key])
        for product in initial['catalog']:
            product['selected_match'] = True
        service = self.service(initial)
        chat = AsyncMock(return_value={'next_action': 'ask', 'clarification': '这次需要比较两个系统，还是只介绍其中一个系统？'})
        result = await matching.prepare_matching(task, service, chat)
        self.assertIn('pending_clarification', result)
        self.assertEqual(chat.await_count, 1)
        self.assertEqual(result['task_context']['product_intent']['selected'], ['MateBook 14'])

    async def test_P2_multiple_versions_do_not_require_SKU_when_current_content_uses_common_facts(self):
        task = self.task('指定MateBook 14，给学生写朋友圈，只介绍各版本共通的屏幕尺寸。')
        initial = packet('windows', model='MateBook 14 2025 Windows版', product='windows')
        other = packet('harmony', model='MateBook 14 2025 鸿蒙版', product='harmony')
        for key in ('catalog', 'facts', 'assets', 'evidence_refs'):
            initial[key].extend(other[key])
        for product in initial['catalog']:
            product['selected_match'] = True
        service = self.service(initial)
        chat = AsyncMock(side_effect=[{'next_action': 'ask', 'clarification': '先确定具体系统和年份，才能继续吗？'}, {'selling_points': []}])
        result = await matching.prepare_matching(task, service, chat)
        self.assertFalse('pending_clarification' in result, '只写共通事实时不需要确定全部版本')
        self.assertTrue(result['selling_point_plan']['selling_points'])

    async def test_P2_user_does_not_know_software_or_budget_is_not_asked_again(self):
        task = self.task('给学生写朋友圈，必须运行课程软件。')
        self.message(task, '预算和软件名称我都不知道。')
        service = self.service()
        chat = AsyncMock(side_effect=[{'next_action': 'ask', 'clarification': '具体软件名称是什么，预算多少钱？'}, plan()])
        result = await matching.prepare_matching(task, service, chat)
        self.assertFalse('pending_clarification' in result, '已回答不知道，不应再索要软件或预算')
        self.assertTrue(result['selling_point_plan']['selling_points'])

    async def test_P2_unknown_software_does_not_allow_same_question_rephrased_as_program(self):
        task = self.task('给学生写朋友圈，必须运行课程软件。')
        self.message(task, '我不知道软件名称。')
        service = self.service()
        chat = AsyncMock(side_effect=[{'next_action': 'ask', 'clarification': '课程用的是什么程序？'}, plan()])
        result = await matching.prepare_matching(task, service, chat)
        self.assertFalse('pending_clarification' in result, '换用程序一词仍属于重复索要软件信息')
        self.assertTrue(result['selling_point_plan']['selling_points'])

    async def test_P3_read_is_a_real_bounded_document_read_and_enters_the_next_plan(self):
        task = self.task()
        service = self.service(packet(reads=24), packet('2', reads=8, category='重量', excerpt='机身重量约1.3kg'))
        chat = AsyncMock(side_effect=[{'next_action': 'finish'},
                                     {'next_action': 'read', 'document_refs': ['doc2'], 'remaining_gaps': ['携带规格原文']},
                                     plan('f2', excerpt='机身重量约1.3kg')])
        result = await matching.prepare_matching(task, service, chat)
        service.read_documents.assert_awaited_once()
        self.assertEqual(service.read_documents.await_args.args[0], ['doc2'])
        self.assertEqual(service.read_documents.await_args.kwargs['max_reads'], 8)
        self.assertEqual(result['selling_point_plan']['selling_points'][0]['fact_ids'], ['f2'])
        self.assertIn('f2', str(chat.await_args_list[2].args[1]['facts']))
        self.assertLessEqual(result['query_control']['actions'], 3)
        self.assertEqual(sum(r['reads'] for r in result['retrieval_runs']), 32)

    async def test_P2_and_P3_share_three_actions_and_32_document_reads(self):
        task = self.task()
        service = self.service(packet(reads=16))
        service.read_documents.side_effect = [packet('2', reads=8), packet('3', reads=8)]
        chat = AsyncMock(side_effect=[{'next_action': 'read', 'document_refs': ['doc2']}, {'next_action': 'finish'},
                                     {'next_action': 'read', 'document_refs': ['doc3']}, plan('f3')])
        result = await matching.prepare_matching(task, service, chat)
        self.assertEqual(result['query_control']['actions'], 3)
        self.assertEqual(sum(r['reads'] for r in result['retrieval_runs']), 32)
        calls_before = service.read_documents.await_count
        self.assertFalse(await matching.supplement_evidence(result, service, document_refs=['doc4']))
        self.assertEqual(service.read_documents.await_count, calls_before)
        self.assertTrue(any(g['kind'] == 'query_limit' for g in result['evidence_gaps']))

    async def test_P3_read_cannot_exceed_remaining_document_quota(self):
        task = self.task()
        service = self.service(packet(reads=30), packet('2', reads=2))
        chat = AsyncMock(side_effect=[{'next_action': 'finish'}, {'next_action': 'read', 'document_refs': ['doc2']}, plan('f2')])
        result = await matching.prepare_matching(task, service, chat)
        self.assertEqual(service.read_documents.await_args.kwargs['max_reads'], 2)
        self.assertEqual(matching.query_remaining(result), 0)

    async def test_elapsed_120_seconds_stops_supplement_before_any_service_call(self):
        task = self.task()
        task['query_control'] = {'actions': 1, 'max_actions': 3, 'started_at': 100, 'max_seconds': 120, 'queries': []}
        service = self.service()
        with patch.object(matching.time, 'time', return_value=220):
            changed = await matching.supplement_evidence(task, service, document_refs=['doc2'])
        self.assertFalse(changed)
        service.read_documents.assert_not_awaited()
        self.assertEqual(task['query_control']['actions'], 1)

    async def test_last_second_of_query_budget_bounds_the_actual_backend_timeout(self):
        task = self.task()
        task['query_control'] = {'actions': 1, 'max_actions': 3, 'started_at': 100, 'max_seconds': 120, 'queries': []}
        service = self.service()
        waits = []
        async def record_wait(awaitable, timeout):
            waits.append(timeout)
            return await awaitable
        with patch.object(matching.time, 'time', return_value=219), patch.object(matching.asyncio, 'wait_for', side_effect=record_wait):
            await matching.supplement_evidence(task, service, document_refs=['doc2'])
        self.assertLessEqual(waits[0], 1)
        self.assertLessEqual(service.read_documents.await_args.kwargs['timeout_seconds'], 1)

    async def test_P3_planning_wait_is_bounded_by_the_same_120_second_decision_window(self):
        task = self.task()
        clock = {'seconds': 0}
        waits = []
        async def discover(*args, **kwargs):
            clock['seconds'] = 50  # Within the original 55-second service timeout.
            return packet()
        async def chat(prompt, payload):
            if prompt == matching.P2:
                clock['seconds'] = 95  # P2 used its allowed 45 seconds.
                return {'next_action': 'finish'}
            return {'next_action': 'stop', 'remaining_gaps': ['无额外结论']}
        async def record_wait(awaitable, timeout):
            waits.append((clock['seconds'], timeout))
            return await awaitable
        service = self.service(); service.discover.side_effect = discover
        fake_time = SimpleNamespace(time=lambda: clock['seconds'], monotonic=lambda: clock['seconds'])
        with patch.object(matching, 'time', fake_time), patch.object(matching.asyncio, 'wait_for', side_effect=record_wait):
            await matching.prepare_matching(task, service, chat)
        self.assertEqual(waits[-1][0], 95)
        self.assertLessEqual(waits[-1][1], 25)

    async def test_P3_stop_is_not_replaced_with_a_default_selling_plan(self):
        task = self.task()
        service = self.service()
        chat = AsyncMock(side_effect=[{'next_action': 'finish'}, {'next_action': 'stop', 'remaining_gaps': ['没有证据支持这一卖点']}])
        result = await matching.prepare_matching(task, service, chat)
        self.assertEqual(result['selling_point_plan']['next_action'], 'stop')
        self.assertEqual(result['selling_point_plan']['selling_points'], [])
        self.assertIn('没有证据支持这一卖点', result['selling_point_plan']['remaining_gaps'])

    async def test_P3_stop_remains_stopped_when_same_requirements_reuse_evidence(self):
        task = self.task()
        service = self.service()
        chat = AsyncMock(side_effect=[{'next_action': 'finish'}, {'next_action': 'stop', 'remaining_gaps': ['核心结论没有原文']}])
        result = await matching.prepare_matching(task, service, chat)
        result = await matching.prepare_matching(result, service, chat)
        self.assertEqual(result['selling_point_plan']['next_action'], 'stop')
        self.assertEqual(result['selling_point_plan']['selling_points'], [])
        self.assertEqual(chat.await_count, 2)

    def prepared_writing_task(self, *, actions=1, message=None):
        task = self.task(message) if message else self.task()
        matching.merge_results(task, packet(category='重量', excerpt='机身重量约1.3kg'))
        matching.assess(task)
        task['selling_point_plan'] = matching.default_plan(task)
        task['query_control'] = {'actions': actions, 'max_actions': 3, 'started_at': matching.time.time(), 'max_seconds': 120, 'queries': []}
        return store.save_task(task)

    async def test_P4_missing_evidence_with_quota_supplements_then_rewrites_once(self):
        task = self.prepared_writing_task()
        service = self.service(packet('2'))
        model = AsyncMock(side_effect=[{'missing_evidence': ['屏幕尺寸原文']}, draft(), {'passed': True, 'issues': [], 'notes': []}])
        with patch.object(workflow, 'knowledge', service), patch.object(workflow, 'json_chat', model), \
             patch.object(workflow, 'supplement_evidence', wraps=matching.supplement_evidence) as supplement:
            result = await workflow.generate_task(task)
        supplement.assert_awaited_once()
        service.discover.assert_awaited_once()
        self.assertEqual(service.discover.await_args.kwargs['queries'], ['屏幕尺寸原文'])
        self.assertEqual(model.await_count, 3)  # P4, P4 retry, fresh P5.
        self.assertIn('f2', [f['id'] for f in model.await_args_list[1].args[1]['facts']])
        self.assertEqual(result['draft']['fact_ids'], ['f2'])
        self.assertEqual(result['status'], 'draft')

    async def test_P4_exhausted_quota_keeps_specific_gap_without_network_or_retry(self):
        task = self.prepared_writing_task(actions=3, message='给学生写条朋友圈，必须运行AutoCAD。')
        service = self.service()
        model = AsyncMock(return_value={'missing_evidence': ['AutoCAD兼容原文']})
        with patch.object(workflow, 'knowledge', service), patch.object(workflow, 'json_chat', model):
            result = await workflow.generate_task(task)
        self.assertEqual(model.await_count, 1)
        service.discover.assert_not_awaited()
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertIsNone(result['draft'])
        self.assertIn('AutoCAD兼容原文', result['messages'][-1]['content'])
        self.assertTrue(any(g['kind'] == 'query_limit' for g in result['evidence_gaps']))

    async def test_unknown_soft_modeling_and_programming_do_not_block_verified_screen_comparison(self):
        task = self.task('给工科新生写条朋友圈，可能建模，也可能编程，暂不确定具体软件。')
        matching.merge_results(task, packet())
        matching.assess(task)
        task['selling_point_plan'] = matching.default_plan(task)
        task['query_control'] = {'actions': 3, 'max_actions': 3, 'started_at': matching.time.time(), 'max_seconds': 120, 'queries': []}
        task = store.save_task(task)
        self.assertFalse(task['task_context']['hard_constraints'])
        service = self.service()
        model = AsyncMock(side_effect=[{'missing_evidence': ['具体编程软件与建模工作负载尚无适配或实测依据']},
                                       draft('f1'), {'passed': True, 'issues': [], 'notes': []}])
        with patch.object(workflow, 'knowledge', service), patch.object(workflow, 'json_chat', model):
            result = await workflow.generate_task(task)
        service.discover.assert_not_awaited()
        self.assertEqual(model.await_count, 3)  # At most two writing attempts, then fresh review.
        scope = model.await_args_list[1].args[1]['instruction']
        self.assertIn('规格', scope)
        self.assertTrue(any(word in scope for word in ('删除', '收窄', '缩小')))
        self.assertIn('14英寸', result['draft']['body'])
        self.assertEqual(result['draft']['fact_ids'], ['f1'])
        self.assertEqual(result['status'], 'draft')
        self.assertTrue(all(c['status'] == 'conditional' for c in result['candidates']))
        self.assertNotIn('流畅建模', result['draft']['body'])

    async def test_complete_supported_draft_is_reviewed_when_missing_list_only_describes_unwritten_angles(self):
        task = self.task('给工科新生写条朋友圈，可能建模，也可能编程。')
        matching.merge_results(task, packet()); matching.assess(task)
        task['selling_point_plan'] = matching.default_plan(task)
        task = store.save_task(task)
        complete = draft('f1')
        complete['body'] = '屏幕为14英寸，可作为课程资料阅读时的比较信息。具体SKU与系统请确认。广告，AI辅助内容。'
        complete['missing_evidence'] = ['未取得课程软件和建模工作负载实测，本稿未作相关承诺']
        service = self.service()
        model = AsyncMock(side_effect=[deepcopy(complete), {'passed': True, 'issues': [], 'notes': []}])
        with patch.object(workflow, 'knowledge', service), patch.object(workflow, 'json_chat', model), \
             patch.object(workflow, 'supplement_evidence', wraps=matching.supplement_evidence) as supplement:
            result = await workflow.generate_task(task)
        self.assertEqual(model.await_count, 2)  # Complete writing plus an independent P5 review.
        supplement.assert_not_awaited()
        service.discover.assert_not_awaited()
        self.assertEqual(result['writing_reported_gaps'], complete['missing_evidence'])
        self.assertEqual(result['draft']['body'], complete['body'])
        self.assertEqual(result['status'], 'draft')
        self.assertTrue(any(c['kind'] == 'specification' and c['status'] == 'supported' and 'f1' in c['fact_ids']
                            for c in result['claim_support']))

    async def test_complete_draft_missing_list_cannot_excuse_an_actual_unsupported_modeling_promise(self):
        task = self.task('给工科新生写条朋友圈，可能建模，也可能编程。')
        matching.merge_results(task, packet()); matching.assess(task)
        task['selling_point_plan'] = matching.default_plan(task)
        task = store.save_task(task)
        complete = draft('f1')
        complete['body'] = '屏幕为14英寸。它能流畅建模。广告，AI辅助内容。'
        complete['missing_evidence'] = ['建模性能实测尚未取得']
        service = self.service()
        # Even a mistaken semantic pass cannot waive the independent evidence
        # check. The unchanged repair proves the existing retry stays bounded.
        semantic_pass = {'passed': True, 'issues': [], 'notes': []}
        model = AsyncMock(side_effect=[deepcopy(complete), deepcopy(semantic_pass),
                                       deepcopy(complete), deepcopy(semantic_pass)])
        with patch.object(workflow, 'knowledge', service), patch.object(workflow, 'json_chat', model), \
             patch.object(workflow, 'supplement_evidence', wraps=matching.supplement_evidence) as supplement:
            result = await workflow.generate_task(task)
        self.assertEqual(model.await_count, 4)
        supplement.assert_not_awaited()
        service.discover.assert_not_awaited()
        self.assertEqual(result['repair_record']['attempts'], 1)
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(any(c['category'] == '推荐与卖点依据' and c['status'] == 'blocked' and '流畅建模' in c['message']
                            for c in result['checks']))
        self.assertTrue(any(c['kind'] == 'capability' and c['status'] == 'unsupported' and '流畅建模' in c['quote']
                            for c in result['claim_support']))

    async def test_P4_remaining_missing_evidence_does_not_repeat_successful_query_forever(self):
        task = self.prepared_writing_task()
        service = self.service(packet('2'))
        model = AsyncMock(return_value={'missing_evidence': ['课程软件实测仍缺失']})
        with patch.object(workflow, 'knowledge', service), patch.object(workflow, 'json_chat', model), \
             patch.object(workflow, 'supplement_evidence', wraps=matching.supplement_evidence) as supplement:
            result = await workflow.generate_task(task)
        self.assertEqual(model.await_count, 2)
        supplement.assert_awaited_once()
        service.discover.assert_awaited_once()
        self.assertEqual(result['status'], 'needs_evidence')
        self.assertIsNone(result['draft'])

    async def test_extra_response_type_gets_one_schema_repair_without_new_facts_or_queries(self):
        task = self.task()
        service = self.service()
        invalid = {'type': 'json_object', 'next_action': 'finish'}
        chat = AsyncMock(side_effect=[deepcopy(invalid), {'next_action': 'finish'}, plan()])
        result = await matching.prepare_matching(task, service, chat)
        self.assertEqual(chat.await_count, 3)  # P2 invalid, P2 correction, P3.
        repair = chat.await_args_list[1].args[1]
        original = chat.await_args_list[0].args[1]
        self.assertEqual(repair['previous_invalid_output'], invalid)
        self.assertTrue(any(error['location'] == ['type'] for error in repair['schema_errors']))
        self.assertEqual(repair['facts'], original['facts'])
        self.assertEqual(repair['evidence_refs'], original['evidence_refs'])
        self.assertEqual(len(result['schema_repairs']), 1)
        self.assertEqual(result['schema_repairs'][0]['stage'], '候选匹配')
        self.assertEqual(result['query_control']['actions'], 1)
        service.discover.assert_awaited_once()
        service.read_documents.assert_not_awaited()
        self.assertEqual(result['selling_point_plan']['selling_points'][0]['fact_ids'], ['f1'])

    async def test_two_invalid_P2_responses_stop_and_workflow_persists_acquired_originals(self):
        task = self.task()
        service = self.service()
        invalid = {'type': 'json_object', 'next_action': 'finish'}
        model = AsyncMock(side_effect=[deepcopy(invalid), deepcopy(invalid)])
        with patch.object(workflow, 'knowledge', service), patch.object(workflow, 'json_chat', model):
            result = await workflow.generate_task(task)
        self.assertEqual(model.await_count, 2)
        service.discover.assert_awaited_once()
        service.read_documents.assert_not_awaited()
        self.assertEqual(result['status'], 'error')
        self.assertIsNone(result['draft'])
        self.assertEqual([f['id'] for f in result['facts']], ['f1'])
        self.assertEqual([r['id'] for r in result['evidence_refs']], ['ev1'])
        self.assertEqual([repair['attempt'] for repair in result['schema_repairs']], [1, 2])
        self.assertIn('Schema', result['error'])
        reopened = store.get_task(result['id'])
        self.assertEqual(reopened['facts'], result['facts'])
        self.assertEqual(reopened['schema_repairs'], result['schema_repairs'])
        self.assertNotIn('请明确型号', result['messages'][-1]['content'])

    async def test_schema_retry_shares_remaining_deadline_and_cannot_restart_its_timeout(self):
        for corrected_at in (115, 120):
            with self.subTest(first_response_at=corrected_at):
                task = self.task()
                clock = {'seconds': 95}
                waits = []
                responses = 0
                async def chat(prompt, payload):
                    nonlocal responses
                    responses += 1
                    if responses == 1:
                        clock['seconds'] = corrected_at
                        return {'type': 'json_object', 'next_action': 'finish'}
                    return {'next_action': 'finish'}
                async def record_wait(awaitable, timeout):
                    waits.append(timeout)
                    return await awaitable
                fake_time = SimpleNamespace(time=lambda: clock['seconds'])
                with patch.object(matching, 'time', fake_time), patch.object(matching.asyncio, 'wait_for', side_effect=record_wait):
                    if corrected_at == 120:
                        with self.assertRaises(TimeoutError):
                            await matching.structured_chat(chat, matching.P2, {}, matching.MatchResponse, task,
                                                           '候选匹配', deadline_at=120)
                    else:
                        result = await matching.structured_chat(chat, matching.P2, {}, matching.MatchResponse, task,
                                                                '候选匹配', deadline_at=120)
                        self.assertEqual(result.next_action, 'finish')
                self.assertEqual(waits, [25, 5] if corrected_at == 115 else [25])
                self.assertEqual(responses, 2 if corrected_at == 115 else 1)
                self.assertEqual(len(task['schema_repairs']), 1)


if __name__ == '__main__':
    unittest.main()
