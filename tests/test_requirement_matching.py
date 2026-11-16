"""A-F/H-N: synthetic evidence and isolated storage; never calls live services."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from huawei_agent import store, workflow
from huawei_agent.task_context import ensure_context, apply_message, apply_brief_save, apply_model_understanding
from huawei_agent.matching import prepare_matching, assess, default_plan, validate_plan, MatchResponse


def results():
    return {'catalog':[{'product_ref':'p1','model':'MateBook 14 2025 Windows版','documents':[]}],
            'facts':[{'id':'f1','product_id':'p1','product_ref':'p1','model':'MateBook 14 2025 Windows版','category':'屏幕','excerpt':'屏幕为14英寸','claim':'屏幕为14英寸','verified':True,'document_id':'doc1','source_url':'https://example.invalid/fact'}],
            'assets':[{'id':'a1','product_id':'p1','model':'MateBook 14 2025 Windows版','name':'test.png','caption':'产品图','verified':True}],
            'evidence':[],'evidence_refs':[{'id':'ev1','fact_id':'f1','document_ref':'doc1','excerpt':'屏幕为14英寸','product_ref':'p1','model':'MateBook 14 2025 Windows版'}],
            'gaps':[], 'warnings':[]}

class Requirements(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(store,'DATA',Path(self.tmp.name));p.start();self.addCleanup(p.stop)
        p=patch.object(workflow,'load_settings',return_value={'deepseek_api_key':''});p.start();self.addCleanup(p.stop)
    def message(self,t,text):
        e=apply_message(t,text,workflow.parse_brief_rules(text,t['brief']))
        return e
    async def test_A_partial_natural_brief_queries_and_generates_useful_direction(self):
        t=store.create_task()
        with patch.object(workflow.knowledge,'discover',new_callable=AsyncMock,return_value=results()) as discover:
            t=await workflow.chat_task(t,'给工科新生写条朋友圈，推荐适合学习的华为电脑。')
        discover.assert_awaited_once()
        self.assertTrue(t['draft']);self.assertEqual(t['brief']['platform'],'moments')
        self.assertFalse(t['brief']['software']);self.assertFalse(t['brief']['budget'])
        self.assertIn('14英寸',t['draft']['body']);self.assertEqual(t['candidates'][0]['status'],'conditional');self.assertNotEqual(t['status'],'blocked')
        self.assertNotIn('AutoCAD',str(t['task_context']))
    async def test_B_selection_request_is_not_product_filter(self):
        t=store.create_task();t['brief']['product']='不了解工科学生选什么样的电脑比较符合学习任务需求。'
        c=ensure_context(t)
        self.assertEqual(c['product_intent']['selected'],[])
        self.assertEqual(t['brief']['product'],'不了解工科学生选什么样的电脑比较符合学习任务需求。')
        with patch.object(workflow.knowledge,'discover',new_callable=AsyncMock,return_value=results()) as d:
            await workflow.generate_task(t)
        self.assertFalse(d.await_args.args[0]['product_intent']['selected'])
    def test_C_mixed_tasks_keep_ambiguity_without_hard_GPU_or_local_AI(self):
        t=store.create_task();self.message(t,'可能要建模，也想用 AI。')
        c=t['task_context'];self.assertGreaterEqual(len(c['use_tasks']),2)
        self.assertFalse(c['hard_constraints']);self.assertNotIn('独显',str(c))
        self.assertNotIn('本地大模型',str(c))
    def test_D_web_AI_replaces_old_inference(self):
        t=store.create_task();self.message(t,'可能要建模，也想用 AI。')
        t['task_context']['conditions'].append({'id':'local','field':'ai_mode','value':'本地AI算力','state':'inferred','strength':'soft'})
        self.message(t,'只使用网页版 AI。')
        self.assertNotIn('本地AI算力',str(t['task_context']['conditions']))
        self.assertIn('网页版AI',str(t['task_context']['conditions']))
    async def test_E_unknown_budget_software_does_not_loop_question(self):
        t=store.create_task();self.message(t,'给工科新生写条朋友圈，预算和软件我都不知道。')
        with patch.object(workflow.knowledge,'discover',new_callable=AsyncMock,return_value=results()):
            t=await workflow.generate_task(t)
        self.assertTrue(t['draft']);self.assertNotEqual(t['status'],'needs_input')
    def test_F_comparison_does_not_replace_selected_model(self):
        t=store.create_task();self.message(t,'指定 MateBook 14 2025，写朋友圈。')
        selected=t['brief']['product'];self.message(t,'和 MateBook D 16 2026 比较一下。')
        self.assertEqual(t['brief']['product'],selected)
        self.assertEqual(t['task_context']['product_intent']['selected'],[selected])
        self.assertTrue(t['task_context']['product_intent']['compare'])
    def test_manual_saved_requirement_dominates_older_chat_and_has_source(self):
        t=store.create_task();self.message(t,'给学生写朋友圈。')
        before=copy.deepcopy(t['brief']);t['brief']['audience']='企业采购负责人';apply_brief_save(t,before)
        saved=store.save_task(t);loaded=store.get_task(saved['id']);ensure_context(loaded)
        aud=[x for x in loaded['task_context']['conditions'] if x['field']=='audience']
        self.assertEqual(aud[-1]['value'],'企业采购负责人')
        self.assertEqual(loaded['requirement_events'][-1]['kind'],'brief_save')
    def test_model_cannot_invent_stated_conditions_or_hard_assumptions(self):
        t=store.create_task();e=self.message(t,'给工科学生写内容。')
        apply_model_understanding(t,{'task_context':[{'field':'software','value':'必须独显','state':'stated','evidence_quote':'不存在的原话','reason':'猜测','strength':'hard'}]},e)
        cond=[x for x in t['task_context']['conditions'] if x['field']=='software'][0]
        self.assertEqual((cond['state'],cond['strength']),('inferred','soft'))
    def test_H_hardware_cannot_prove_modeling_or_local_AI(self):
        t=store.create_task();self.message(t,'必须能建模。');t.update(results());t['product_catalog']=results()['catalog']
        req=t['task_context']['use_tasks'][0]
        proposal=MatchResponse.model_validate({'candidates':[{'product_ref':'p1','fit_assessments':[{'requirement_id':req['id'],'status':'satisfied','fact_ids':['f1']}]}]})
        assess(t,proposal)
        self.assertEqual(t['candidates'][0]['fit_assessments'][0]['status'],'unknown')
        self.assertEqual(t['candidates'][0]['status'],'conditional')
    def test_I_budget_remains_unknown_without_price_evidence(self):
        t=store.create_task();self.message(t,'给学生推荐，预算不超过6000元。');t.update(results());t['product_catalog']=results()['catalog']
        assess(t)
        budget=[f for f in t['fit_assessments'] if f['requirement_id'] in [r['id'] for r in t['task_context']['conditions'] if r['field']=='budget']]
        self.assertEqual(budget[0]['status'],'unknown')
    async def test_J_N_missing_evidence_is_useful_gap_not_missing_model(self):
        t=store.create_task();self.message(t,'给学生写学习电脑选择内容。')
        with patch.object(workflow.knowledge,'discover',new_callable=AsyncMock,return_value={'facts':[],'assets':[],'evidence':[],'catalog':[], 'gaps':[{'kind':'evidence_missing','message':'授权库没有对应任务的产品原文'}]}):
            t=await workflow.generate_task(t)
        self.assertEqual(t['status'],'needs_evidence');self.assertIsNone(t['draft'])
        self.assertIn('产品原文',t['messages'][-1]['content']);self.assertNotIn('请明确型号',t['messages'][-1]['content'])
    async def test_M_platform_only_reuses_evidence(self):
        t=store.create_task();self.message(t,'给学生写朋友圈。');t.update(results());t['product_catalog']=results()['catalog'];assess(t);t['selling_point_plan']=default_plan(t)
        before=copy.deepcopy(t['brief']);t['brief']['platform']='xiaohongshu';apply_brief_save(t,before)
        with patch.object(workflow.knowledge,'discover',new_callable=AsyncMock) as d:
            await prepare_matching(t,workflow.knowledge,AsyncMock(),False)
        d.assert_not_awaited();self.assertEqual(t['facts'][0]['id'],'f1')
    async def test_repeated_query_stops_with_bounded_actions(self):
        t=store.create_task();self.message(t,'给学生推荐电脑。')
        response={'next_action':'read','document_refs':['doc1'],'candidates':[]}
        plan={'selling_points':[]}
        chat=AsyncMock(side_effect=lambda prompt,payload: response if '候选发现与匹配' in prompt else plan);reader=AsyncMock(return_value=results())
        with patch.object(workflow.knowledge,'discover',new_callable=AsyncMock,return_value=results()),patch.object(workflow.knowledge,'read_documents',reader):
            await prepare_matching(t,workflow.knowledge,chat,True)
        reader.assert_awaited_once();self.assertIn('停止重复',str(t['evidence_gaps']))
    def test_invalid_product_and_fact_refs_cannot_enter_plan(self):
        t=store.create_task();self.message(t,'给学生写内容。');t.update(results());t['product_catalog']=results()['catalog'];assess(t)
        plan=validate_plan(t,{'selling_points':[{'product_ref':'invented','fact_ids':['invented'],'task_ids':[],'value_explanation':'好','allowed_expression':'能流畅建模'}]})
        self.assertNotIn('invented',str(plan));self.assertNotIn('能流畅建模',str(plan))
