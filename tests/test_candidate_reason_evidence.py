"""Recommendation cards are public claims too; all evidence here is synthetic."""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import AsyncMock

from huawei_agent.matching import MatchResponse, assess, default_plan, prepare_matching, validate_plan
from huawei_agent.task_context import ensure_context


def fixture():
    task={'id':'reason-boundary','brief':{'platform':'moments','audience':'工科新生','scenario':'school',
        'goal':'比较选型','budget':'','product':'','software':''},'messages':[],
        'facts':[{'id':'memory-a','product_ref':'product-a','product_id':'product-a',
            'model':'MateBook A 2026 Windows版','category':'内存','excerpt':'最高可选32GB，部分配置。',
            'verified':True,'document_ref':'doc-a','evidence_ref_ids':['ref-a']}],
        'evidence_refs':[{'id':'ref-a','fact_id':'memory-a','fact_ids':['memory-a'],'product_ref':'product-a',
            'document_ref':'doc-a','excerpt':'最高可选32GB，部分配置。'}],
        'assets':[],'evidence':[],
        'product_catalog':[{'product_ref':'product-gt','model':'MateBook GT 系列','documents':[]},
                           {'product_ref':'product-a','model':'MateBook A 2026 Windows版','documents':[]}]}
    context=ensure_context(task)
    context['conditions']=[{'id':'req-learning','field':'use_tasks','value':'文档与课程学习','state':'stated',
        'source_ids':['submitted'],'reason':'合成用户要求','strength':'soft'}]
    return task


def proposed(gt_ids=None, a_text='最高可选32GB，部分配置，可供比较。', ranking='32GB足够高负载学习，匹配度高。'):
    return MatchResponse.model_validate({'candidates':[
        {'product_ref':'product-gt','ranking_reason':'内存与接口更适合高负载学习，但约1.49kg与集显是边界。',
         'fit_assessments':[{'requirement_id':'req-learning','status':'satisfied','fact_ids':gt_ids or [],
            'explanation':'3:2 OLED、32GB内存与1/2TB SSD，适合多文档与较大资料工作集。'}]},
        {'product_ref':'product-a','ranking_reason':ranking,'fit_assessments':[{'requirement_id':'req-learning',
            'status':'satisfied','fact_ids':['memory-a'],'explanation':a_text}]}]})


def public_reason(candidate):
    return candidate['ranking_reason']+' '+ ' '.join(f['explanation'] for f in candidate['fit_assessments'])


class CandidateReasonEvidenceTests(unittest.TestCase):
    def test_real_gt_empty_facts_cannot_publish_model_parameters_or_definite_fit(self):
        task=fixture();assess(task,proposed())
        gt=next(c for c in task['candidates'] if c['product_ref']=='product-gt')
        self.assertEqual(gt['fact_ids'],[])
        self.assertEqual(gt['status'],'conditional')
        for token in ['OLED','32GB','1/2TB','1.49kg','更适合','高负载']:
            self.assertNotIn(token,public_reason(gt))
        self.assertIn('尚未核实',public_reason(gt))
        self.assertIn('召回',public_reason(gt))
        self.assertTrue(any(x['kind']=='ranking_reason' and x['product_ref']=='product-gt' for x in task['rejected_matching_text']))
        self.assertTrue(any(x['kind']=='fit_explanation' and x['product_ref']=='product-gt' for x in task['rejected_matching_text']))
        self.assertNotIn('rejected_ranking_reason',gt)  # Internal rejected prose is not a generator input.
        rec=next(x for x in task['recommendations'] if x['model']=='MateBook GT 系列')
        self.assertNotIn('1.49kg',rec['reason']+rec['limitations'])

    def test_other_product_fact_id_cannot_support_gt_explanation(self):
        task=fixture();assess(task,proposed(['memory-a']))
        gt=next(c for c in task['candidates'] if c['product_ref']=='product-gt')
        self.assertFalse(gt['fit_assessments'][0]['fact_ids'])
        self.assertNotIn('32GB',public_reason(gt))

    def test_unknown_keeps_valid_original_specs_with_qualifiers_but_narrows_fit_language(self):
        task=fixture();assess(task,proposed())
        known=next(c for c in task['candidates'] if c['product_ref']=='product-a')
        text=public_reason(known)
        self.assertEqual(known['status'],'conditional')
        for token in ['32GB','最高','部分配置','尚未核实']:
            self.assertIn(token,text)
        for token in ['足够','匹配度高','高负载','更适合']:
            self.assertNotIn(token,text)

    def test_unsupported_parameter_clause_does_not_hide_beside_a_valid_numeric_fact(self):
        task=fixture();assess(task,proposed(a_text='3:2 OLED屏和32GB内存，值得比较。', ranking='32GB内存，值得比较。'))
        known=next(c for c in task['candidates'] if c['product_ref']=='product-a')
        self.assertNotIn('OLED',public_reason(known))
        self.assertNotIn('3:2',public_reason(known))
        self.assertIn('最高',public_reason(known))

    def test_existing_supported_reason_survives_without_erasing_all_useful_information(self):
        task=fixture();text='内存最高可选32GB，部分配置，可作为比较的规格依据。'
        assess(task,proposed(a_text=text,ranking=text))
        known=next(c for c in task['candidates'] if c['product_ref']=='product-a')
        self.assertIn('可作为比较的规格依据',public_reason(known))
        self.assertIn('32GB',public_reason(known))

    def test_candidate_with_effective_evidence_groups_before_unread_model_rank(self):
        task=fixture();assess(task,proposed())
        self.assertEqual(task['candidates'][0]['product_ref'],'product-a')
        task['task_context']['product_intent'].update(mode='selected',selected=['MateBook GT 系列'])
        assess(task,proposed())
        self.assertEqual(task['candidates'][0]['product_ref'],'product-gt')

    def test_conflicting_fact_scope_or_reference_cannot_make_display_claim_valid(self):
        for mutation in ('fact_scope','ref_scope','historical'):
            task=fixture()
            if mutation=='fact_scope':task['facts'][0]['product_id']='product-gt'
            elif mutation=='ref_scope':task['evidence_refs'][0]['product_ref']='product-gt'
            else:task['facts'][0]['historical']=True
            assess(task,proposed())
            known=next(c for c in task['candidates'] if c['product_ref']=='product-a')
            self.assertNotIn('32GB',public_reason(known))

    def test_platform_cache_rechecks_old_display_strings_without_querying_library(self):
        task=fixture();assess(task,proposed())
        task['selling_point_plan']=default_plan(task)
        gt=next(c for c in task['candidates'] if c['product_ref']=='product-gt')
        gt['ranking_reason']='3:2 OLED、32GB与1/2TB SSD更适合高负载，约1.49kg。'
        gt['fit_assessments'][0]['explanation']=gt['ranking_reason']
        task['matching_key']=task['task_context']['matching_key']
        knowledge=AsyncMock()
        asyncio.run(prepare_matching(task,knowledge,AsyncMock(),False))
        knowledge.discover.assert_not_awaited();knowledge.read_documents.assert_not_awaited()
        gt=next(c for c in task['candidates'] if c['product_ref']=='product-gt')
        self.assertNotIn('OLED',public_reason(gt));self.assertNotIn('32GB',public_reason(gt))

    def test_selling_value_explanation_receives_same_scope_and_unknown_fit_guard(self):
        task=fixture();assess(task,proposed())
        plan=validate_plan(task,{'selling_points':[{'task_ids':['req-learning'],'product_ref':'product-a',
            'fact_ids':['memory-a'],'allowed_expression':'内存最高可选32GB，部分配置。',
            'value_explanation':'3:2 OLED与32GB足够高负载学习，匹配度高。'}]})
        self.assertTrue(plan['selling_points'])
        value=plan['selling_points'][0]['value_explanation']
        for token in ['OLED','足够','高负载','匹配度高']:
            self.assertNotIn(token,value)
        self.assertIn('最高',value);self.assertIn('部分配置',value)
    def test_unbound_direction_and_rejected_angles_cannot_bypass_validated_points(self):
        task=fixture();assess(task,proposed())
        plan=validate_plan(task,{'content_direction':'Windows 11 家庭版路线便于对接常见课程软件。',
            'rejected_angles':['MateBook GT无USB-A和HDMI。','缺少对应软件兼容性证据，不承诺实际表现。'],
            'selling_points':[{'task_ids':['req-learning'],'product_ref':'product-a','fact_ids':['memory-a'],
                'allowed_expression':'内存最高可选32GB，部分配置。','value_explanation':'可比较已提供的规格。'}]})
        self.assertNotIn('常见课程软件',str(plan))
        self.assertNotIn('USB-A',str(plan));self.assertNotIn('HDMI',str(plan))
        self.assertIn('已核对的内存',plan['content_direction'])
        self.assertIn('缺少对应软件兼容性证据，不承诺实际表现。',plan['rejected_angles'])
        self.assertTrue(any(x['kind']=='content_direction' for x in task['rejected_matching_text']))

    def test_cache_checks_all_backend_candidates_beyond_model_output_cap(self):
        task=fixture();assess(task,proposed());task['selling_point_plan']=default_plan(task)
        for i in range(9):
            task['product_catalog'].append({'product_ref':'extra-'+str(i),'model':'Extra Model '+str(i),'documents':[]})
            task['candidates'].append({'product_ref':'extra-'+str(i),'model':'Extra Model '+str(i),
                'fit_assessments':[],'status':'conditional','ranking_reason':'32GB足够高负载。','selected_by_user':False,'fact_ids':[]})
        task['matching_key']=task['task_context']['matching_key'];knowledge=AsyncMock()
        asyncio.run(prepare_matching(task,knowledge,AsyncMock(),False))
        self.assertEqual(len(task['candidates']),11)
        self.assertTrue(all('足够' not in c['ranking_reason'] for c in task['candidates']))
        knowledge.discover.assert_not_awaited()

    def test_required_qualifiers_are_from_point_originals_not_unrelated_model_parameters(self):
        task=fixture();assess(task,proposed())
        plan=validate_plan(task,{'selling_points':[{'task_ids':['req-learning'],'product_ref':'product-a',
            'fact_ids':['memory-a'],'allowed_expression':'内存最高可选32GB，部分配置。',
            'value_explanation':'已提供可比较的规格。','required_qualifiers':['Ultra7 155H仅Windows。'],
            'prohibited_extensions':['MateBook GT无USB-A和HDMI。','不将规格视作真实任务性能。']}],
            'remaining_gaps':['X无USB-A和HDMI。','缺少对应任务实测证据。']})
        public=str(plan)
        for token in ['Ultra7','155H','Windows','USB-A','HDMI']:
            self.assertNotIn(token,public.replace('MateBook A 2026 Windows版',''))
        point=plan['selling_points'][0]
        self.assertIn('最高可选32GB，部分配置。',point['required_qualifiers'])
        self.assertIn('不将规格视作真实任务性能。',point['prohibited_extensions'])
        self.assertIn('缺少对应任务实测证据。',plan['remaining_gaps'])



if __name__=='__main__':unittest.main()
