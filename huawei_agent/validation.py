from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .policies import platform

FORBIDDEN = ["全网最低", "全国最低", "百分之百", "100%保证", "绝对安全", "永不卡顿", "永久不卡", "行业第一", "全球第一", "最强", "最有效", "最适合", "最佳", "零风险"]


def review_recommendation_claims(task: dict, semantic: dict | None = None) -> dict:
    """Independently inspect the delivered text; model-supplied citations prove nothing.

    This is a deliberately bounded supplement to the existing reviewer, not a
    general entailment engine. Exact specifications, identity, qualifiers and
    high-risk capability promises are checked here; the semantic reviewer still
    judges other paraphrases. Old tasks without matching data retain validate's
    existing behavior until they are understood/retrieved by the new workflow.
    """
    if not any(task.get(k) for k in ("task_context", "candidates", "selling_point_plan", "evidence_refs")):
        return {"claim_support": [], "checks": []}
    draft = task.get("draft") or {}
    if not draft:
        return {"claim_support": [], "checks": []}
    checks, support = [], []
    facts = [f for f in task.get("facts", []) if isinstance(f, dict)]
    refs = task.get("evidence_refs") or []
    if isinstance(refs, dict):
        refs = list(refs.values())
    refs = [r for r in refs if isinstance(r, dict)]
    ref_map = {str(r.get("id") or r.get("fact_id")): r for r in refs}
    events = task.get('requirement_events') or []
    legacy_unlocated = bool(events and all(e.get('kind') == 'legacy_snapshot' for e in events) and not refs and
                            not any(f.get('document_id') or f.get('document_ref') or f.get('locator') for f in facts))
    if legacy_unlocated:
        # Existing drafts may predate source locators. Keep their established
        # validate/semantic behavior rather than inventing locators or imposing
        # a new blanket delivery gate. New retrieval restores strict checks.
        claims = [{"location": key, "quote": str(draft[key]), "status": "legacy_unlocated",
                   "fact_ids": [], "evidence_ref_ids": [], "source_state": "legacy_unknown"}
                  for key in ('title', 'lead', 'body', 'cta') if draft.get(key)]
        return {"claim_support": claims, "checks": [{"category": "推荐与卖点依据", "status": "warning",
                "message": "旧稿未保存原文定位；保留原有核验结果与来源状态，重新取证后使用新增证据检查。"}]}
    candidates = task.get("candidates") or []
    if isinstance(candidates, dict):
        candidates = list(candidates.values())
    candidates = [c for c in candidates if isinstance(c, dict)]

    def norm(value):
        return re.sub(r"[\s（）()_－-]", "", str(value)).lower()

    def identity(value):
        p = value.get("product_ref")
        if isinstance(p, dict):
            return str(p.get("product_id") or p.get("id") or p.get("model") or "")
        return str(value.get("product_id") or p or value.get("model") or value.get("name") or "")

    # Resolve only backend-known identities. A name in the final prose is never
    # itself a new product reference.
    aliases, models = {}, {}
    for record in facts + refs + candidates:
        pid = identity(record)
        if not pid:
            continue
        names = [record.get("model"), record.get("canonical_model"), record.get("name")]
        if isinstance(record.get("product_ref"), dict):
            names += [record["product_ref"].get("model"), record["product_ref"].get("name")]
        names += record.get("aliases", []) if isinstance(record.get("aliases"), list) else []
        for name in names:
            if name:
                aliases[norm(name)] = pid
                models[pid] = str(name)
        aliases.setdefault(norm(pid), pid)
    context = task.get("task_context") or {}
    intention = context.get("product_intent") or {}
    selected = intention.get("selected") or intention.get("selected_products") or []
    if isinstance(selected, str):
        selected = [selected]
    defaults = []
    for value in selected:
        key = identity(value) if isinstance(value, dict) else str(value)
        pid = aliases.get(norm(key), key if key in models else "")
        if pid:
            defaults.append(pid)
    if not defaults and len(models) == 1:
        defaults = list(models)

    def named(text):
        text = norm(text)
        matches = [(text.find(name), -len(name), pid) for name, pid in aliases.items()
                   if len(name) > 2 and name in text]
        # The longest name at a position preserves system/year/configuration.
        found, occupied = [], []
        for pos, neglen, pid in sorted(matches, key=lambda x: (x[1], x[0])):
            end = pos - neglen
            if any(pos < b and end > a for a, b in occupied):
                continue
            occupied.append((pos, end)); found.append((pos, pid))
        return sorted(found)

    if not defaults:
        planned = {identity(point) for point in (task.get('selling_point_plan') or {}).get('selling_points', [])
                   if isinstance(point, dict) and identity(point)}
        if len(planned) == 1:
            pid = aliases.get(norm(next(iter(planned))))
            if pid:
                defaults = [pid]
    if not defaults:
        heading_products = {pid for _, pid in named(' '.join(str(draft.get(k) or '') for k in ('title', 'lead')))}
        if len(heading_products) == 1:
            defaults = list(heading_products)

    def product_at(text, token=""):
        found = named(text)
        if found:
            position = norm(text).find(norm(token)) if token else -1
            before = [pid for pos, pid in found if pos <= position]
            if before:
                return [before[-1]]
            return list(dict.fromkeys(pid for _, pid in found))
        return list(dict.fromkeys(defaults))

    def source_text(fact):
        # claim may include a model-generated paraphrase. Original excerpt is
        # mandatory for new matching evidence, with a backend source locator.
        return str(fact.get("excerpt") or fact.get("source_excerpt") or "")

    def eligible(fact):
        ref = ref_map.get(str(fact.get("id"))) or next(
            (r for r in refs if r.get("fact_id") == fact.get("id")), {})
        locator = fact.get("document_id") or fact.get('document_ref') or ref.get("document_id") or ref.get('document_ref')
        invalid = any(value.get("conflict") is True or value.get("has_conflict") is True or
                      value.get("historical_snapshot") is True or value.get("historical_only") is True or value.get('historical') is True or
                      value.get("status") in {"conflict", "invalid", "historical"} for value in (fact, ref))
        return bool(fact.get("verified") is True and identity(fact) and locator and source_text(fact) and not invalid)

    usable = [f for f in facts if eligible(f)]
    units = r"GHz|GB|TB|kg|Wh|nits|PPI|mm|Hz|英寸|小时|千克|克|线程|核|%"
    numeric = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(" + units + r")", re.I)
    screen_numeric = re.compile(r"(?<![\d.])\d{1,2}\s*[:：]\s*\d{1,2}(?!\d)|(?<!\d)\d{3,5}\s*[×xX✕]\s*\d{3,5}(?!\d)")
    screen_terms = r"屏幕|显示屏|长屏|触控屏|宽高比|屏比|比例|分辨率|像素|OLED|LCD"

    def spec_key(value):
        return norm(value).replace('：', ':').replace('x', '×').replace('✕', '×')

    def specification_matches(text, category=''):
        result = list(numeric.finditer(text))
        for match in screen_numeric.finditer(text):
            before, after = text[max(0,match.start()-16):match.start()], text[match.end():match.end()+16]
            local = before + match.group(0) + after
            if not re.search(screen_terms, category + local, re.I):
                continue
            if ':' in spec_key(match.group(0)):
                # A nearby display mention must not turn a meeting time into
                # an aspect-ratio claim. This adds only display number shapes.
                if re.search(r"时间|上午|下午|晚上|早上|今天|明天|将在|定于",before) or re.match(r"\s*(?:开始|结束|到店|发布|见面|上线)",after):
                    continue
            result.append(match)
        return sorted(result,key=lambda match:match.start())
    performance = re.compile(
        r"流畅(?:运行|使用|完成|应对)?|轻松(?:运行|胜任|应对|完成)|专业渲染|"
        r"(?:满足|胜任|保证|保障|支持|兼容)[^，。；;！？\n]{0,24}"
        r"(?:建模|渲染|本地(?:AI|大模型)|AutoCAD|SolidWorks|Revit|MATLAB|Blender|\.exe|Windows软件)|"
        r"(?:建模|渲染|本地(?:AI|大模型))[^，。；;！？\n]{0,16}(?:有保证|没问题|性能保障)", re.I)
    # Softer wording can still assert software/workload suitability. An OS name
    # or processor specification does not entail "便于对接课程软件" either.
    software_task = r"(?:软件|应用|程序|编程|建模|渲染|课程任务|AutoCAD|SolidWorks|Revit|MATLAB|Blender|WPS|Office)"
    software_suitability = re.compile(
        r"(?:便于|方便|更方便|更便于)(?:对接|使用|运行|安装|适配|兼容|接入)[^，。；;！？\n]{0,24}" + software_task +
        r"|(?:适合|适用于|胜任|满足|支持|兼容)[^，。；;！？\n]{0,24}" + software_task +
        r"|(?:通用|广泛兼容)[^，。；;！？\n]{0,12}(?:软件|应用|程序)(?:路线|生态|环境|平台)?"
        r"|(?:软件|应用|程序)(?:适配|兼容性?)[^，。；;！？\n]{0,8}(?:更广|广泛|更好|更方便|有保障|没问题)", re.I)
    budget_claim = re.compile(r"符合(?:你的|您的)?预算|(?:完全|肯定)?在预算内|不超(?:出)?预算|预算(?:完全)?够|预算匹配")
    recommendation = re.compile(r"推荐(?:选|购买|入手|这|给)?|适合|满足(?:你的|您的|工科|学习)|放心(?:买|选|用)|直接(?:买|选|入手)")
    caveat = re.compile(r"候选|值得(?:比较|考虑)|待(?:核实|确认|验证)|尚待|尚无|未(?:知|核实|确认|验证)|不能(?:直接)?(?:证明|保证|确认|认定|推断|视为)|不(?:代表|等于|保证)|仍需|需(?:要)?(?:确认|核实|验证)|无法(?:确认|证明|保证)|仅凭.*不能|是否(?:适合|兼容|支持|满足|便于|方便)|能否")
    interface_terms = re.compile(r"HDMI|USB(?:[-－ ]?[ABC])?|Type[-－ ]?C|Thunderbolt|接口|端口", re.I)
    interface_names = re.compile(r"HDMI|USB|Type[-－ ]?C|Thunderbolt", re.I)

    def qualification_scope(text, token):
        """Keep qualifiers with their attribute, not every number in a section."""
        if not token:
            return text
        groups = [group for group in re.split(r"[。；;\n]", text) if spec_key(token) in spec_key(group)]
        scoped = []
        for group in groups:
            parts = re.split(r"[，,、]", group)
            for i, part in enumerate(parts):
                if spec_key(token) not in spec_key(part):
                    continue
                # A trailing condition-only clause qualifies the preceding
                # specification ("10小时，实验室测试条件下"). A clause about
                # another numeric attribute never does.
                relevant = [part]
                for neighbor in parts[i+1:i+2]:
                    if not numeric.search(neighbor) and re.search(r"约|最高|部分|可选|测试|实验室|条件|仅", neighbor):
                        relevant.append(neighbor)
                scoped.append('，'.join(relevant))
        return '；'.join(scoped) or text

    def qualified(fact, sentence, token=""):
        full_original = source_text(fact)
        # Rendering the complete original excerpt preserves its own boundaries.
        if norm(full_original) in norm(sentence):
            return True
        original = qualification_scope(full_original, token)
        target = qualification_scope(sentence, token)
        rules = [(r"(?:约|大约|近似)", r"约|大约|近似"),
                 (r"最高|至高|最多|最大|长达", r"最高|至高|最多|最大|长达"),
                 (r"部分(?:版本|配置|机型)|指定(?:版本|配置|条件)|仅限|可选", r"部分|指定|仅限|可选"),
                 (r"测试条件|实验室|特定条件", r"测试条件|实验室|特定条件")]
        if any(re.search(required, original) and not re.search(retained, target) for required, retained in rules):
            return False
        for condition in re.findall(r"(?:仅|只在|限于)(Windows版?|鸿蒙版?|20\d{2}款?)", original, re.I):
            if norm(condition) not in norm(target):
                return False
        return True

    def nonassertion(text, match):
        # Keep the scope local: a distant "待核实" must not excuse an actual
        # promise elsewhere in the same sentence or another selling point.
        start, end = match.span()
        clause = re.split(r"[，,；;]|但是|不过|然而|但|却", text[max(0, start-24):min(len(text), end+24)])
        return any(caveat.search(part) for part in clause if match.group(0) in part)

    def numeric_nonassertion(text, match, surface):
        # Candidate/recommendation caveats concern task fit, not a fixed product
        # specification. Only a question or uncertainty about this actual value
        # can leave its numeric identity unasserted.
        before, after = text[:match.start()], text[match.end():]
        if re.search(r"(?:是否|是不是)(?:为|是|有|配备|采用)?\s*$|(?:可能|或许|尚不确定)(?:是|为|有)?\s*$", before):
            return True
        attribute = r"(?:内存|容量|存储|屏幕(?:比例)?|比例|分辨率|宽高比|重量|续航|频率|厚度|电量|规格|配置)?"
        if re.match(r"\s*(?:的)?" + attribute + r"(?:吗|么|呢)(?:$|[，,？?])", after):
            return True
        if re.match(r"\s*(?:的)?" + attribute + r"(?:仍|还|尚)?(?:待核实|待确认|需核实|需确认|未核实|未确认|未知|不确定)(?:$|[，,])", after):
            return True
        # Sentence splitting removes the question mark. A bare parameter query
        # such as '内存32GB？' is distinct from '32GB是否适合软件？'.
        return bool(re.fullmatch(r"\s*(?:的)?" + attribute + r"\s*[？?]", after) or
                    re.fullmatch(r"\s*(?:的)?" + attribute + r"\s*", after) and
                    re.search(re.escape(text) + r"[？?]", surface))

    def affirmative_software(text, match):
        # Do not turn the substring "支持软件" in "不支持软件" into positive
        # source evidence. Negative/unknown statements remain with the existing
        # semantic reviewer rather than triggering this affirmative-only guard.
        prefix = text[max(0, match.start()-8):match.start()]
        denied_inference = re.search(r"不能仅凭[^，。；;]{0,16}(?:认定|证明|推断|判断)$", text[max(0,match.start()-24):match.start()])
        return not nonassertion(text, match) and not denied_inference and not re.search(r"(?:不|并非|并不|难以|未能|尚未)(?:能|可|更)?$", prefix)

    def literal_interface(fact, sentence):
        # Only a literal port statement, with an optional backend-known product
        # name/category prefix, is proof. An appended benefit needs review even
        # when the same sentence also repeats the entire original specification.
        target = norm(sentence).strip('：:，,。.')
        for name, pid in sorted(aliases.items(), key=lambda item: -len(item[0])):
            if pid == identity(fact) and len(name) > 2 and target.startswith(name):
                target = target[len(name):].strip('：:，,。.'); break
        original = norm(source_text(fact)).strip('：:，,。.')
        category = norm(fact.get('category') or '')
        return target in {original, category + original, category + ':' + original, category + '：' + original}

    def interface_source_matches_scope(fact, sentence):
        accessory = r"包装|附件|配件|电源适配器|充电器"
        category = str(fact.get('category') or '')
        accessory_source = re.search(accessory, category) or (
            not re.search(r"接口|端口", category) and re.search(accessory, source_text(fact)))
        # A USB-C charger in the box is not evidence of the computer's ports.
        # It may be a related source only when this actual claim names an
        # accessory, not merely because both passages happen to contain USB.
        return not accessory_source or bool(re.search(accessory, sentence))

    def add(location, quote, kind, pids, evidence, reasons):
        used_refs = [r for r in refs if r.get('fact_id') in {f['id'] for f in evidence} or
                     any(r.get('id') in (f.get('evidence_ref_ids') or []) for f in evidence)]
        item = {"location": location, "quote": quote, "kind": kind,
                "product_ids": pids, "fact_ids": [f["id"] for f in evidence],
                "evidence_ref_ids": [str(r['id']) for r in used_refs if r.get('id')],
                "status": "unsupported" if reasons else "supported", "issues": reasons,
                "requirement_version": context.get("version"),
                "evidence_version": (task.get('selling_point_plan') or {}).get('evidence_version') or task.get("evidence_version")}
        support.append(item)
        for reason in reasons:
            checks.append({"category": "推荐与卖点依据", "status": "blocked",
                           "message": f"{location}「{quote}」：{reason}",
                           "location": location, "quote": quote, "fact_ids": item["fact_ids"]})

    surfaces = [(key, str(draft.get(key) or "")) for key in ("title", "lead", "body", "cta")]
    for key in ("selling_points", "points", "tags"):
        for i, point in enumerate(draft.get(key) or []):
            if isinstance(point, dict):
                value = " ".join(str(point.get(k) or "") for k in ("text", "title", "body", "value", "claim"))
            else:
                value = str(point)
            surfaces.append((f"{key}[{i}]", value))
    for i, image in enumerate(draft.get("images") or []):
        if isinstance(image, dict):
            surfaces.append((f"images[{i}].caption", str(image.get("caption") or "")))

    # Recheck every actual claim in the final draft, including short poster
    # points, tags and image captions. Draft claim_support is intentionally ignored.
    for location, text in surfaces:
        for sentence in filter(None, (s.strip() for s in re.split(r"[。！？!\n；;]", text))):
            for match in specification_matches(sentence):
                token = match.group(0); pids = product_at(sentence, token)
                if numeric_nonassertion(sentence, match, text):
                    continue
                matching = [f for f in usable if identity(f) in pids and
                            any(spec_key(m.group(0)) == spec_key(token) for m in specification_matches(source_text(f), f.get('category','')))]
                reasons = []
                if not matching:
                    reasons.append("该型号及配置范围没有支持此数字的有效原文；请纠正型号、取得对应依据或删除该数字")
                else:
                    valid = [f for f in matching if qualified(f, sentence, token)]
                    if not valid:
                        reasons.append("原文的约数、上限或适用配置/测试条件未保留；请恢复必要限定或删去该陈述")
                    else:
                        matching = valid
                add(location, sentence, "specification", pids, matching, reasons)
            for match in performance.finditer(sentence):
                if nonassertion(sentence, match):
                    continue
                pids = product_at(sentence, match.group(0))
                # Specifications do not entail workload, compatibility or speed.
                # Exact original wording may be supported; semantic paraphrases
                # need a fresh semantic check against actual original evidence.
                matching = [f for f in usable if identity(f) in pids and norm(match.group(0)) in norm(source_text(f)) and qualified(f, sentence)]
                reasons = [] if matching else ["缺少该产品对应任务的兼容或性能原文；CPU、内存等规格不能证明此承诺，请收窄或删除"]
                add(location, sentence, "capability", pids, matching, reasons)
            for match in software_suitability.finditer(sentence):
                if not affirmative_software(sentence, match):
                    continue
                pids = product_at(sentence, match.group(0))
                matching = [f for f in usable if identity(f) in pids and qualified(f, sentence) and any(
                    norm(original.group(0)) == norm(match.group(0)) and affirmative_software(source_text(f), original)
                    for original in software_suitability.finditer(source_text(f)))]
                add(location, sentence, "software_suitability", pids, matching, [] if matching else [
                    "缺少该产品对应软件或工作负载适配的有效原文；系统名称、CPU或内存规格不能证明此句，请删除适配结论或改为待核实条件"])
            for match in budget_claim.finditer(sentence):
                if nonassertion(sentence, match):
                    continue
                pids = product_at(sentence, match.group(0))
                prices = [q for q in (task.get("quotes") or {}).get("quotes", []) if q.get("status") == "verified" and
                          q.get("configuration_scope") and
                          (q.get("product_id") in pids or aliases.get(norm(q.get("product_name", ""))) in pids) and
                          any(f.get('configuration_scope') == q['configuration_scope'] for f in usable if identity(f) in pids)]
                budget = str((task.get("brief") or {}).get("budget") or "")
                limit = re.search(r"\d[\d,]*(?:\.\d+)?", budget)
                within = False
                for price in prices:
                    try:
                        within |= bool(limit and Decimal(str(price["checkout_amount"])) <= Decimal(limit.group(0).replace(",", "")))
                    except (KeyError, InvalidOperation, TypeError):
                        pass
                add(location, sentence, "budget_fit", pids, [], [] if within else [
                    "缺少有效的同型号同配置报价与预算比较依据；请保留预算匹配未知，不承诺符合预算"])
            for match in recommendation.finditer(sentence):
                if not affirmative_software(sentence, match):
                    continue
                pids = product_at(sentence, match.group(0))
                relevant = [c for c in candidates if identity(c) in pids]
                conditional = [c for c in relevant if c.get("status") in {"conditional", "conditional_candidate", "条件候选", "excluded", "已排除"} or
                               any(a.get("status") in {"unknown", "conflict"} and a.get("strength") == "hard"
                                   for a in (c.get("fit_assessments") or []) if isinstance(a, dict))]
                if conditional:
                    add(location, sentence, "recommendation", pids, [], [
                        "条件候选或冲突候选被写成确定适配推荐；请写明相关条件、改为比较方向或删除推荐结论"])
                else:
                    matched = [f for f in usable if identity(f) in pids and
                               any(f.get('id') in (a.get('fact_ids') or a.get('supporting_fact_ids') or [])
                                   for c in relevant for a in (c.get('fit_assessments') or []) if isinstance(a, dict))]
                    add(location, sentence, "recommendation", pids, matched, [])
                    if not matched:
                        support[-1]['status'] = 'requires_semantic_review'

            # Port statements also need a stored claim-to-source mapping. A
            # related interface passage is only a candidate for semantic review:
            # USB3.2, for example, must not by itself prove USB-A or an accessory
            # benefit. Keep backend-validated references separate from support.
            if interface_terms.search(sentence):
                pids = product_at(sentence)
                technical_names = {norm(m.group(0)) for m in interface_names.finditer(sentence)}
                related = [f for f in usable if identity(f) in pids and interface_source_matches_scope(f, sentence) and (
                    re.search(r"接口|端口", str(f.get('category') or '')) or
                    technical_names.intersection(norm(m.group(0)) for m in interface_names.finditer(source_text(f))))]
                matched = [f for f in related if literal_interface(f, sentence) and qualified(f, sentence)]
                add(location, sentence, "interface_statement", pids, matched, [])
                item = support[-1]
                item['support_relation'] = 'literal_original' if matched else 'relevance_only'
                item['candidate_fact_ids'] = [f['id'] for f in related]
                item['candidate_evidence_ref_ids'] = [str(r['id']) for r in refs if r.get('id') and (
                    r.get('fact_id') in set(item['candidate_fact_ids']) or
                    any(r['id'] in (f.get('evidence_ref_ids') or []) for f in related))]
                if not matched:
                    item['status'] = 'requires_semantic_review'

            # Record other actual product statements too. They require semantic
            # interpretation unless the original passage itself is present in
            # the final text; never mark an arbitrary citation as proof.
            if not any(item['location'] == location and item['quote'] == sentence for item in support) and re.search(
                    r"屏幕|处理器|内存|存储|续航|重量|触控|便携|轻薄|金属|鸿蒙|Windows|适配|兼容", sentence, re.I):
                pids = product_at(sentence)
                matched = [f for f in usable if identity(f) in pids and norm(source_text(f)).strip('：:，,。.') in norm(sentence)]
                add(location, sentence, "product_statement", pids, matched, [])
                if not matched:
                    support[-1]['status'] = 'requires_semantic_review'

    # A real semantic reviewer can catch paraphrases and evidence implication
    # beyond the bounded rules. Preserve all of its issues; no fact ID waives it.
    if semantic and semantic.get("issues"):
        for issue in semantic["issues"]:
            quote = issue.get("quote") or issue.get("claim") or issue.get("原句") or "" if isinstance(issue, dict) else ""
            checks.append({"category": "推荐语义依据", "status": "blocked", "message": str(issue), "quote": quote})
    return {"claim_support": support, "checks": checks}


def reconcile_visual_evidence(result: dict, proof: dict) -> dict:
    """Resolve only visual claims contradicted by verified compositor evidence."""
    issues = result.get("issues", [])
    if not isinstance(issues, list):
        issues = [issues or "视觉模型未返回有效核验项目"]
    remaining, resolutions = [], []
    normalize = lambda value: re.sub(r"\s+", "", str(value))
    def texts(value):
        if isinstance(value, str):
            return [normalize(value)] if value else []
        if isinstance(value, dict):
            return [text for child in value.values() for text in texts(child)]
        if isinstance(value, list):
            return [text for child in value for text in texts(child)]
        return []
    rendered = texts(proof.get("text_rendered", []))
    for issue in issues:
        if isinstance(issue, dict) and proof.get("verified") is True:
            category = issue.get("category")
            if category == "product_pixels" and proof.get("product_pixels_verified") is True:
                resolutions.append({"issue": issue, "evidence": "成品产品区域与同一ima原图等比例贴层后的像素哈希完全相同"})
                continue
            expected, observed = issue.get("expected"), issue.get("observed")
            if category == "text" and isinstance(expected, str) and isinstance(observed, str) and normalize(expected) and normalize(expected) == normalize(observed) and any(normalize(expected) in text for text in rendered):
                resolutions.append({"issue": issue, "evidence": "预期与识别文本仅有空白差异，且与已验证成品的实际排版输入一致"})
                continue
        remaining.append(issue)
    value = dict(result, issues=remaining)
    if resolutions:
        value["literal_resolutions"] = resolutions
    # A model can decline judgement with no issue; proof cannot silently convert that to a pass.
    value["passed"] = not remaining and (result.get("passed") is True or bool(resolutions))
    return value


def reconcile_literal_evidence(result: dict, draft: dict, facts: list) -> dict:
    """Resolve only demonstrably false critic objections to an exact factual rendering.

    A model's judgement cannot override a literal match. This is deliberately narrow:
    it does not waive qualifier omissions, negatives, comparisons or novel claims.
    """
    def key(s):
        return re.sub(r"[\s：:，,。；;（）()]", "", str(s)).lower()
    full_text = key(" ".join(str(draft.get(k, "")) for k in ["title", "lead", "body", "cta"]))
    used = set(draft.get("fact_ids") or [])
    literals = {}
    for fact in facts:
        if fact.get("id") not in used or not fact.get("verified"):
            continue
        category, excerpt = fact.get("category", ""), fact.get("excerpt", "")
        for verb in ["", "为", "提供", "可选"]:
            literals[key(category + verb + excerpt)] = fact["id"]
    remaining, resolved = [], []
    for issue in result.get("issues") or []:
        quote = ""
        if isinstance(issue, dict):
            quote = next((issue.get(k) for k in ["quote", "原句", "claim", "draft_quote"] if isinstance(issue.get(k), str)), "")
        if quote and key(quote) in full_text and key(quote) in literals:
            resolved.append({"quote": quote, "fact_id": literals[key(quote)], "resolution": "正文原句与所引用事实逐字归一后相同"})
        else:
            remaining.append(issue)
    if resolved:
        result = dict(result)
        result["issues"] = remaining
        result["literal_resolutions"] = resolved
        if not remaining:
            result["passed"] = True
    return result


def validate(draft: dict | None, facts: list, assets: list, quotes: dict, platform_id: str,
             semantic: dict | None = None) -> list[dict]:
    checks = []
    def add(category, status, message):
        checks.append({"category": category, "status": status, "message": message})
    if not draft:
        return [{"category": "内容", "status": "blocked", "message": "尚未生成内容"}]
    p = platform(platform_id)
    text = "\n".join(str(draft.get(k) or "") for k in ["title", "lead", "body", "cta"])
    if not draft.get("title") or not draft.get("body"):
        add("内容", "blocked", "缺少标题或正文")
    if platform_id == "poster":
        points = draft.get("selling_points") or draft.get("points")
        if not isinstance(points, list):
            points = [line.strip() for line in str(draft.get("body") or "").splitlines() if line.strip()]
        if not 1 <= len(points) <= 3:
            add("海报版式", "blocked", "海报正文必须为1至3条完整短卖点，每条占一行；删除额外段落，不能截断事实限定")
    valid_facts = {f["id"]: f for f in facts if f.get("verified")}
    used = draft.get("fact_ids", [])
    unknown = [x for x in used if x not in valid_facts]
    if not used or unknown:
        add("产品事实", "blocked", "未关联有效事实或引用了不存在的事实")
    else:
        add("产品事实", "pass", f"已关联 {len(used)} 条 ima 原文事实，配置与测试限定需随正文保留")
    selected = draft.get("images", [])
    asset_map = {a["id"]: a for a in assets}
    invalid = [a for a in selected if a.get("id") not in asset_map or not asset_map[a["id"]].get("verified")]
    identities = {(valid_facts[x].get("product_id") or valid_facts[x].get("model")) for x in used if x in valid_facts}
    mismatched = [a for a in selected if a.get("id") in asset_map and
                  (asset_map[a["id"]].get("product_id") or asset_map[a["id"]].get("model")) not in identities]
    if invalid:
        add("图片型号", "blocked", "配图缺少已确认的型号与索引关联")
    elif mismatched:
        add("图片型号", "blocked", "配图型号与正文实际引用的产品事实不一致")
    elif len(selected) < p["min_images"] or len(selected) > p["max_images"]:
        add("图片数量", "blocked", f"{p['name']}需 {p['min_images']}–{p['max_images']} 张图，目前 {len(selected)} 张")
    else:
        add("图片型号", "pass", "选图均来自已关联型号的 ima 图片索引；原图按比例放置")
    hits = [w for w in FORBIDDEN if w in text]
    if hits:
        add("营销合规", "blocked", "发现需修改的表达：" + "、".join(hits))
    else:
        add("营销合规", "pass", "未命中当前绝对化与虚假承诺规则")
    if re.search(r"我(?:用了|买了|亲测)|亲身体验|实测(?:提升|跑分|续航)", text):
        add("体验依据", "blocked", "出现亲测或体验性陈述，需要真实且获准使用的证据")
    # No monetary amount may be introduced independently of the pricing engine.
    matches = re.finditer(r"(?:[¥￥]|CNY|RMB)\s*(\d[\d,]*(?:\.\d{1,2})?)|(?<![\d.])(\d[\d,]*(?:\.\d{1,2})?)\s*元", text, re.I)
    amounts = []
    for match in matches:
        before, after = text[max(0, match.start()-12):match.start()], text[match.end():match.end()+10]
        if re.search(r"预算[约为在是：: ]*$", before) or re.match(r"(?:左右|以内|上下)?(?:的)?预算", after):
            continue  # A user's budget is not a product checkout-price claim.
        amounts.append(Decimal((match.group(1) or match.group(2)).replace(",", "")))
    allowed = set()
    used_models = [valid_facts[x].get("model", "") for x in used if x in valid_facts]
    model_key = lambda s: re.sub(r"[\s（）()_-]", "", str(s)).lower().replace("huawei", "")
    for q in quotes.get("quotes", []):
        if q.get("status") == "verified":
            if q.get("product_name") and not any(model_key(m) in model_key(q["product_name"]) for m in used_models if m):
                continue
            try:
                allowed.add(Decimal(str(q["checkout_amount"])))
            except (KeyError, InvalidOperation, TypeError):
                pass
    if amounts and any(x not in allowed for x in amounts):
        add("价格", "blocked", "文案出现未由报价引擎提供的金额")
    elif not quotes.get("best"):
        add("价格", "warning", "尚无已核实最低报价；不得在文案中承诺确定到手价")
    else:
        add("价格", "pass", "报价引擎结果已提供；导出前仍需确认其有效期与资格条件")
    source = " ".join(str(valid_facts[x].get("claim", "")) + str(valid_facts[x].get("model", "")) for x in used if x in valid_facts)
    normalize = lambda s: re.sub(r"\s+", "", s).lower()
    specifications = re.findall(r"\d+(?:\.\d+)?\s*(?:GHz|GB|TB|kg|Wh|nits|PPI|mm|Hz|英寸|小时|线程|核|%)", text, re.I)
    if any(normalize(spec) not in normalize(source) for spec in specifications):
        add("数字事实", "blocked", "文案出现未由所引用产品事实支持的规格数字")
    if semantic is None:
        add("语义核验", "warning", "模型语义核验未执行；当前为可编辑规则草稿，逐项依据可查看")
    elif semantic.get("passed") is True and not semantic.get("issues"):
        add("语义核验", "pass", "模型已辅助对照事实、限制条件与文本；不替代来源记录")
    else:
        add("语义核验", "blocked", "；".join(str(x) for x in semantic.get("issues", ["无法确认内容与证据一致"])))
    if "广告" not in text or "AI" not in text:
        add("发布标识", "warning", "发布时按适用规则标明广告及AI生成/辅助内容，并使用平台标识功能")
    else:
        add("发布标识", "pass", "成品包含广告与AI辅助提示；发布时仍须使用平台对应声明功能")
    return checks
