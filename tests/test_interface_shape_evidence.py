"""USB protocol generations never prove connector shape; all originals are synthetic."""
import unittest

from huawei_agent.matching import MatchResponse, SellingPlan, assess, validate_plan, _interface_shapes_supported
from test_candidate_reason_evidence import fixture


def port_task(original):
    task=fixture()
    fact=task['facts'][0]
    fact.update(category='接口',excerpt=original,claim='接口：'+original)
    task['evidence_refs'][0]['excerpt']=original
    assess(task)
    return task


def plan_for(expression, *, action='generate', value='可比较已提供的接口规格。'):
    return {'next_action':action,'selling_points':[{'task_ids':['req-learning'],'product_ref':'product-a',
        'fact_ids':['memory-a'],'allowed_expression':expression,'value_explanation':value}]}


class InterfaceShapeEvidenceTests(unittest.TestCase):
    def test_protocol_only_cannot_authorize_usb_a_even_if_marketing_summary_mentions_it(self):
        task=port_task('USB-C 接口 × 1（全功能）\n\nUSB3.2 Gen1 × 2\n\nHDMI × 1')
        task['evidence_refs'].append({'id':'marketing-a','product_ref':'product-a','document_ref':'selling-a',
            'kind':'selling_points','fact_ids':[],'excerpt':'两个USB-A可连接传统外设。'})
        task['product_catalog'][1]['summaries']=[{'excerpt':'两个USB-A可连接传统外设。'}]
        plan=validate_plan(task,plan_for('带两个USB-A和HDMI。'))
        self.assertTrue(plan['selling_points'])
        allowed=plan['selling_points'][0]['allowed_expression']
        self.assertNotIn('USB-A',allowed)
        self.assertIn('USB3.2 Gen1 × 2',allowed)
        self.assertIn('USB-C 接口 × 1（全功能）',allowed)
        self.assertEqual(plan['next_action'],'generate')
        self.assertEqual(plan['selling_points'][0]['fact_ids'],['memory-a'])
        SellingPlan.model_validate(plan)

    def test_explicit_a_shape_original_can_be_retained(self):
        task=port_task('USB-A 接口 × 2')
        plan=validate_plan(task,plan_for('USB-A 接口 × 2'))
        self.assertTrue(plan['selling_points'])
        self.assertIn('USB-A',plan['selling_points'][0]['allowed_expression'])
        SellingPlan.model_validate(plan)

    def test_explicit_c_shape_original_can_be_retained_without_becoming_a(self):
        task=port_task('USB-C 接口 × 1（全功能）')
        plan=validate_plan(task,plan_for('USB-C 接口 × 1（全功能）'))
        self.assertTrue(plan['selling_points'])
        self.assertIn('USB-C',plan['selling_points'][0]['allowed_expression'])
        self.assertNotIn('USB-A',str(plan))

    def test_a_b_c_labels_must_all_be_present_in_originals_not_protocol_name(self):
        protocol=[{'category':'接口','excerpt':'USB3.2 Gen1 × 2'}]
        for label in ('USB-A','USB-B','USB-C','USB-A/B/C','Type-C'):
            self.assertFalse(_interface_shapes_supported(label,protocol))
        explicit=[{'category':'接口','excerpt':'USB Type-A、USB-B、USB-C'}]
        self.assertTrue(_interface_shapes_supported('USB-A/B/C',explicit))
        self.assertTrue(_interface_shapes_supported('Type-C',explicit))

    def test_candidate_explanation_and_rank_use_same_product_fact_shape_guard(self):
        task=port_task('USB-C 接口 × 1（全功能）\nUSB3.2 Gen1 × 2')
        proposal=MatchResponse.model_validate({'candidates':[{'product_ref':'product-a',
            'ranking_reason':'两个USB-A便于直接接U盘。','fit_assessments':[{'requirement_id':'req-learning',
            'status':'unknown','fact_ids':['memory-a'],'explanation':'两个USB-A可接入常用外设。'}]}]})
        assess(task,proposal)
        candidate=next(x for x in task['candidates'] if x['product_ref']=='product-a')
        public=candidate['ranking_reason']+' '.join(f['explanation'] for f in candidate['fit_assessments'])
        self.assertNotIn('USB-A',public)
        self.assertIn('USB3.2 Gen1',public)
        self.assertEqual(candidate['status'],'conditional')

    def test_oversize_original_is_rejected_without_truncation_or_schema_overflow(self):
        original='USB3.2 Gen1 × 2\n'+('仅限对应指定版本；全部原文限定保留。'*70)
        self.assertGreater(len(original),1000)
        task=port_task(original)
        plan=validate_plan(task,plan_for('两个USB-A。'))
        self.assertEqual(plan['selling_points'],[])
        self.assertEqual(plan['next_action'],'stop')
        SellingPlan.model_validate(plan)

    def test_valid_short_original_fallback_preserves_read_state(self):
        task=port_task('USB3.2 Gen1 × 2')
        plan=validate_plan(task,plan_for('两个USB-A。',action='read'))
        self.assertEqual(plan['next_action'],'read')
        self.assertNotIn('USB-A',str(plan))
        self.assertIn('USB3.2 Gen1 × 2',plan['selling_points'][0]['allowed_expression'])
        SellingPlan.model_validate(plan)


if __name__=='__main__':unittest.main()
