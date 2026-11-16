"""Build credential-free Dify DSL and tool definitions from the local contracts.

Run with the project's Python environment. Generated YAML targets DSL 0.6.0,
matching Dify's current official CLI e2e fixture rather than assuming Cloud has
already deployed the newest main-branch DSL version.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PUBLIC_BASE = "https://replace-with-your-api.example.invalid"

BUILD_CHAT = '''import json

def main(query: str, task_id: str, user: str, context_token: str,
         conversation_task_id: str, conversation_context_token: str,
         conversation_user: str, action: str, platform: str, sys_user_id: str) -> dict:
    task_id = (task_id or conversation_task_id or "").strip()
    context_token = (context_token or conversation_context_token or "").strip()
    user = (user or conversation_user or "").strip()
    if not task_id:
        user = "preview:" + str(sys_user_id)
        context_token = ""
    elif not user:
        user = "preview:" + str(sys_user_id)
    action = action or "chat"
    if action not in ["chat", "generate", "retrieve", "verify"]:
        raise ValueError("不支持的任务动作")
    payload = {"action": action, "user": user, "message": query or "",
               "instruction": query or "", "context_token": context_token}
    if task_id:
        payload["task_id"] = task_id
    if platform:
        payload["platform"] = platform
    return {"payload": json.dumps(payload, ensure_ascii=False),
            "request_user": user, "context_token": context_token}
'''

PARSE_CHAT = '''import json

def main(body: str, status_code: int, previous_task_id: str,
         request_user: str, context_token: str) -> dict:
    fallback = {"reply": "任务接口未返回可用结果，请查看连接状态或重新执行。",
                "task_id": previous_task_id or "", "status": "error",
                "result_json": "{}", "request_user": request_user,
                "context_token": context_token}
    if not 200 <= int(status_code) < 300:
        fallback["reply"] = "任务接口返回 HTTP " + str(status_code) + "，未生成或确认成品。"
        return fallback
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return fallback
    if not isinstance(data, dict) or not isinstance(data.get("result"), dict):
        return fallback
    task = data["result"]
    task_id = str(data.get("task_id") or task.get("id") or previous_task_id or "")
    if not task_id:
        return fallback
    # Keep large evidence bodies and chat history out of the code-node output.
    # The business UI reads the complete saved task through its own backend.
    summary = {k: task[k] for k in ["id", "status", "brief", "draft", "checks", "quotes"] if k in task}
    encoded = json.dumps(summary, ensure_ascii=False)
    if len(encoded) > 60000:
        encoded = json.dumps({"id": task_id, "status": task.get("status"),
                              "truncated": True, "detail": "请在业务界面查看完整任务"}, ensure_ascii=False)
    return {"reply": str(data.get("reply") or "任务已更新，请在业务界面查看内容和核验结果。")[:20000],
            "task_id": task_id, "status": str(data.get("status") or task.get("status") or "unknown"),
            "result_json": encoded, "request_user": str(data.get("user") or request_user),
            "context_token": str(data.get("context_token") or context_token)}
'''

PARSE_TOOL = '''import json

def main(body: str, status_code: int) -> dict:
    if not 200 <= int(status_code) < 300:
        return {"result": json.dumps({"ok": False, "http_status": status_code,
                 "error": "工具接口执行失败；不得补造结果"}, ensure_ascii=False), "ok": False}
    try:
        result = json.loads(body)
        encoded = json.dumps(result, ensure_ascii=False)
    except (ValueError, TypeError):
        return {"result": '{"ok":false,"error":"工具返回了无效JSON"}', "ok": False}
    if len(encoded) > 75000:
        return {"result": '{"ok":false,"error":"工具结果过长；请缩小检索或核验范围"}', "ok": False}
    return {"result": encoded, "ok": True}
'''


def variable(name, label, kind="text-input", required=False, options=None, default="", maximum=256):
    return {"variable": name, "label": label, "type": kind, "required": required,
            "options": options or [], "default": default, "max_length": maximum,
            "hint": "", "placeholder": ""}


def code_node(code, variables, outputs, title):
    return {"type": "code", "title": title, "code_language": "python3", "code": code,
            "variables": [{"variable": name, "value_selector": selector} for name, selector in variables.items()],
            "outputs": {key: {"type": value, "children": None} for key, value in outputs.items()}}


def http_node(path):
    return {"type": "http-request", "title": "调用受控任务服务" if "dify" in path else "调用业务工具",
            "desc": "外部调用；TOOL_TOKEN仅以Secret环境变量引用，不作为用户输入。",
            "method": "post", "url": "{{#env.PUBLIC_API_BASE#}}" + path,
            "authorization": {"type": "no-auth", "config": None},
            "headers": "Content-Type: application/json\nX-Tool-Token: {{#env.TOOL_TOKEN#}}", "params": "", "variables": [],
            "body": {"type": "raw-text", "data": [{"id": "request-json", "key": "", "type": "text", "value": "{{#payload.payload#}}"}]},
            "ssl_verify": True, "timeout": {"connect": 10, "read": 300, "write": 30},
            "retry_config": {"retry_enabled": False, "max_retries": 0, "retry_interval": 1000},
            "error_strategy": "fail-branch"}


def graph(nodes, links):
    by_id = {key: data for key, data in nodes}
    return {"nodes": [{"id": key, "type": "custom", "data": {"desc": "", "selected": False, **data},
                       "position": {"x": i * 305 + 30, "y": 500 if key == "failure" else 250},
                       "sourcePosition": "right", "targetPosition": "left", "width": 260,
                       "height": 100, "selected": False} for i, (key, data) in enumerate(nodes)],
            "edges": [{"id": f"{source}-{handle}-{target}", "type": "custom", "source": source,
                       "target": target, "sourceHandle": handle, "targetHandle": "target", "zIndex": 0,
                       "data": {"sourceType": by_id[source]["type"], "targetType": by_id[target]["type"],
                                "isInIteration": False, "isInLoop": False}}
                      for source, target, handle in links],
            "viewport": {"x": 0, "y": 0, "zoom": 0.65}}


def base(name, mode, description):
    return {"version": "0.6.0", "kind": "app", "dependencies": [],
            "app": {"name": name, "description": description, "icon": "💻", "icon_type": "emoji",
                    "icon_background": "#EAF1FF", "mode": mode, "use_icon_as_answer_icon": False},
            "workflow": {"conversation_variables": [], "environment_variables": [
                {"id": "d3d3609d-32b6-4413-98f6-e6037ae5fef3", "name": "PUBLIC_API_BASE",
                 "value_type": "string", "value": PUBLIC_BASE, "description": "自研后端公共HTTPS地址，不带末尾斜线"},
                {"id": "03e46106-fcae-4c90-9104-b574b7768444", "name": "TOOL_TOKEN",
                 "value_type": "secret", "value": "", "description": "与自研后端TOOL_TOKEN一致；导出时排除真实值"}],
                "rag_pipeline_variables": [],
                "features": {"file_upload": {"enabled": False}, "opening_statement": "",
                    "retriever_resource": {"enabled": False}, "sensitive_word_avoidance": {"enabled": False},
                    "speech_to_text": {"enabled": False}, "suggested_questions": [],
                    "suggested_questions_after_answer": {"enabled": False}, "text_to_speech": {"enabled": False}}}}


def chatflow():
    app = base("华为PC图文工作台 · 对话入口", "advanced-chat", "多轮场景理解与受控图文生成入口。执行、证据与规则计算由自研后端负责；需配置公共HTTPS服务和工具凭证。")
    workflow = app["workflow"]
    workflow["features"]["opening_statement"] = "描述这次内容面向谁、解决什么问题、准备发在哪里。信息不足时我会继续确认；资料与报价未核实前不会承诺。"
    names = ["task_id", "context_token", "request_user"]
    workflow["conversation_variables"] = [
        {"id": uuid, "name": name, "description": description, "value_type": "string", "value": "", "selector": ["conversation", name]}
        for uuid, name, description in [
            ("e23cb11f-76de-4c7c-8855-be08a684775d", names[0], "后端任务标识；与Dify conversation_id不同"),
            ("3cd81212-e366-4806-9194-71f996d73d45", names[1], "服务器生成的任务签名，不得由LLM生成"),
            ("f8d98dc2-6129-4a2d-a81c-42e9cf34e9aa", names[2], "后端代理传入的业务用户；预览使用独立命名空间")]]
    nodes = [
        ("start", {"type": "start", "title": "任务输入", "variables": [
            variable("task_id", "后端任务ID（服务器代理填写）"),
            variable("user", "业务用户（服务器代理填写）"),
            variable("context_token", "任务签名（服务器代理填写）", maximum=256),
            variable("action", "执行动作", "select", options=["chat", "generate", "retrieve", "verify"], default="chat"),
            variable("platform", "平台覆盖值", "select", options=["wechat", "xiaohongshu", "moments", "poster"], default="")]}),
        ("payload", code_node(BUILD_CHAT,
            {"query": ["sys", "query"], "task_id": ["start", "task_id"], "user": ["start", "user"],
             "context_token": ["start", "context_token"], "conversation_task_id": ["conversation", "task_id"],
             "conversation_context_token": ["conversation", "context_token"], "conversation_user": ["conversation", "request_user"],
             "action": ["start", "action"], "platform": ["start", "platform"], "sys_user_id": ["sys", "user_id"]},
            {"payload": "string", "request_user": "string", "context_token": "string"}, "安全编码请求")),
        ("execute", http_node("/api/dify/execute")),
        ("parsed", code_node(PARSE_CHAT,
            {"body": ["execute", "body"], "status_code": ["execute", "status_code"],
             "previous_task_id": ["conversation", "task_id"], "request_user": ["payload", "request_user"],
             "context_token": ["payload", "context_token"]},
            {key: "string" for key in ["reply", "task_id", "status", "result_json", "request_user", "context_token"]}, "解析结果与交付状态")),
        ("remember", {"type": "assigner", "version": "2", "title": "保留本次任务上下文", "items": [
            {"input_type": "variable", "operation": "over-write", "value": ["parsed", name],
             "variable_selector": ["conversation", name], "write_mode": "over-write"} for name in names]}),
        ("answer", {"type": "answer", "title": "回复与追问", "answer": "{{#parsed.reply#}}", "variables": []}),
        ("failure", {"type": "answer", "title": "连接失败", "variables": [],
            "answer": "任务服务连接失败，本次未确认生成结果。请检查公共HTTPS地址、TOOL_TOKEN与服务运行状态；原任务可在业务界面重新打开。"}),
    ]
    workflow["graph"] = graph(nodes, [("start", "payload", "source"), ("payload", "execute", "source"),
        ("execute", "parsed", "source"), ("execute", "failure", "fail-branch"),
        ("parsed", "remember", "source"), ("remember", "answer", "source")])
    return app


def tool_workflow(name, path, fields, build_code):
    app = base(name, "workflow", "可发布为Dify Workflow工具。输入JSON由程序解析；金额与核验不由LLM臆算。")
    outputs = [{"variable": "result", "value_selector": ["parsed", "result"], "value_type": "string"},
               {"variable": "ok", "value_selector": ["parsed", "ok"], "value_type": "boolean"}]
    nodes = [
        ("start", {"type": "start", "title": "工具输入", "variables": fields}),
        ("payload", code_node(build_code, {f["variable"]: ["start", f["variable"]] for f in fields}, {"payload": "string"}, "编码工具参数")),
        ("execute", http_node(path)),
        ("parsed", code_node(PARSE_TOOL, {"body": ["execute", "body"], "status_code": ["execute", "status_code"]},
                            {"result": "string", "ok": "boolean"}, "解析工具结果")),
        ("end", {"type": "end", "title": "返回工具结果", "outputs": outputs}),
        ("failure", {"type": "code", "title": "连接失败结果", "code_language": "python3", "variables": [],
            "code": 'def main() -> dict:\n    return {"result": \'{"ok":false,"error":"工具服务连接失败"}\', "ok": False}\n',
            "outputs": {"result": {"type": "string", "children": None}, "ok": {"type": "boolean", "children": None}}}),
        ("failed_end", {"type": "end", "title": "返回失败状态", "outputs": [
            {"variable": "error_result", "value_selector": ["failure", "result"], "value_type": "string"},
            {"variable": "error_ok", "value_selector": ["failure", "ok"], "value_type": "boolean"}]})]
    app["workflow"]["graph"] = graph(nodes, [("start", "payload", "source"), ("payload", "execute", "source"),
        ("execute", "parsed", "source"), ("parsed", "end", "source"),
        ("execute", "failure", "fail-branch"), ("failure", "failed_end", "source")])
    return app


def openapi():
    obj = {"type": "object", "additionalProperties": True}
    array = {"type": "array", "items": obj}
    schemas = {
        "ExecuteRequest": {"type": "object", "required": ["action", "user"], "properties": {
            "action": {"type": "string", "enum": ["chat", "generate", "retrieve", "verify"]}, "user": {"type": "string"},
            "task_id": {"type": "string"}, "context_token": {"type": "string", "description": "服务器HMAC_SHA256签名，与user和task_id绑定"},
            "message": {"type": "string"}, "instruction": {"type": "string"}, "brief": obj,
            "platform": {"type": "string", "enum": ["wechat", "xiaohongshu", "moments", "poster"]}}},
        "SearchRequest": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "model": {"type": "string"}}},
        "QuotesRequest": {"type": "object", "required": ["offers", "buyer", "region"], "properties": {
            "offers": {**array, "description": "带真实来源和时间的报价对象；完整字段见docs/pricing.md。不得由LLM补造verified、金额和优惠规则。"},
            "buyer": {**obj, "description": "kind personal/business；身份资格以true/false/未知区分"},
            "region": {"type": "string", "default": "杭州"}, "now": {"type": "string", "format": "date-time"},
            "max_age_hours": {"type": "number", "minimum": 0}}},
        "VerifyRequest": {"type": "object", "required": ["draft", "facts", "assets", "quotes", "platform"], "properties": {
            "draft": obj, "facts": array, "assets": array, "quotes": obj,
            "platform": {"type": "string", "enum": ["wechat", "xiaohongshu", "moments", "poster"]}}},
    }
    result = {"openapi": "3.0.3", "info": {"title": "华为PC Agent 受控工具", "version": "1.0.0",
              "description": "产品事实从ima检索；报价使用独立规则引擎。导入前替换servers地址，使用X-Tool-Token自定义请求头认证。"},
              "servers": [{"url": PUBLIC_BASE}], "security": [{"toolToken": []}], "paths": {},
              "components": {"securitySchemes": {"toolToken": {"type": "apiKey", "in": "header", "name": "X-Tool-Token"}}, "schemas": schemas}}
    for path, schema, operation, summary in [
        ("/api/dify/execute", "ExecuteRequest", "executeHuaweiContentTask", "执行受控任务流水线"),
        ("/api/tools/search", "SearchRequest", "searchImaProductFacts", "检索指定ima知识库产品事实与图片"),
        ("/api/tools/quotes", "QuotesRequest", "calculateVerifiedOffers", "按证据和资格计算报价，禁止LLM算价"),
        ("/api/tools/verify", "VerifyRequest", "verifyHuaweiDraft", "核验事实、型号、平台格式与营销表达")]:
        result["paths"][path] = {"post": {"operationId": operation, "summary": summary,
            "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/" + schema}}}},
            "responses": {"200": {"description": "结构化业务结果；仍须检查业务status和核验项", "content": {"application/json": {"schema": obj}}},
                          "401": {"description": "工具凭证无效"}, "403": {"description": "任务上下文或用户权限不匹配"},
                          "422": {"description": "输入参数不符合合同"}}}}
    return result


def write_yaml(filename, value):
    class ReadableDumper(yaml.SafeDumper):
        def ignore_aliases(self, data):
            return True

    def represent_string(dumper, text):
        return dumper.represent_scalar("tag:yaml.org,2002:str", text, style="|" if "\n" in text else None)

    ReadableDumper.add_representer(str, represent_string)
    (HERE / filename).write_text(yaml.dump(value, Dumper=ReadableDumper, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


def main():
    HERE.mkdir(exist_ok=True)
    write_yaml("huawei-pc-chatflow.yml", chatflow())
    write_yaml("ima-search-workflow.yml", tool_workflow("华为PC · ima资料检索", "/api/tools/search", [
        variable("query", "检索问题", "paragraph", True, maximum=4000), variable("model", "精确产品型号", maximum=256)],
        'import json\ndef main(query: str, model: str) -> dict:\n    return {"payload": json.dumps({"query": query, "model": model or ""}, ensure_ascii=False)}\n'))
    write_yaml("quote-engine-workflow.yml", tool_workflow("华为PC · 确定性报价计算", "/api/tools/quotes", [
        variable("offers_json", "报价证据JSON数组", "paragraph", True, maximum=80000),
        variable("buyer_json", "资格JSON对象", "paragraph", True, default="{}", maximum=4000),
        variable("region", "报价地区", required=True, default="杭州")],
        'import json\ndef main(offers_json: str, buyer_json: str, region: str) -> dict:\n'
        '    offers, buyer = json.loads(offers_json), json.loads(buyer_json)\n'
        '    if not isinstance(offers, list) or not isinstance(buyer, dict):\n'
        '        raise ValueError("offers必须是数组且buyer必须是对象")\n'
        '    return {"payload": json.dumps({"offers": offers, "buyer": buyer, "region": region}, ensure_ascii=False)}\n'))
    write_yaml("verify-workflow.yml", tool_workflow("华为PC · 图文核验", "/api/tools/verify", [
        variable("draft_json", "草稿JSON对象", "paragraph", True, maximum=60000),
        variable("facts_json", "事实JSON数组", "paragraph", True, maximum=80000),
        variable("assets_json", "素材JSON数组", "paragraph", True, maximum=60000),
        variable("quotes_json", "报价引擎结果JSON对象", "paragraph", True, default="{}", maximum=60000),
        variable("platform", "发布平台", "select", True, options=["wechat", "xiaohongshu", "moments", "poster"], default="wechat")],
        'import json\ndef main(draft_json: str, facts_json: str, assets_json: str, quotes_json: str, platform: str) -> dict:\n'
        '    draft, facts, assets, quotes = [json.loads(v) for v in [draft_json, facts_json, assets_json, quotes_json]]\n'
        '    if not isinstance(draft, dict) or not isinstance(facts, list) or not isinstance(assets, list) or not isinstance(quotes, dict):\n'
        '        raise ValueError("草稿、事实、素材或报价JSON类型不正确")\n'
        '    return {"payload": json.dumps({"draft": draft, "facts": facts, "assets": assets, "quotes": quotes, "platform": platform}, ensure_ascii=False)}\n'))
    spec = openapi()
    write_yaml("tools.openapi.yml", spec)
    (HERE / "tools.openapi.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    module_spec = importlib.util.spec_from_file_location("huawei_policy_delivery", ROOT / "huawei_agent" / "policies.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    pack = {"version": "1.0.0", "classification": "项目内容策略，不代表各平台官方统一规则", "scenarios": module.SCENARIOS,
            "platforms": module.PLATFORMS, "channels": module.CHANNELS, "system_prompt": module.SYSTEM_PROMPT}
    (HERE / "policy-pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("已生成4个Dify DSL、2个OpenAPI格式及8场景/4平台策略包；未包含真实凭证。")


if __name__ == "__main__":
    main()
