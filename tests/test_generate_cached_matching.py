"""Actual generation must persist guarded cached recommendations, with no new retrieval."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from huawei_agent import store, workflow
from huawei_agent.matching import assess
from huawei_agent.task_context import summarize
from test_candidate_reason_evidence import fixture, proposed


class GenerateCachedMatchingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        p=patch.object(store,'DATA',Path(self.tmp.name));p.start();self.addCleanup(p.stop)
        p=patch.object(workflow,'load_settings',return_value={'deepseek_api_key':''});p.start();self.addCleanup(p.stop)

    def dirty_cached_task(self):
        task=store.create_task('旧缓存任务')
        sample=fixture();task.update({k:v for k,v in sample.items() if k!='id'})
        for fact in task['facts']:fact.setdefault('claim',fact['category']+'：'+fact['excerpt'])
        summarize(task);assess(task,proposed())
        task['assets']=[{'id':'asset-'+str(i),'name':'test.png','caption':'产品图','model':'MateBook A 2026 Windows版',
            'product_ref':'product-a','product_id':'product-a','verified':True} for i in range(3)]
        gt=next(c for c in task['candidates'] if c['product_ref']=='product-gt')
        gt['ranking_reason']='3:2 OLED、32GB与1/2TB SSD更适合高负载，约1.49kg。'
        gt['fit_assessments'][0]['explanation']=gt['ranking_reason']
        task['selling_point_plan']={'next_action':'generate',
            'content_direction':'Windows通用软件路线便于对接常见课程软件。',
            'selling_points':[{'task_ids':['req-learning'],'product_ref':'product-a','fact_ids':['memory-a'],
                'allowed_expression':'内存最高可选32GB，部分配置。','value_explanation':'Windows通用软件路线便于对接常见课程软件。',
                'required_qualifiers':['Ultra 7 155H仅Windows。'],'prohibited_extensions':[]}],
            'rejected_angles':['MateBook GT无USB-A和HDMI。'],'remaining_gaps':[]}
        task['matching_key']=task['task_context']['matching_key']
        return store.save_task(task,'保存旧缓存')

    def public(self, task):
        return json.dumps({'candidates':task['candidates'],'recommendations':task['recommendations'],
            'selling_point_plan':task['selling_point_plan']},ensure_ascii=False)

    def assert_clean(self, task):
        gt=next(c for c in task['candidates'] if c['product_ref']=='product-gt')
        gt_text=gt['ranking_reason']+' '.join(a['explanation'] for a in gt['fit_assessments'])
        for token in ['OLED','32GB','1/2TB','1.49kg','高负载','更适合']:
            self.assertNotIn(token,gt_text)
        for token in ['常见课程软件','通用软件路线','155H','USB-A','HDMI']:
            self.assertNotIn(token,self.public(task))
        self.assertIn('最高可选32GB',self.public(task))
        self.assertTrue(task.get('rejected_matching_text'))

    async def test_generate_reuses_and_persists_cleaned_cache_then_reopen_stays_clean(self):
        task=self.dirty_cached_task();before=task['revision']
        with patch.object(workflow.knowledge,'discover',AsyncMock(side_effect=AssertionError('cache must not discover'))) as discover, \
             patch.object(workflow.knowledge,'read_documents',AsyncMock(side_effect=AssertionError('cache must not read'))) as read, \
             patch.object(workflow,'json_chat',AsyncMock(side_effect=AssertionError('rules must not call model'))) as model:
            result=await workflow.generate_task(store.get_task(task['id']))
        self.assertTrue(result['draft']);self.assertNotEqual(result['status'],'error')
        reopened=store.get_task(task['id']);self.assert_clean(reopened)
        self.assertGreater(reopened['revision'],before)
        self.assertEqual(reopened['candidates'],result['candidates'])
        discover.assert_not_awaited();read.assert_not_awaited();model.assert_not_awaited()

    async def test_actual_writer_payload_gets_guarded_plan_without_new_understanding_or_matching_calls(self):
        task=self.dirty_cached_task();payloads=[]
        async def model(prompt,payload):
            payloads.append(deepcopy(payload))
            if 'draft' in payload:return {'passed':True,'issues':[],'notes':[]}
            return {'title':'对照已核对的内存规格','lead':'按实际任务继续比较','body':'内存最高可选32GB，部分配置。广告，AI辅助内容。',
                'cta':'咨询具体配置','tags':[],'images':[{'id':'asset-0','caption':'产品图','position':'正文后'}],
                'fact_ids':['memory-a']}
        with patch.object(workflow,'load_settings',return_value={'deepseek_api_key':'synthetic'}), \
             patch.object(workflow,'json_chat',AsyncMock(side_effect=model)) as chat, \
             patch.object(workflow.knowledge,'discover',AsyncMock(side_effect=AssertionError('no fresh discovery'))) as discover, \
             patch.object(workflow.knowledge,'read_documents',AsyncMock(side_effect=AssertionError('no fresh reading'))) as read:
            result=await workflow.generate_task(store.get_task(task['id']))
        self.assertEqual(chat.await_count,2,result.get('repair_record'))  # Existing writer + final review only.
        self.assertNotEqual(result['status'],'error')
        self.assert_clean(store.get_task(task['id']))
        writer=payloads[0]
        for token in ['常见课程软件','155H','USB-A','HDMI']:
            self.assertNotIn(token,json.dumps(writer.get('selling_point_plan'),ensure_ascii=False))
        discover.assert_not_awaited();read.assert_not_awaited()

    async def test_platform_change_preserves_cache_and_does_not_ask_budget_or_software(self):
        task=self.dirty_cached_task();task['brief']['platform']='xiaohongshu'
        task=store.save_task(task,'只改平台')
        with patch.object(workflow.knowledge,'discover',AsyncMock(side_effect=AssertionError('platform change must reuse evidence'))) as discover, \
             patch.object(workflow.knowledge,'read_documents',AsyncMock(side_effect=AssertionError('platform change must reuse evidence'))) as read:
            result=await workflow.generate_task(store.get_task(task['id']))
        reopened=store.get_task(task['id']);self.assert_clean(reopened)
        self.assertEqual(reopened['brief']['platform'],'xiaohongshu')
        self.assertNotEqual(result['status'],'needs_input')
        self.assertEqual(len(result['draft']['images']),3)
        self.assertEqual(reopened['brief']['budget'],'');self.assertEqual(reopened['brief']['software'],'')
        discover.assert_not_awaited();read.assert_not_awaited()

    async def test_cached_stop_or_read_cleans_and_persists_without_writing(self):
        for action in ('stop','read'):
            task=self.dirty_cached_task();task['selling_point_plan']['next_action']=action
            if action=='stop':task['selling_point_plan']['selling_points']=[]
            task=store.save_task(task,'保存暂停方案')
            with patch.object(workflow.knowledge,'discover',AsyncMock(side_effect=AssertionError('no new query'))) as discover, \
                 patch.object(workflow,'rule_draft',side_effect=AssertionError('stop/read must not write')) as writer:
                result=await workflow.generate_task(store.get_task(task['id']))
            reopened=store.get_task(task['id'])
            self.assertEqual(reopened['selling_point_plan']['next_action'],action)
            self.assertEqual(result['status'],'needs_evidence')
            self.assertNotIn('OLED',next(c for c in reopened['candidates'] if c['product_ref']=='product-gt')['ranking_reason'])
            writer.assert_not_called();discover.assert_not_awaited()


if __name__=='__main__':unittest.main()
