"""Recommendation evidence boundaries; synthetic sources, no provider calls."""
from copy import deepcopy
import unittest

from huawei_agent.validation import review_recommendation_claims, validate


def task_with_evidence(body="MateBook A 屏幕为14英寸。"):
    return {
        "brief": {"product": "MateBook A", "budget": "6000元", "platform": "moments"},
        "task_context": {"version": 3, "product_intent": {"mode": "selected", "selected": ["MateBook A"]}},
        "candidates": [{"product_id": "a", "model": "MateBook A", "status": "recommendable", "fit_assessments": []}],
        "facts": [{"id": "screen-a", "product_id": "a", "model": "MateBook A", "document_id": "doc-a",
                   "configuration_scope": "A Windows 2026", "category": "屏幕", "excerpt": "屏幕为14英寸",
                   "claim": "屏幕为14英寸", "verified": True}],
        "draft": {"title": "学习电脑的比较方向", "lead": "", "body": body, "cta": "", "tags": [],
                  "images": [], "fact_ids": ["screen-a"]},
        "assets": [], "quotes": {"quotes": [], "best": []}, "evidence_refs": [],
    }


def blocked(task, semantic=None):
    return [c for c in review_recommendation_claims(task, semantic)["checks"] if c["status"] == "blocked"]


class MatchingEvidenceTests(unittest.TestCase):
    def test_exact_same_product_original_number_is_supported(self):
        task = task_with_evidence()
        result = review_recommendation_claims(task)
        self.assertEqual(result["checks"], [])
        self.assertEqual(result["claim_support"][0]["fact_ids"], ["screen-a"])
        self.assertEqual(result["claim_support"][0]["requirement_version"], 3)

    def test_numeric_fact_from_a_cannot_support_b_even_when_cited(self):
        task = task_with_evidence("MateBook B 屏幕为14英寸。")
        task["facts"].append({"id": "screen-b", "product_id": "b", "model": "MateBook B", "document_id": "doc-b",
                              "excerpt": "屏幕为16英寸", "verified": True})
        self.assertTrue(blocked(task))
        self.assertEqual(review_recommendation_claims(task)["claim_support"][0]["product_ids"], ["b"])

    def test_screen_ratio_from_another_product_cannot_support_current_product(self):
        for colon in (':', '：'):
            with self.subTest(colon=colon):
                task = task_with_evidence('MateBook A 屏幕比例为3'+colon+'2。')
                task['facts'][0].update(excerpt='屏幕比例16:10', claim='屏幕比例16:10')
                task['facts'].append({'id':'screen-b','product_id':'b','model':'MateBook B','document_id':'doc-b',
                                      'category':'屏幕','excerpt':'屏幕比例3:2','verified':True})
                result = review_recommendation_claims(task, {'passed':True,'issues':[]})
                self.assertTrue(any(c['status']=='blocked' and c.get('location')=='body' for c in result['checks']))
                self.assertTrue(any(c['kind']=='specification' and c['product_ids']==['a'] and c['status']=='unsupported'
                                    for c in result['claim_support']))

    def test_screen_resolution_from_another_product_cannot_support_current_product(self):
        for symbol in ('×', 'x', '✕'):
            with self.subTest(symbol=symbol):
                task = task_with_evidence('MateBook A 屏幕分辨率为2880'+symbol+'1920。')
                task['facts'][0].update(excerpt='屏幕分辨率2160×1440', claim='屏幕分辨率2160×1440')
                task['facts'].append({'id':'screen-b','product_id':'b','model':'MateBook B','document_id':'doc-b',
                                      'category':'屏幕','excerpt':'屏幕分辨率2880×1920','verified':True})
                self.assertTrue(blocked(task, {'passed':True,'issues':[]}))

    def test_same_product_screen_number_shapes_support_equivalent_renderings_and_qualifiers(self):
        for colon in (':', '：'):
            for symbol in ('×', 'x', '✕'):
                with self.subTest(colon=colon,symbol=symbol):
                    task = task_with_evidence('MateBook A 屏幕比例16'+colon+'10，最高分辨率2880'+symbol+'1920。')
                    task['facts'][0].update(excerpt='屏幕比例16:10，最高分辨率2880×1920')
                    self.assertEqual(blocked(task), [])
                    task['draft']['body'] = 'MateBook A 屏幕比例16'+colon+'10，分辨率2880'+symbol+'1920。'
                    self.assertTrue(blocked(task))

    def test_screen_number_extension_does_not_check_ordinary_dates_times_or_multiplication(self):
        for text in ('2026-10-20发布，下午16:10到店看屏幕。', '作业要求计算2880x1920。', '活动编号316，14人参加。'):
            with self.subTest(text=text):
                task = task_with_evidence(text)
                self.assertEqual(blocked(task), [])

    def test_candidate_caveat_does_not_waive_same_product_numeric_identity(self):
        for sentence in ['MateBook A 可作候选，内存32GB。',
                         'MateBook A 可作为32GB内存候选。',
                         'MateBook A 可作3:2屏幕候选。',
                         'MateBook A 值得比较的3:2屏幕。']:
            with self.subTest(sentence=sentence):
                task = task_with_evidence(sentence)
                task['candidates'][0]['status'] = 'conditional'
                task['facts'][0].update(category='参数', excerpt='内存16GB，屏幕比例16:10')
                task['facts'].append({'id':'b','model':'MateBook B','product_id':'b','document_id':'doc-b',
                                      'category':'参数','excerpt':'内存32GB，屏幕比例3:2','verified':True})
                self.assertTrue(blocked(task, {'passed':True,'issues':[]}))
                task['draft']['body'] = 'MateBook A 可作为16GB内存候选。'
                self.assertEqual(blocked(task), [])

    def test_software_unknown_cannot_waive_asserted_product_specification(self):
        for sentence in ['MateBook A 软件适配待核实且内存32GB。',
                         'MateBook A 内存32GB，软件适配待核实。',
                         'MateBook A 内存32GB兼容性待核实。',
                         'MateBook A 32GB内存是否适合建模？']:
            with self.subTest(sentence=sentence):
                task = task_with_evidence(sentence)
                task['facts'][0].update(category='内存', excerpt='内存16GB')
                self.assertTrue(blocked(task))

    def test_genuine_parameter_questions_and_unknown_values_are_not_asserted_specs(self):
        for sentence in ['MateBook A 内存是否32GB？', 'MateBook A 内存是不是32GB？',
                         'MateBook A 内存32GB吗？', 'MateBook A 内存32GB？',
                         'MateBook A 内存32GB吗?', 'MateBook A 内存32GB?',
                         'MateBook A 32GB内存待核实。', 'MateBook A 内存可能是32GB。',
                         'MateBook A 内存容量未知，暂不讨论具体参数。']:
            with self.subTest(sentence=sentence):
                task = task_with_evidence(sentence)
                task['facts'][0].update(category='内存', excerpt='内存16GB')
                self.assertEqual(blocked(task), [])

    def test_default_product_prevents_using_any_model_number(self):
        task = task_with_evidence("屏幕为16英寸。")
        task["facts"].append({"id": "screen-b", "product_id": "b", "model": "MateBook B", "document_id": "doc-b",
                              "excerpt": "屏幕为16英寸", "verified": True})
        self.assertTrue(blocked(task))

    def test_unique_selling_plan_supplies_implicit_draft_product(self):
        task = task_with_evidence("屏幕为14英寸。")
        task['task_context']['product_intent']['selected'] = []
        task['facts'].append({'id': 'b', 'product_id': 'b', 'model': 'MateBook B', 'document_id': 'db', 'excerpt': '屏幕16英寸', 'verified': True})
        task['selling_point_plan'] = {'selling_points': [{'product_ref': 'a', 'fact_ids': ['screen-a']}]}
        self.assertEqual(blocked(task), [])

    def test_final_unique_title_supplies_identity_but_mixed_titles_do_not(self):
        task = task_with_evidence("屏幕为14英寸。")
        task['task_context']['product_intent']['selected'] = []
        task['facts'].append({'id': 'b', 'product_id': 'b', 'model': 'MateBook B', 'document_id': 'db', 'excerpt': '屏幕16英寸', 'verified': True})
        task['draft']['title'] = '了解MateBook A'
        self.assertEqual(blocked(task), [])
        task['draft']['title'] = 'MateBook A与MateBook B比较'
        self.assertTrue(blocked(task))

    def test_same_series_system_year_identity_is_not_collapsed(self):
        task = task_with_evidence("MateBook A 鸿蒙版 2026 内存为32GB。")
        task["facts"] = [
            {"id": "ram-w", "product_id": "w", "model": "MateBook A Windows版 2025", "document_id": "dw", "excerpt": "内存32GB", "verified": True},
            {"id": "ram-h", "product_id": "h", "model": "MateBook A 鸿蒙版 2026", "document_id": "dh", "excerpt": "内存16GB", "verified": True},
        ]
        self.assertTrue(blocked(task))
        self.assertEqual(review_recommendation_claims(task)["claim_support"][0]["product_ids"], ["h"])

    def test_model_claim_support_and_verified_flag_do_not_prove_entailment(self):
        task = task_with_evidence("屏幕为32英寸。")
        task["draft"]["claim_support"] = [{"claim": "屏幕为32英寸", "fact_ids": ["screen-a"], "verified": True}]
        self.assertTrue(blocked(task))
        task = task_with_evidence()
        task["facts"][0].pop("document_id")
        self.assertTrue(blocked(task))

    def test_cpu_ram_do_not_prove_performance_or_software_compatibility(self):
        promises = ["MateBook A 可以流畅建模。", "MateBook A 支持AutoCAD。", "MateBook A 专业渲染没问题。",
                    "MateBook A 本地大模型性能有保证。", "MateBook A 轻松应对三维建模。"]
        for promise in promises:
            with self.subTest(promise=promise):
                task = task_with_evidence(promise)
                task["facts"][0].update(excerpt="处理器8核，内存32GB", category="处理器")
                self.assertTrue(blocked(task))

    def test_OS_name_does_not_prove_affirmative_software_route_or_workload_suitability(self):
        claims = ['Windows 11 家庭版路线便于对接常见课程软件。',
                  'Windows路线更方便使用常用软件。', '这个系统适合课程软件。',
                  'Windows是通用软件路线。', '内存32GB，更方便使用建模软件。',
                  '这台电脑的软件兼容性更广。']
        for claim in claims:
            with self.subTest(claim=claim):
                task = task_with_evidence(claim)
                task['facts'][0].update(category='操作系统', excerpt='Windows 11 家庭版 / Linux')
                result = review_recommendation_claims(task, {'passed': True, 'issues': [], 'notes': ['系统路线有助于课程软件']})
                issues = [c for c in result['checks'] if c['status'] == 'blocked' and c.get('location') == 'body']
                self.assertTrue(any('系统名称' in c['message'] and c['quote'] == claim.rstrip('。') for c in issues))
                self.assertTrue(any(c['kind'] == 'software_suitability' and c['status'] == 'unsupported' for c in result['claim_support']))

    def test_uncertain_or_negative_software_route_statements_are_not_affirmative_promises(self):
        for claim in ['Windows路线是否便于对接常见课程软件，仍需核实。',
                      '不能仅凭系统名称认定通用软件路线。',
                      'Windows系统不代表课程软件兼容已确认。',
                      '更方便使用课程软件的结论尚无依据。',
                      '该系统并不适合课程软件。',
                      '建模等专业软件兼容性，建议带课程清单到店核对。']:
            with self.subTest(claim=claim):
                task = task_with_evidence(claim)
                task['facts'][0].update(category='操作系统', excerpt='Windows 11 家庭版 / Linux')
                task['candidates'][0]['status'] = 'conditional'
                self.assertEqual(blocked(task), [])

    def test_actual_product_software_original_can_support_its_claim_and_required_condition(self):
        task = task_with_evidence('MateBook A 支持AutoCAD。')
        task['facts'][0].update(category='软件适配', excerpt='该配置支持AutoCAD')
        self.assertEqual(blocked(task), [])
        support = review_recommendation_claims(task)['claim_support']
        self.assertTrue(any(c['kind'] == 'software_suitability' and c['fact_ids'] == ['screen-a'] and c['status'] == 'supported' for c in support))
        task['facts'][0]['excerpt'] = '仅Windows版支持AutoCAD'
        self.assertTrue(blocked(task))
        task['draft']['body'] = 'MateBook A 仅Windows版支持AutoCAD。'
        self.assertEqual(blocked(task), [])

    def test_negative_software_original_never_proves_positive_claim(self):
        task = task_with_evidence('Windows路线便于对接常见课程软件。')
        task['facts'][0].update(category='适配限制', excerpt='Windows路线并不便于对接常见课程软件')
        self.assertTrue(blocked(task))

    def test_denials_and_pending_verification_are_not_capability_promises(self):
        limitations = ["仅凭CPU不能证明流畅建模。", "MateBook A 能否兼容AutoCAD仍需核实。",
                       "不能保证流畅建模。", "本地大模型性能有保证的结论尚无依据。",
                       "建模性能未知，值得比较屏幕与携带需求。"]
        for text in limitations:
            with self.subTest(text=text):
                self.assertEqual(blocked(task_with_evidence(text)), [])
        self.assertTrue(blocked(task_with_evidence('尚无实测但可以流畅建模。')))
        conditional = task_with_evidence('先作为候选不过它适合所有建模课程。')
        conditional['candidates'][0]['status'] = 'conditional'
        self.assertTrue(blocked(conditional))

    def test_capability_literal_keeps_original_limitation(self):
        task = task_with_evidence("MateBook A 支持AutoCAD。")
        task["facts"][0].update(excerpt="仅Windows版支持AutoCAD", configuration_scope="Windows版")
        # A genuine literal still cannot establish a claim about another system.
        task["facts"][0]["model"] = "MateBook A Windows版"
        task["facts"][0]["product_id"] = "windows-a"
        self.assertTrue(blocked(task))
        task = task_with_evidence("MateBook A 支持AutoCAD。")
        task["facts"][0].update(excerpt="仅Windows版支持AutoCAD")
        self.assertTrue(blocked(task))
        task["draft"]["body"] = "MateBook A 仅Windows版支持AutoCAD。"
        self.assertEqual(blocked(task), [])

    def test_important_numeric_qualifiers_survive_compression(self):
        for excerpt, plain, qualified in [
            ("重量约1.3kg", "重量1.3kg", "重量约1.3kg"),
            ("续航最高10小时", "续航10小时", "续航最高10小时"),
            ("部分配置可选32GB内存", "内存32GB", "部分配置可选32GB内存"),
            ("实验室测试条件下续航10小时", "续航10小时", "实验室测试条件下续航10小时"),
        ]:
            with self.subTest(excerpt=excerpt):
                task = task_with_evidence(plain)
                task["facts"][0].update(excerpt=excerpt)
                self.assertTrue(blocked(task))
                task["draft"]["body"] = qualified
                self.assertEqual(blocked(task), [])

    def test_qualifier_on_another_attribute_does_not_block_unaffected_number(self):
        task = task_with_evidence("MateBook A 屏幕14英寸。")
        task["facts"][0]["excerpt"] = "机身重量约1.3kg，屏幕14英寸；最高续航10小时。"
        self.assertEqual(blocked(task), [])
        task["draft"]["body"] = "MateBook A 机身重量约1.3kg，屏幕14英寸；最高续航10小时。"
        self.assertEqual(blocked(task), [])

    def test_qualifier_on_another_final_number_cannot_waive_omission(self):
        task = task_with_evidence("MateBook A 重量约1.3kg，续航10小时。")
        task["facts"][0]["excerpt"] = "重量约1.3kg，续航约10小时"
        self.assertTrue(blocked(task))

    def test_unknown_fit_cannot_become_unconditional_recommendation(self):
        task = task_with_evidence("MateBook A 适合工科学习。")
        task["candidates"][0]["status"] = "conditional"
        self.assertTrue(blocked(task))
        task["draft"]["body"] = "MateBook A 可作为条件候选，建模兼容仍待核实。"
        self.assertEqual(blocked(task), [])
        task['draft']['title'] = 'MateBook A，到店看看是否适合你'
        task['draft']['body'] = '能否支持AutoCAD，仍待核实。'
        self.assertEqual(blocked(task), [])

    def test_unknown_budget_does_not_become_confirmed_match(self):
        task = task_with_evidence("MateBook A 符合你的预算。")
        self.assertTrue(blocked(task))
        task["quotes"]["quotes"] = [{"status": "verified", "product_id": "a", "checkout_amount": "5000"}]
        self.assertTrue(blocked(task))  # No matching configuration scope.
        task["quotes"]["quotes"][0]["configuration_scope"] = "A Windows 2026"
        self.assertEqual(blocked(task), [])
        task["draft"]["body"] = "预算匹配尚待核实。"
        self.assertEqual(blocked(task), [])

    def test_history_and_conflict_are_not_current_product_evidence(self):
        for flag in [{"historical_snapshot": True}, {"conflict": True}, {"status": "conflict"}]:
            task = task_with_evidence()
            task["facts"][0].update(flag)
            self.assertTrue(blocked(task))

    def test_actual_final_claims_in_all_exported_surfaces_are_inspected(self):
        for key in ("title", "lead", "cta", "selling_points", "tags", "images"):
            task = task_with_evidence()
            if key == "images":
                task["draft"][key] = [{"id": "image-a", "caption": "MateBook A 流畅建模"}]
            elif key in {"selling_points", "tags"}:
                task["draft"][key] = ["MateBook A 流畅建模"]
            else:
                task["draft"][key] = "MateBook A 流畅建模"
            with self.subTest(key=key):
                self.assertTrue(any(c["location"].startswith(key) for c in blocked(task)))

    def test_semantic_issues_remain_even_if_fact_id_exists(self):
        task = task_with_evidence()
        issue = {"quote": "屏幕为14英寸", "location": "body", "reason": "该句配置范围不正确", "fact_id": "screen-a"}
        result = review_recommendation_claims(task, {"passed": False, "issues": [issue]})
        self.assertTrue(any(c["category"] == "推荐语义依据" and c["quote"] == issue["quote"] for c in result["checks"]))

    def test_actual_final_A_port_benefit_records_related_source_without_claiming_entailment(self):
        task = task_with_evidence('带HDMI和两个USB-A，接投影、U盘少转接。')
        task['facts'][0].update(id='ports-a', category='接口',
            excerpt='USB-C 接口 × 1（全功能）\nUSB3.2 Gen1 × 2\nHDMI × 1\n3.5 mm 耳机和麦克风接口 × 1',
            evidence_ref_ids=['ev-ports-a'])
        task['evidence_refs'] = [{'id':'ev-ports-a','fact_id':'ports-a','document_id':'doc-a','product_id':'a'}]
        task['draft']['claim_support'] = [{'quote':task['draft']['body'],'fact_ids':['ports-a'],'status':'supported'}]
        result = review_recommendation_claims(task, {'passed':True,'issues':[]})
        claim = next(c for c in result['claim_support'] if c['kind']=='interface_statement')
        self.assertEqual(claim['quote'], task['draft']['body'].rstrip('。'))
        self.assertEqual(claim['status'], 'requires_semantic_review')
        self.assertEqual(claim['support_relation'], 'relevance_only')
        self.assertEqual(claim['fact_ids'], [])
        self.assertEqual(claim['candidate_fact_ids'], ['ports-a'])
        self.assertEqual(claim['candidate_evidence_ref_ids'], ['ev-ports-a'])
        self.assertEqual(result['checks'], [])  # Mapping does not add a new global gate.

    def test_port_candidates_do_not_borrow_other_product_or_invalid_original(self):
        task = task_with_evidence('MateBook A 带HDMI接口，连接投影少转接。')
        task['facts'].extend([
            {'id':'ports-b','product_id':'b','model':'MateBook B','document_id':'doc-b',
             'category':'接口','excerpt':'HDMI接口','verified':True,'evidence_ref_ids':['ev-ports-b']},
            {'id':'ports-a-unlocated','product_id':'a','model':'MateBook A',
             'category':'接口','excerpt':'HDMI接口','verified':True},
        ])
        task['evidence_refs'] = [{'id':'ev-ports-b','fact_id':'ports-b','product_id':'b','document_id':'doc-b'}]
        claim = next(c for c in review_recommendation_claims(task)['claim_support'] if c['kind']=='interface_statement')
        self.assertEqual(claim['product_ids'], ['a'])
        self.assertEqual(claim['candidate_fact_ids'], [])
        self.assertEqual(claim['candidate_evidence_ref_ids'], [])
        self.assertEqual(claim['fact_ids'], [])
        self.assertEqual(claim['status'], 'requires_semantic_review')

    def test_literal_port_original_has_backend_supported_mapping(self):
        task = task_with_evidence('MateBook A HDMI 接口 × 1。')
        task['facts'][0].update(id='ports-a', category='接口', excerpt='HDMI 接口 × 1',
                                evidence_ref_ids=['ev-ports-a','model-invented-ref'])
        task['evidence_refs'] = [{'id':'ev-ports-a','fact_id':'ports-a','document_id':'doc-a','product_id':'a'}]
        claim = next(c for c in review_recommendation_claims(task)['claim_support'] if c['kind']=='interface_statement')
        self.assertEqual(claim['status'], 'supported')
        self.assertEqual(claim['support_relation'], 'literal_original')
        self.assertEqual(claim['fact_ids'], ['ports-a'])
        self.assertEqual(claim['evidence_ref_ids'], ['ev-ports-a'])
        self.assertEqual(claim['candidate_evidence_ref_ids'], ['ev-ports-a'])
        task['draft']['body'] = 'MateBook A HDMI 接口 × 1，接投影无需转接。'
        claim = next(c for c in review_recommendation_claims(task)['claim_support'] if c['kind']=='interface_statement')
        self.assertEqual(claim['status'], 'requires_semantic_review')
        self.assertEqual(claim['fact_ids'], [])
        self.assertEqual(claim['candidate_fact_ids'], ['ports-a'])

    def test_packaged_USB_charger_is_not_a_body_port_candidate_source(self):
        task = task_with_evidence('MateBook A 机身有USB-C和HDMI接口。')
        task['facts'][0].update(id='ports-a', category='接口', excerpt='USB-C接口 × 1，HDMI × 1',
                                evidence_ref_ids=['ev-ports-a'])
        task['facts'].extend([
            {'id':'package-a','product_id':'a','model':'MateBook A','document_id':'doc-package-a',
             'category':'包装清单','excerpt':'PC × 1，USB-C 电源适配器 × 1','verified':True,
             'evidence_ref_ids':['ev-package-a']},
            {'id':'accessory-a','product_id':'a','model':'MateBook A','document_id':'doc-accessory-a',
             'category':'其他','excerpt':'USB-C 电源适配器 × 1','verified':True},
        ])
        task['evidence_refs'] = [
            {'id':'ev-ports-a','fact_id':'ports-a','document_id':'doc-a','product_id':'a'},
            {'id':'ev-package-a','fact_id':'package-a','document_id':'doc-package-a','product_id':'a'},
        ]
        claim = next(c for c in review_recommendation_claims(task)['claim_support'] if c['kind']=='interface_statement')
        self.assertEqual(claim['candidate_fact_ids'], ['ports-a'])
        self.assertEqual(claim['candidate_evidence_ref_ids'], ['ev-ports-a'])
        self.assertEqual(claim['status'], 'requires_semantic_review')
        task['draft']['body'] = 'MateBook A 包装内含USB-C电源适配器。'
        claim = next(c for c in review_recommendation_claims(task)['claim_support'] if c['kind']=='interface_statement')
        self.assertIn('package-a', claim['candidate_fact_ids'])
        self.assertIn('ev-package-a', claim['candidate_evidence_ref_ids'])

    def test_final_edit_is_rechecked_instead_of_reusing_old_support(self):
        task = task_with_evidence()
        task["claim_support"] = review_recommendation_claims(task)["claim_support"]
        task["draft"]["body"] = "MateBook A 屏幕为16英寸。"
        self.assertTrue(blocked(task))

    def test_legacy_task_is_untouched_and_existing_validate_contract_is_preserved(self):
        task = task_with_evidence()
        for key in ("task_context", "candidates", "evidence_refs"):
            task.pop(key)
        before = deepcopy(task)
        result = review_recommendation_claims(task)
        self.assertEqual(result, {"claim_support": [], "checks": []})
        self.assertEqual(task, before)
        original = validate(task["draft"], task["facts"], task["assets"], task["quotes"], "moments")
        self.assertIsInstance(original, list)
        self.assertTrue(any(c["category"] == "价格" for c in original))

    def test_legacy_snapshot_without_original_locator_is_warning_and_not_new_gate(self):
        task = task_with_evidence()
        task['requirement_events'] = [{'kind': 'legacy_snapshot', 'id': 'legacy-1'}]
        task['facts'][0].pop('document_id')
        result = review_recommendation_claims(task)
        self.assertEqual(blocked(task), [])
        self.assertEqual(result['claim_support'][0]['status'], 'legacy_unlocated')
        self.assertEqual(result['checks'][0]['status'], 'warning')
        task['requirement_events'].append({'kind': 'message', 'id': 'event-1'})
        self.assertTrue(blocked(task))


if __name__ == "__main__":
    unittest.main()
