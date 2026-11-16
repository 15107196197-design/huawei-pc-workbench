from __future__ import annotations

import asyncio
import json
import re

from .knowledge import KnowledgeError, knowledge
from .policies import PLATFORMS, SCENARIOS, SYSTEM_PROMPT, platform, scenario
from .providers import ProviderError, json_chat, search_prices
from .settings import load_settings
from .store import get_task, now, save_task
from .validation import reconcile_literal_evidence, validate, review_recommendation_claims
from .task_context import (P1, Understanding, PRODUCT_RE, apply_brief_save, apply_message, apply_model_understanding, ensure_context, key_question, digest)
from .matching import DraftResponse, ReviewResponse, P4, P5, prepare_matching, supplement_evidence, assess, default_plan, structured_chat

LOCKS: dict[str, asyncio.Lock] = {}


def task_lock(task_id: str) -> asyncio.Lock:
    return LOCKS.setdefault(task_id, asyncio.Lock())


def parse_brief_rules(message: str, brief: dict) -> dict:
    b = dict(brief)
    for p in PLATFORMS:
        if p["name"] in message or (p["id"] == "wechat" and "微信文章" in message) or (p["id"] == "moments" and "朋友圈" in message):
            b["platform"] = p["id"]
    scenario_words = {"school": ["开学", "大学", "学生"], "office": ["职场", "办公", "差旅"],
                      "creator": ["剪辑", "摄影", "创作者", "设计师"], "family": ["家庭", "家用", "父母"],
                      "business": ["企业采购", "团队采购", "批量采购"], "store": ["到店", "门店到访"],
                      "launch": ["新品", "首发"], "holiday": ["节日", "送礼", "中秋", "春节"]}
    for key, words in scenario_words.items():
        if any(w in message for w in words):
            b["scenario"] = key
            break
    audiences = ["工科新生", "工科学生", "大学新生", "大学生", "家长", "商务人士", "移动办公者", "设计师", "摄影师", "视频创作者", "家庭用户", "中小企业", "附近顾客", "职场新人", "学生", "上班族"]
    audience = [w for w in audiences if w in message]
    if audience:
        b["audience"] = "、".join(audience[:3])
    elif re.search(r"(?:人群|受众|面向|给)[：: ]?([^，。；\n]{2,24})", message):
        b["audience"] = re.search(r"(?:人群|受众|面向|给)[：: ]?([^，。；\n]{2,24})", message).group(1)
    if re.search(r"软文|文案|宣传|推荐|介绍|咨询|到店|海报", message):
        b["goal"] = "到店体验与咨询" if "到店" in message else "帮助理解产品并形成选购建议"
    budget = re.search(r"(?:预算|价位|不超过|以内)[约为是：: ]*(\d+(?:\.\d+)?\s*[万千kK]?)", message)
    if budget:
        b["budget"] = budget.group(1)
    if "杭州" in message:
        b["region"] = "杭州"
    product = PRODUCT_RE.search(message)
    if product:
        b["product"] = product.group(0).strip()
    if re.search(r"还没选|未指定|帮我选|推荐几|推荐产品", message):
        b["product"] = ""
    software = re.findall(r"Windows|HarmonyOS|鸿蒙|Office|WPS|Photoshop|Premiere|AutoCAD|CAD|剪映|文档处理|办公文档|编程|剪辑", message, re.I)
    if software:
        b["software"] = "、".join(dict.fromkeys(software))
    for stage, words in {"初步了解": ["了解", "种草"], "比较选型": ["比较", "对比", "选购", "推荐"], "准备购买": ["下单", "准备买", "到手价"]}.items():
        if any(w in message for w in words): b["purchase_stage"] = stage
    return b


async def parse_brief(message: str, brief: dict) -> dict:
    # Schema-checked interpretation is merged into task_context in chat_task.
    return parse_brief_rules(message, brief)


def missing_questions(brief: dict) -> list[str]:
    # Compatibility API: model, budget and software are never universal required fields.
    if not any(brief.get(k) for k in ['audience','scenario','goal','product','software']):
        return ["这条内容主要给谁看，或者希望电脑帮助他们完成什么事情？"]
    return []


async def retrieve_task(task: dict, query: str = "", refresh: bool = False) -> dict:
    ensure_context(task)
    task['stage'] = 'ima资料与图片检索'
    task = save_task(task, version=False)
    if query:
        # A submitted retrieval query is data, never a new selected product.
        task.setdefault('understanding_decision', {})['query_plan'] = [query[:300]]
    try:
        task = await prepare_matching(task, knowledge, json_chat, bool(load_settings()['deepseek_api_key']), refresh)
    except (ProviderError,ValueError,TimeoutError):
        # Partial successful retrieval survives an interpretation/format failure.
        save_task(task,'保留已取得的原文与执行缺口',version=False)
        raise
    task['stage'] = '资料已检索'
    return save_task(task, '更新产品依据')


def rule_draft(task: dict, instruction: str = "") -> dict:
    b = dict(task["brief"])
    b["audience"] = b.get("audience") or "目标读者"
    p, sc = platform(b["platform"]), scenario(b.get("scenario", ""))
    facts = [f for f in task["facts"] if f.get("verified")]
    models = list(dict.fromkeys(f["model"] for f in facts))
    model = models[0] if models else b.get("product") or "华为PC"
    plan = task.get('selling_point_plan', {})
    planned_ids = [fid for point in plan.get('selling_points', []) for fid in point['fact_ids']]
    if planned_ids:
        selected = [f for fid in planned_ids for f in facts if f['id'] == fid]
        model = selected[0]['model'] if selected else model
    else:
        selected = [f for f in facts if f['model'] == model][:3]
    if p['id'] == 'moments': selected = selected[:1]
    if p['id'] == 'poster': selected = [f for f in selected if len(f['excerpt']) <= 95][:3]
    assets = [a for a in task["assets"] if a.get("verified") and a["model"] == model][:p["max_images"]]
    topic = {"school": "开学选电脑，先看学习任务怎么完成", "office": "从会议到差旅，把办公需求逐项看清", "creator": "选创作电脑，先把软件与素材流程说清", "family": "家庭换新，让每位使用者的需求都有位置", "business": "团队选电脑，从部署与使用要求开始", "store": "带上常用任务，到店实际体验", "launch": "认识新品，先看变化是否适合自己", "holiday": "送一台电脑之前，先了解收礼人的使用场景"}.get(sc["id"], "围绕真实任务，选择适合的电脑")
    snippets = [f"{f['category']}\n{f['excerpt']}" for f in selected]
    if p["id"] == "moments":
        body = (snippets[0] if snippets else "待补充已确认的产品事实。") + "\n\n具体销售配置与软件适配请先确认。"
        title, lead, cta, tags = model + "，到店看看是否适合你", sc["focus"], "欢迎私信说明需求，预约到店体验。", []
    elif p["id"] == "xiaohongshu":
        title, lead = topic, f"给{b['audience']}的一份选择清单：先对照自己的任务，再看{model}的已确认信息。"
        body = "\n\n".join(f"{i+1}｜{t}" for i, t in enumerate(snippets)) + "\n\n选之前再确认：具体配置、常用软件和当前报价。没有实测依据，不替你承诺使用效果。"
        cta, tags = "你最在意哪个使用环节？带着需求继续比较。", ["华为电脑", sc["name"], "电脑选购"]
    elif p["id"] == "poster":
        title, lead = topic, model
        # Keep factual qualifiers instead of truncating a specification mid-sentence.
        snippets = [s.replace("\n", "；") for s in snippets]
        body = "\n\n".join(snippets[:3]) or "了解具体配置，带上常用软件到店验证。"
        cta, tags = "咨询具体配置与活动条件，预约到店体验。", []
    else:
        title, lead = topic, f"对{b['audience']}来说，选电脑需要从实际问题出发。本次围绕{sc['focus']}，整理{model}的产品依据与待确认条件。"
        body = "\n\n".join(snippets) + "\n\n选购前的确认\n以上为知识库收录的官方规格摘录；不同销售配置可能存在差异。请核对具体SKU、系统及必用软件，不把屏幕、接口或处理器名称直接等同于实际任务表现。"
        cta, tags = "欢迎带上预算和常用任务咨询，进一步核对具体配置与当前报价。", []
    if instruction:
        # A rule template cannot claim to understand arbitrary editorial requests.
        lead += "（本次修改要求已记录；自由改写需接通文本模型。）"
    draft = {"title": title, "lead": lead, "body": body, "cta": cta, "tags": tags,
            "images": [{"id": a["id"], "caption": a["caption"], "position": "主视觉" if p["id"] == "poster" else f"第{i+1}段后"} for i, a in enumerate(assets)],
            "fact_ids": [f["id"] for f in selected], "generator": "rules", "disclosure": "广告｜AI辅助工作台规则草稿，发布前核验"}
    if p["id"] == "poster":
        draft["selling_points"] = snippets[:3]
    return draft


async def verify_task(task: dict) -> dict:
    semantic = None
    visual_checks = [c for c in task.get("checks", []) if c.get("category") == "视觉核验"] if (task.get("draft") or {}).get("poster_url") else []
    task.pop("semantic_review", None)
    if task.get("draft") and load_settings()["deepseek_api_key"]:
        semantic = await json_chat("""你是证据审校员，对draft实际陈述的产品事实与购买承诺进行逐项核对。
只用facts、quotes以及brief中的用户自述信息，不用模型记忆补证据。检查错型号、错误数字、改变事实含义的限定遗漏、虚构体验、优惠资格、无依据承诺。
任务是判断已写陈述是否被支持，不要求覆盖所有facts；未选用的事实、未写出的额外功能或未展开的参数，不构成错误。
严格区分不同部件，例如触控板和触摸屏；不能因某部件的事实没出现在正文里，就认定另一部件陈述错误。
只在删除限定会改变实际陈述的适用范围或含义时判错；没有声称具体功率时不要求额外列出全部功率参数。
预算是用户自述的任务条件，不是商家售价。明确写作预算不构成虚构价格。图片说明可使用已提供资产索引的画面描述，但不能从图推断未证明参数。
返回JSON {passed:bool,issues:[具体应修改的错误],notes:[可选建议]}。issues只列实际阻断问题，每条引用draft原句及对应证据；已通过的项目、可选补充和泛泛建议放notes。若无实际错误，passed=true且issues=[]。""" + P5, {"schema": ReviewResponse.model_json_schema(), "task_context": task.get("task_context"), "candidates": task.get("candidates", []), "selling_point_plan": task.get("selling_point_plan"), "evidence_refs": task.get("evidence_refs", []), "draft": task["draft"], "brief": task["brief"], "facts": task["facts"], "assets": [{"id": a["id"], "caption": a["caption"], "model": a["model"]} for a in task["assets"]], "quotes": task["quotes"]})
        try:ReviewResponse.model_validate(semantic)
        except ValueError as exc:raise ProviderError('审校返回不符合后端Schema，未认定通过') from exc
        semantic = reconcile_literal_evidence(semantic, task["draft"], task["facts"])
        task["semantic_review"] = semantic
    task["checks"] = validate(task.get("draft"), task["facts"], task["assets"], task["quotes"], task["brief"]["platform"], semantic)
    recommendation_review = review_recommendation_claims(task, semantic)
    task['claim_support'] = recommendation_review['claim_support']
    if task.get('draft') is not None:
        task['draft']['claim_support'] = recommendation_review['claim_support']
    task['checks'].extend(recommendation_review['checks'])
    if task.get('writing_reported_gaps'):
        task['checks'].append({'category':'写作依据边界','status':'warning','message':'写作模型另列未确定角度；已对最终实际陈述独立核验，不将未写角度作为统一门槛'})
    task["checks"].extend(visual_checks)
    for warning in task.get("retrieval_warnings", []):
        task["checks"].append({"category": "资料", "status": "warning", "message": warning})
    if task.get("needs_regeneration"):
        task["checks"].append({"category": "任务需求", "status": "blocked", "message": "任务需求已修改，请重新生成后交付"})
    task["status"] = "blocked" if any(c["status"] == "blocked" for c in task["checks"]) else "draft"
    task["stage"] = "核验待处理" if task["status"] == "blocked" else "可预览与修改"
    return task


def generation_facts(task: dict) -> list[dict]:
    planned = {fid for p in task.get('selling_point_plan', {}).get('selling_points', []) for fid in p['fact_ids']}
    return [f for f in task['facts'] if f.get('verified') and (f['id'] in planned if planned else True)]


def decision_payload(task: dict) -> dict:
    plan=task.get('selling_point_plan') or {}
    products={p['product_ref'] for p in plan.get('selling_points',[])}
    return {'task_context':task.get('task_context'),
            'candidates':[c for c in task.get('candidates',[]) if not products or c['product_ref'] in products],
            'selling_point_plan':plan,
            'evidence_refs':[r for r in task.get('evidence_refs',[]) if not products or r.get('product_ref') in products]}


async def understand_submitted(task: dict) -> dict:
    ensure_context(task)
    events=task.get('requirement_events', [])
    event=next((e for e in reversed(events) if e['kind']!='legacy_snapshot'),None)
    if not event or event['id'] in task.get('understood_events', []): return task
    if load_settings()['deepseek_api_key']:
        try:
            interpreted = await structured_chat(json_chat,P1,{
                'submitted_event': event, 'history': task['messages'][-10:], 'brief': task['brief'],
                'task_context': task['task_context'], 'platform': task['brief']['platform'],
                'candidates': task.get('candidates', []), 'evidence_gaps': task.get('evidence_gaps', [])},Understanding,task,'需求理解')
            response=interpreted.model_dump()
            apply_model_understanding(task, response, event)
        except (ValueError, ProviderError, TimeoutError) as exc:
            task['understanding_warning'] = ('需求模型接口未完成：'+str(exc) if isinstance(exc,ProviderError) else '需求模型未返回有效结构')+'；已按明确原文保留任务并继续受限查询'
            task['understanding_error_kind']=type(exc).__name__
    task.setdefault('understood_events', []).append(event['id'])
    return task


async def generate_task(task: dict, instruction: str = "", refresh: bool = False) -> dict:
    ensure_context(task)
    if task['task_context'].get('platform') != task['brief']['platform']:
        old = dict(task['brief'], platform=task['task_context']['platform'])
        apply_brief_save(task, old)
    task = await understand_submitted(task)
    decision=task.get('understanding_decision', {})
    latest_event=next((e for e in reversed(task.get('requirement_events', [])) if e['kind']!='legacy_snapshot'),{})
    if decision.get('next_action')=='stop' and re.search(r'停止|取消|不要生成|先别生成',str(latest_event.get('data',''))):
        task['status'],task['stage']='ready','任务已按要求停止'
        return save_task(task,'保留需求，停止生成')
    question = key_question(task)
    if question:
        task['status'], task['stage'] = 'needs_input', '需求理解'
        if not task.get('messages') or task['messages'][-1].get('content') != question:
            task['messages'].append({'role': 'assistant', 'content': '还需要补充：' + question})
        return save_task(task, '确认关键任务')
    task["status"], task["stage"], task["error"] = "generating", "检索依据", ""
    task.pop("repair_record", None)
    task = save_task(task, version=False)
    try:
        if (not task.get('selling_point_plan') or task.get('matching_key') != task['task_context']['matching_key'] or refresh):
            task = await retrieve_task(task, refresh=refresh)
        elif task.get('facts'):
            # Cached decisions still contain public/model-facing prose. Enter the
            # existing cache guard before writing; it reuses facts without queries.
            task = await prepare_matching(task, knowledge, json_chat, use_model=False)
        clarification=task.get('pending_clarification')
        if clarification and clarification.get('question') and clarification.get('key') not in task.get('asked_clarifications',[]):
            task['status'],task['stage']='needs_input','确认影响选择的关键差异'
            task.setdefault('asked_clarifications',[]).append(clarification['key'])
            task['messages'].append({'role':'assistant','content':clarification['question']})
            return save_task(task,'单问关键差异')
        if task.get('selling_point_plan', {}).get('next_action') in {'stop','read'} or not task.get('selling_point_plan', {}).get('selling_points') or not task.get('facts'):
            task['status'], task['stage'] = 'needs_evidence', '依据缺口'
            gaps = task.get('evidence_gaps', [])
            descriptions = [x.get('message', str(x)) if isinstance(x, dict) else str(x) for x in gaps]
            message = '已理解任务，但当前授权资料不足以支持确定的产品推荐。' + ('；'.join(dict.fromkeys(descriptions))[:700] if descriptions else '需要补充对应产品原文依据；可以先保留任务方向和待核实项。')
            task['messages'].append({'role': 'assistant', 'content': message})
            return save_task(task, '保存条件方向与证据缺口')
        task["stage"] = "平台内容生成"
        task = save_task(task, version=False)
        if load_settings()["deepseek_api_key"]:
            writing_scope_instruction=""
            for writing_attempt in range(2):
                selected_facts = generation_facts(task)
                draft = await json_chat(SYSTEM_PROMPT + P4, {**decision_payload(task), 'schema': DraftResponse.model_json_schema(),
                    "brief": task["brief"], "platform": platform(task["brief"]["platform"]),
                    "scene": scenario(task["brief"].get("scenario", "")), "facts": selected_facts,
                    "assets": [{k: a[k] for k in ["id", "name", "model", "verified", "caption"]} for a in task["assets"]],
                    "quotes": task["quotes"], "previous_draft": task.get("draft") if instruction else None,
                    "instruction": ("围绕给定事实重新组织内容，最多三个主要卖点，不要保留未选用的参数。" + instruction + writing_scope_instruction)})
                complete_draft=all(isinstance(draft.get(k),str) and draft.get(k).strip() for k in ['title','body']) and bool(draft.get('fact_ids'))
                if draft.get('missing_evidence') and complete_draft:
                    # The writer may list evidence for angles it deliberately did not claim.
                    # A full draft goes through independent final-text checks, never a self-issued pass.
                    task['writing_reported_gaps']=draft['missing_evidence']
                if draft.get('missing_evidence') and not complete_draft:
                    missing=draft['missing_evidence']
                    if not isinstance(missing,list) or not all(isinstance(x,str) for x in missing):raise ProviderError('写作缺口不符合后端Schema')
                    target_refs={p['product_ref'] for p in task.get('selling_point_plan',{}).get('selling_points',[])}
                    relevant_fits=[a for candidate in task.get('candidates',[]) if candidate['product_ref'] in target_refs for a in candidate['fit_assessments']]
                    proven={a['requirement_id'] for a in relevant_fits if a['status']=='satisfied'}
                    unresolved={a['requirement_id'] for a in relevant_fits if a['status'] in {'unknown','conflict'}}
                    hard_tasks=[r for r in task['task_context']['conditions'] if r['strength']=='hard' and r['field'] in {'use_tasks','software','system','workload'} and (r['id'] not in proven or r['id'] in unresolved)]
                    if writing_attempt==0:
                        changed=await supplement_evidence(task,knowledge,queries=missing)
                        if changed:
                            previous_plan=task['selling_point_plan']
                            assess(task)
                            from .matching import validate_plan,SellingPlan
                            task['selling_point_plan']=validate_plan(task,{k:v for k,v in previous_plan.items() if k in SellingPlan.model_fields})
                        if not hard_tasks:
                            writing_scope_instruction='本次不要求证明具体软件兼容或编程建模性能。以下缺口不是本次条件文案的固定前提：'+'；'.join(missing)+'。删除依赖缺口的结论，只围绕selling_point_plan中已核对的规格与可比较价值写有实际信息的条件内容；不承诺确定适配，不写通篇待确认清单，按原平台篇幅与原图规则交付。'
                            task['writing_scope_decision']={'excluded_dependencies':missing,'reason':'未知软需求不阻断已核实规格的条件内容'}
                        if changed or not hard_tasks:continue
                    task['status'],task['stage']='needs_evidence','写作依据缺口'
                    task['evidence_gaps'].extend({'kind':'evidence_missing','message':x} for x in missing)
                    task['messages'].append({'role':'assistant','content':'当前材料仍缺少：'+'；'.join(missing)+'。已保留任务和条件方向。'})
                    return save_task(task,'保存写作依据缺口')
                try:DraftResponse.model_validate(draft)
                except ValueError as exc:raise ProviderError('写作返回不符合后端draft Schema，未保存成品') from exc
                break
            draft["generator"] = "deepseek"
            draft["disclosure"] = "广告｜AI辅助生成，发布前核验"
            task["mode"] = "deepseek"
        else:
            draft = rule_draft(task, instruction)
            task["mode"] = "rules"
        for key in ["title", "lead", "body", "cta"]:
            if not isinstance(draft.get(key, ""), str):
                raise ProviderError("模型返回的内容字段类型不正确，未保存成品")
        for key in ["tags", "images", "fact_ids"]:
            if not isinstance(draft.get(key, []), list):
                raise ProviderError("模型返回的引用字段类型不正确，未保存成品")
            draft.setdefault(key, [])
        draft['context_version'] = task['task_context']['version']
        draft['evidence_version'] = task.get('selling_point_plan', {}).get('evidence_version', digest(task['facts']))
        task['draft'] = draft
        task["needs_regeneration"] = False
        task["stage"] = "事实与合规核验"
        task = await verify_task(task)
        if task["status"] == "blocked" and load_settings()["deepseek_api_key"]:
            issues = [c["message"] for c in task["checks"] if c["status"] == "blocked"]
            task["repair_record"] = {"attempts": 1, "initial_issues": issues}
            revised = await json_chat(SYSTEM_PROMPT + P4, {**decision_payload(task), "schema": DraftResponse.model_json_schema(), "brief": task["brief"], "platform": platform(task["brief"]["platform"]),
                "facts": generation_facts(task), "assets": [{k: a[k] for k in ["id", "name", "model", "verified", "caption"]} for a in task["assets"]],
                "quotes": task["quotes"], "previous_draft": task["draft"], "instruction": "根据以下核验问题修订，只修正或删除无依据内容，不新增参数；保留平台格式。", "issues": issues})
            try:DraftResponse.model_validate(revised)
            except ValueError as exc:raise ProviderError('修订返回不符合后端draft Schema，未采信成品') from exc
            revised["generator"], revised["disclosure"] = "deepseek", "广告｜AI辅助生成，发布前核验"
            if not all(isinstance(revised.get(k, ""), str) for k in ["title", "lead", "body", "cta"]) or not all(isinstance(revised.get(k, []), list) for k in ["tags", "images", "fact_ids"]):
                raise ProviderError("修订结果字段类型错误，未通过交付核验")
            revised['context_version'] = task['task_context']['version']
            revised['evidence_version'] = task.get('selling_point_plan', {}).get('evidence_version', digest(task['facts']))
            task["draft"] = revised
            task = await verify_task(task)
        if task["brief"]["platform"] == "poster" and task["status"] != "blocked":
            from .media import compose_poster
            task["draft"]["poster_url"] = await compose_poster(task)
        task["messages"].append({"role": "assistant", "content": "已生成" + platform(task["brief"]["platform"])["name"] + ("规则草稿。请查看依据和核验提示；接通文本模型后可自由改写。" if draft["generator"] == "rules" else "内容。请查看成品与逐项核验结果。")})
        return save_task(task, "生成／修改内容", expected_revision=task["revision"])
    except (KnowledgeError, ProviderError, ValueError, TimeoutError) as e:
        latest = get_task(task['id'])
        if isinstance(e,ValueError) and '内容已被更新' in str(e):return latest
        if latest.get('task_context', {}).get('version') != task.get('task_context', {}).get('version'):
            return latest
        task = latest
        task["status"], task["stage"], task["error"] = "error", "任务未完成", str(e)
        task["messages"].append({"role": "assistant", "content": str(e)})
        return save_task(task, "记录执行失败")


async def chat_task(task: dict, message: str) -> dict:
    task['messages'].append({'role': 'user', 'content': message[:12000]})
    if message.startswith('[生成当前任务]'):
        return await generate_task(task, message.removeprefix('[生成当前任务]'))
    old_key = ensure_context(task)['matching_key']
    old_brief = dict(task['brief'])
    parsed = await parse_brief(message, task['brief'])
    event = apply_message(task, message, parsed)
    task = await understand_submitted(task)
    if re.search(r'停止|取消|不要生成|先别生成|先停',message):
        task['status'],task['stage']='ready','任务已按要求停止'
        task['messages'].append({'role':'assistant','content':'已保留本次需求，暂不生成。'})
        return save_task(task,'保留已提交需求，停止生成')
    if old_key != task['task_context']['matching_key']:
        task['candidates'], task['fit_assessments'], task['selling_point_plan'] = [], [], {}
        task['needs_regeneration'] = bool(task.get('draft'))
    if old_brief.get('product') != task['brief'].get('product') or old_brief.get('software') != task['brief'].get('software'):
        task['facts'], task['assets'], task['evidence'] = [], [], []
    if task['title'] == '新的内容任务': task['title'] = message[:36]
    task = save_task(task, '更新已提交的任务理解', version=False)
    return await generate_task(task, message if task.get('draft') else '')
