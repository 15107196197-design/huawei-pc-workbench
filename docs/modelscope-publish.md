# 魔搭评审展示页发布与核验

本项目在魔搭创空间发布只读成果展示页，展示功能、架构、提示词设计、真实文章、海报和作品说明书；页面不连接本机后台，不提供付费模型推理入口，也不配置 ima、DeepSeek 或百炼密钥。

- 创空间入口：<https://modelscope.cn/studios/A1211JOY/huawei-pc-content-studio>
- 实际应用地址：<https://a1211joy-huawei-pc-content-studio.ms.show>
- 说明书地址：<https://a1211joy-huawei-pc-content-studio.ms.show/docs/manual.pdf>

实际应用地址以官方元数据接口返回的 `data.host` 为准。创空间外层页面返回 HTTP 200，不能单独证明应用及附件已经可访问。

## 发布目录与约定

官方当前支持 Gradio、Streamlit、Docker、Static。这里采用 `sdk_type=static`，入口为仓库根目录 `index.html`。Static 不运行构建步骤，因此上传的是已经生成的网页、脚本、样式、JSON、图片和 PDF，不上传 Python 构建脚本、后台源码或运行数据。不需要为这个展示页配置 GPU、模型 API 或自行填写硬件规格。

发布助手从 `review-site/` 收集固定白名单：根目录 `index.html`、`app.js`、`styles.css`、`config.json`、`README.md`，以及 `assets/`、`docs/` 中支持的展示文件。构建脚本留在 GitHub 源码仓库。请先完成说明书和脱敏素材生成，再发布静态目录。

创空间仓库使用 `master` 分支。本项目显式传 `revision="master"`，把 `review-site/` 中的内容上传到仓库根，而不是再套一层 `review-site` 目录。官方当前 Static 约定是根目录 `index.html`；未发现要求另配 `app_file`、自定义 entrypoint 或 `ms_deploy.json` 的规定。Docker 的 `7860` 端口规则不用于本页。

## 本机一次性授权与发布

发布工具与工作台运行依赖分开安装：

```bash
uv venv output/publish-env --python .venv/bin/python
uv pip install --python output/publish-env/bin/python modelscope-hub==0.4.0
.venv/bin/python scripts/publish_review.py
```

打开 <http://127.0.0.1:8790/>，在密码框填写用户自己的写权限 Token。令牌仅保存在当前发布进程内存中，配置操作只调用官方身份查询；表单提交即清空。发布助手不读取浏览器 Cookies，不调用会持久化凭证的 SDK `login()`，不把令牌写入 URL、Git remote、浏览器存储或仓库。ModelScope 和 GitHub 的认证连接绕过环境代理，保留 TLS 校验。

身份验证后，协调进程另行调用发布动作。先 GET 本机 `/`，取响应头 `X-CSRF-Token`；POST 请求同时提供该头以及 `Origin: http://127.0.0.1:8790`。

```text
POST /api/actions/modelscope/publish
Content-Type: application/json

{"slug":"huawei-pc-content-studio"}
```

助手只创建新的 `static/public` 创空间。已经存在、但不是当前进程刚创建的空间会被拒绝覆盖；同一进程内可以重新发布本次创建的空间。进程关闭后授权和本次创建记录都消失。`deployment_requested=true` 表示上传及部署请求已提交，仍需进行下述运行核验。

源码仓库采用单独动作，避免未经检查直接上传：`/api/actions/github/create` 创建新 public 仓库，`/api/actions/github/prepare` 返回文件清单和 `manifest_sha256`，检查后再调用 `/api/actions/github/upload` 并传入相同摘要。源码变化、远程分支变化、非本次创建的既有仓库都会阻断上传。

## 官方状态接口

公开或应用公开的创空间可以匿名查询元数据：

```text
GET https://modelscope.cn/openapi/v1/studios/A1211JOY/huawei-pc-content-studio
```

读取 `data.status`、`data.runtime.status` 与 `data.host`。`Building` 表示仍在构建，不能当作已经可用；发布后的最终验收还应检查页面内容和资源。不要通过反复部署代替等待构建结果。

官方 SDK 0.4.0 的 `api.get_repo(repo_id, repo_type="studio")` 保留 `runtime` 字段，但其 `RepoInfo` 数据类型没有顶层 `host` 和 `status` 字段。需要实际应用地址时，可在已经授权的 SDK 对象上调用：

```python
metadata = api.openapi.get_studio("A1211JOY", "huawei-pc-content-studio")
host = metadata.get("host")
runtime = metadata.get("runtime")
```

也可以直接使用下面的匿名 HTTP 核验方式，不构造默认 SDK 客户端、不接触本机已有授权。

## 匿名页面与附件核验

以下脚本只发送公开 GET 请求，不使用 Token、现有 Cookies 或环境代理，不触发部署。应在部署状态就绪后运行；重新发布页面时重新比对附件摘要。

```python
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse
import httpx

metadata_url = "https://modelscope.cn/openapi/v1/studios/A1211JOY/huawei-pc-content-studio"
paths = ["index.html", "app.js", "styles.css", "config.json", "docs/manual.pdf",
         "assets/poster.png", "assets/poster.pdf", "assets/article-json.json",
         "assets/article-zip.zip"]

with httpx.Client(trust_env=False, timeout=25, follow_redirects=False) as client:
    response = client.get(metadata_url)
    response.raise_for_status()
    metadata = response.json()["data"]
    print("deployment_status:", metadata.get("status"))
    base = metadata["host"].rstrip("/") + "/"
    assert urlparse(base).scheme == "https"
    assert urlparse(base).hostname.endswith(".ms.show")
    for path in paths:
        response = client.get(urljoin(base, path))
        response.raise_for_status()
        remote = response.content
        local = Path("review-site", path).read_bytes()
        assert hashlib.sha256(remote).digest() == hashlib.sha256(local).digest(), path
        if path.endswith(".pdf"):
            assert remote.startswith(b"%PDF-"), path
        if path.endswith(".png"):
            assert remote.startswith(b"\x89PNG\r\n\x1a\n"), path
        if path.endswith(".zip"):
            assert remote.startswith(b"PK\x03\x04"), path
        print(path, response.status_code, len(remote), "matches_local")
```

另外检查应用首页和 `index.html` 均可访问、`config.json` 的 GitHub/魔搭/说明书入口与 README 及说明书一致、正文示例与图片能正常显示、PDF 可阅读、ZIP 可解压。HTTP 状态和摘要证明资源交付一致；界面交互与 PDF 排版仍需单独打开核验。

## 日志与异常诊断

SDK 支持以下只读日志接口。日志通常要求账号读取权限；不要为了查日志把令牌贴到聊天、命令行参数或公开文件。

```python
# api 是当前进程中已经通过用户授权的 SDK 对象。
logs = api.get_repo_logs(
    "A1211JOY/huawei-pc-content-studio", repo_type="studio",
    log_type="build", page_num=1, page_size=50,
)
```

对应官方 HTTP 接口为：

```text
GET /openapi/v1/studios/{owner}/{repo_name}/logs/build?page_num=1&page_size=50
GET /openapi/v1/studios/{owner}/{repo_name}/logs/run?page_num=1&page_size=50
```

`log_type` 仅允许 `build`、`run`，每页最多 500 条。响应包含 `logs`、`page_num`、`page_size`、`total_count`、`total_page_num`，支持 `keyword`、`start_timestamp`、`end_timestamp`。Static 页面没有自研后台推理进程，因此不应以没有业务运行日志推定页面故障；先核查元数据状态、上传分支、根目录入口与公开资源响应。

常见定位顺序：确认 SDK 类型仍是 Static；确认 `master` 根目录有 `index.html`；确认静态构建产物和 PDF 已上传；查询构建状态或日志；最后检查实际 `data.host` 下的文件响应。构建期间返回的应用 404 不应被记录为已上线成功。

## 访问可用性的边界

官方说明免费资源配额有时间限制，未给出本页 Static 类型的确定休眠时长或评审期 SLA。静态展示减少了付费模型接口和后台进程的依赖，但不能由项目方保证平台绝不发生中断。保留同版 GitHub 源码、说明书和样例作为备用材料；提交前及需要展示时重新进行匿名资源核验。

## 官方依据

- [ModelScope 官方创空间部署指南](https://github.com/modelscope/modelscope-skills/blob/main/skills/ms-studio-deploy/SKILL.md)：四种 SDK、Static 入口、master 分支、部署与配额边界。
- [官方 Studio OpenAPI 参考](https://github.com/modelscope/modelscope-skills/blob/main/skills/ms-studio-deploy/references/openapi-studio-endpoints.md)：元数据、日志、创建及部署接口。
- [ModelScope Hub 官方 SDK](https://github.com/modelscope/modelscope_hub)：独立安装、权限和 CLI/API 入口。
- [官方 SDK RepoInfo 与 runtime 数据类型](https://github.com/modelscope/modelscope_hub/blob/main/src/modelscope_hub/types.py)：SDK 返回值保留字段。
- [官方 OpenAPI 客户端实现](https://github.com/modelscope/modelscope_hub/blob/main/src/modelscope_hub/_openapi.py)：公开元数据读取与日志分页参数。

## 本次公开访问验收

官方元数据状态为 `Running`，可见性为 `public`。以不携带 Cookie 或 Authorization 的 HTTP 客户端读取全部 21 个发布文件，均返回 HTTP 200，SHA256 与本地发布文件一致；包括首页、JS/CSS、配置、说明书 PDF、三分钟脚本、文章便携 ZIP、海报 PNG/PDF。浏览器自动化对外部页面连接超时，因此此项记录的是公开 HTTP 与文件一致性验收，不声称完成了发布后浏览器交互验收；对应静态页面交互已在本地预览中验证。
