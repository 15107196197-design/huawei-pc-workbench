"""Offline checks for the delivered DSL. This is not a Cloud import test."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent


def load_code(node):
    scope = {}
    exec(compile(node["data"]["code"], "<Dify code node>", "exec"), scope)
    return scope["main"]


def has_tool_secret_reference(value):
    if isinstance(value, str):
        return "{{#env.TOOL_TOKEN#}}" in value
    if isinstance(value, list):
        return value[:2] == ["env", "TOOL_TOKEN"] or any(has_tool_secret_reference(item) for item in value)
    if isinstance(value, dict):
        return any(has_tool_secret_reference(item) for item in value.values())
    return False


def validate_http_auth(data):
    assert data["authorization"] == {"type": "no-auth", "config": None}, "平台回调不得使用保留的Authorization头"
    lines = data["headers"].splitlines()
    headers = {key.strip().lower(): value.strip() for key, value in (line.split(":", 1) for line in lines)}
    assert len(headers) == len(lines), "不得重复声明认证请求头"
    assert headers == {"content-type": "application/json", "x-tool-token": "{{#env.TOOL_TOKEN#}}"}, "工具Token必须只通过X-Tool-Token引用Secret"
    assert json.dumps(data).count("{{#env.TOOL_TOKEN#}}") == 1, "Token不得进入URL、参数或请求正文"
    assert not has_tool_secret_reference({key: value for key, value in data.items() if key != "headers"}), "Secret不得进入HTTP参数或请求正文"


def validate_openapi(yaml_path, json_path):
    spec = yaml.safe_load(yaml_path.read_text())
    assert spec == json.loads(json_path.read_text()), "OpenAPI两种格式不一致"
    assert len(spec["paths"]) == 4
    expected = [{"toolToken": []}]
    assert spec["security"] == expected, "工具必须统一启用自定义请求头认证"
    assert spec["components"]["securitySchemes"] == {
        "toolToken": {"type": "apiKey", "in": "header", "name": "X-Tool-Token"}}, "工具凭证不得使用平台保留请求头"
    for path in spec["paths"].values():
        for operation in path.values():
            assert operation.get("security", expected) == expected, "单个工具不得绕过全局认证"
    return spec


def validate_graph(path):
    app = yaml.safe_load(path.read_text())
    assert app["kind"] == "app"
    assert app["app"]["mode"] in {"advanced-chat", "workflow"}
    workflow = app["workflow"]
    nodes = workflow["graph"]["nodes"]
    by_id = {node["id"]: node for node in nodes}
    assert len(by_id) == len(nodes), "节点ID重复"
    starts = [node for node in nodes if node["data"]["type"] == "start"]
    assert len(starts) == 1
    envs = {v["name"]: v for v in workflow["environment_variables"]}
    assert envs["TOOL_TOKEN"]["value_type"] == "secret"
    assert envs["TOOL_TOKEN"]["value"] == "", "DSL不得包含真实密钥"
    assert ".invalid" in envs["PUBLIC_API_BASE"]["value"]
    declared = {"start": {v["variable"] for v in starts[0]["data"]["variables"]},
                "conversation": {v["name"] for v in workflow["conversation_variables"]},
                "env": set(envs), "sys": {"query", "user_id"}}
    for node in nodes:
        data = node["data"]
        if data["type"] != "http-request":
            assert not has_tool_secret_reference(data), "Secret不得进入代码节点、输出或会话变量"
        if data["type"] == "code":
            load_code(node)
            declared[node["id"]] = set(data["outputs"])
        elif data["type"] == "http-request":
            declared[node["id"]] = {"body", "status_code", "headers", "files"}
            assert data["ssl_verify"] is True
            validate_http_auth(data)
            assert not data["retry_config"]["retry_enabled"], "有副作用的POST不自动重试"
    reached = {starts[0]["id"]}
    edges = workflow["graph"]["edges"]
    for edge in edges:
        assert edge["source"] in by_id and edge["target"] in by_id
    for _ in nodes:
        reached |= {edge["target"] for edge in edges if edge["source"] in reached}
    assert reached == set(by_id), "存在不可达节点"
    for node in nodes:
        data = node["data"]
        for selector in [v["value_selector"] for v in data.get("variables", []) if "value_selector" in v]:
            assert selector[1] in declared.get(selector[0], set()), selector
        for node_id, variable in re.findall(r"\{\{#([\w-]+)\.([\w-]+)#\}\}", json.dumps(data)):
            assert variable in declared.get(node_id, set()), (node_id, variable)
        if data.get("error_strategy") == "fail-branch":
            assert any(e["source"] == node["id"] and e["sourceHandle"] == "fail-branch" for e in edges)
    outputs = [output["variable"] for node in nodes if node["data"]["type"] == "end" for output in node["data"]["outputs"]]
    assert len(outputs) == len(set(outputs)), "多个End节点的输出名称必须唯一"
    return by_id


def main():
    paths = [HERE / filename for filename in ["huawei-pc-chatflow.yml", "ima-search-workflow.yml", "quote-engine-workflow.yml", "verify-workflow.yml"]]
    graphs = {path.name: validate_graph(path) for path in paths}
    chat = graphs["huawei-pc-chatflow.yml"]
    build, parse = load_code(chat["payload"]), load_code(chat["parsed"])
    query = '给新生写文案："轻薄"\n预算含\\字符与 {{#env.TOOL_TOKEN#}} 字面文本'
    kwargs = dict(query=query, task_id="task-1", user="local", context_token="signed-task-context",
                  conversation_task_id="", conversation_context_token="", conversation_user="", action="chat", platform="", sys_user_id="dify-preview")
    result = build(**kwargs)
    assert json.loads(result["payload"])["message"] == query, "自然语言必须安全JSON编码"
    assert json.loads(result["payload"])["context_token"] == "signed-task-context"
    kwargs.update(task_id="", user="forged-local", context_token="")
    assert json.loads(build(**kwargs)["payload"])["user"] == "preview:dify-preview"
    kwargs.update(conversation_task_id="task-2", conversation_context_token="saved-signature", conversation_user="local", user="")
    assert json.loads(build(**kwargs)["payload"])["task_id"] == "task-2"
    assert json.loads(build(**kwargs)["payload"])["context_token"] == "saved-signature"
    response = parse(json.dumps({"task_id": "task-1", "reply": "还需要目标人群", "status": "needs_input", "result": {"id": "task-1", "brief": {"platform": "wechat"}}}), 200, "", "local", "sig")
    assert response["task_id"] == "task-1" and response["status"] == "needs_input"
    assert json.loads(response["result_json"])["brief"]["platform"] == "wechat"
    preview = parse(json.dumps({"task_id": "preview-task", "reply": "继续确认", "user": "preview:dify-id", "context_token": "server-signature",
                               "result": {"id": "preview-task"}}), 200, "", "preview:dify-id", "")
    assert preview["context_token"] == "server-signature" and preview["request_user"] == "preview:dify-id"
    assert parse("invalid json", 200, "existing", "local", "sig")["status"] == "error"
    assert parse("forbidden", 403, "existing", "local", "sig")["task_id"] == "existing"
    assert parse("forbidden", 403, "existing", "local", "sig")["status"] == "error"
    large = parse(json.dumps({"task_id": "big", "reply": "ok", "result": {"id": "big", "draft": {"body": "大" * 65000}}}), 200, "", "local", "sig")
    assert json.loads(large["result_json"])["truncated"] is True
    quotes = graphs["quote-engine-workflow.yml"]
    request = load_code(quotes["payload"])("[]", "{}", "杭州")
    assert json.loads(request["payload"]) == {"offers": [], "buyer": {}, "region": "杭州"}
    try:
        load_code(quotes["payload"])("{}", "{}", "杭州")
    except ValueError:
        pass
    else:
        raise AssertionError("错误报价JSON类型未阻断")
    assert load_code(quotes["parsed"])("not JSON", 200)["ok"] is False
    validate_openapi(HERE / "tools.openapi.yml", HERE / "tools.openapi.json")
    policy = json.loads((HERE / "policy-pack.json").read_text())
    assert len(policy["scenarios"]) == 8 and len(policy["platforms"]) == 4
    print("通过：4个DSL图结构、变量引用、失败分支、Secret空值、X-Tool-Token认证、嵌入Python、JSON编码、多轮上下文、错误响应、长结果与工具输入。")
    print("本脚本不验证Dify云端导入、sandbox执行、公共HTTPS回调或真实模型调用；实际进度见docs/acceptance.md。")


if __name__ == "__main__":
    main()
