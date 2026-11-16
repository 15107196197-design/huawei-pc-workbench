# Dify 云端接入与发布

本项目的正式操作入口是自研图文工作台。Dify Chatflow 承担多轮入口、HTTP 编排、回复和会话上下文；产品事实、报价规则、图文生成、证据保存与核验在自研后端执行。主 Chatflow 里的“调用受控任务服务”是完整业务流水线入口，不能把它描述成九个已经分别接入云端的业务节点。

交付已完成本地 DSL 结构与嵌入代码验证；**尚未在用户 Dify 云端工作区实际导入，也未验证云端对公网后端的调用**。本地启动成功、YAML 可解析或 OpenAPI 合法，都不等于已完成这两项验收。

## 文件与作用

| 文件 | 使用方式 |
| --- | --- |
| `dify/huawei-pc-chatflow.yml` | 在 Dify Studio 导入为 Chatflow，正式业务入口使用此应用的 Service API |
| `dify/ima-search-workflow.yml` | 可单独导入、发布为资料检索 Workflow 工具 |
| `dify/quote-engine-workflow.yml` | 可单独导入、发布为确定性报价工具，输入来自渠道证据 |
| `dify/verify-workflow.yml` | 可单独导入、发布为图文核验工具 |
| `dify/tools.openapi.yml`、`dify/tools.openapi.json` | 相同 OpenAPI 3.0.3 定义的两种格式；可选一种导入自定义工具 |
| `dify/policy-pack.json` | 从后端实际策略生成的八场景、四平台与总控提示词快照 |
| `dify/prompts.md` | 总控和各业务节点的提示词边界、结构及迁移说明 |
| `dify/acceptance.md` | 场景、平台、报价、权限和完整状态流的验收记录表 |
| `dify/nginx-tools.conf.example` | 仅公开受控回调与工具路由的 HTTPS 反代模板，需替换域名、证书和本机端口 |
| `dify/nginx-studio.conf.example` | 配置单操作人登录后，整套工作台的 HTTPS 反代模板；不是多人权限系统 |

不必为了使用主 Chatflow 同时导入另外三个 Workflow。它们用于独立调试，或以后将完整业务流水线拆为更细的可视化编排；OpenAPI 自定义工具是另一种接入方式，不会自动安装到主流程中。

## 1. 准备公共后端与凭证

1. 先按项目 README 启动自研服务并完成本机功能验证。ima、DeepSeek、百炼等凭证只保存在后端配置中。
2. 为后端提供 Dify Cloud 能访问的、证书有效的公共 HTTPS 地址，例如 `https://agent-api.your-domain.example`。`http://127.0.0.1:8787`、`localhost` 和家庭局域网地址均不能作为云端的回调地址。
3. 在后端配置 `PUBLIC_API_BASE`，末尾不带 `/`；配置随机且足够长的 `TOOL_TOKEN`。通过受控配置界面、环境变量或本机 `.env` 保存，不在聊天、截图、DSL、代码仓库或日志中展示完整值。
4. 默认公网反向代理只开放需要的 `/api/dify/execute` 和 `/api/tools/` 路由；本机业务界面的设置、任务列表与文件管理不能直接作为无登录的公网管理界面发布。需要公开整套工作台时，先运行 `.venv/bin/python scripts/configure_access.py` 配置单操作人登录并启用 HTTPS；正式多人部署仍需用户隔离。
5. Dify Cloud 的 HTTP 请求将接触到本次需求与选中的资料片段。首次真实调用前确认所选资料可用于该云端工作区；不要把 ima 密钥或整库原文直接写入 Chatflow。

`TOOL_TOKEN` 是 **Dify 调用后端** 的凭证；`DIFY_API_KEY` 是 **后端调用 Dify** 的应用密钥；二者用途不同，不可混用。ima 和模型密钥不需要填入这份 DSL。

本交付统一使用 `X-Tool-Token` 承载回调凭证，兼容魔搭创空间对入站 `Authorization` 等请求头的限制。HTTP 节点选择 `no-auth` 仅表示不自动生成 `Authorization`，自定义请求头鉴权仍由后端强制执行。后端保留 Bearer 兼容；同时传入两个认证头时，两者都必须正确，不能以其中一个覆盖错误凭证。此项已做本地交付检查，Dify 云端导入和回调仍待真实验证。

如果采用 Nginx，可从 `dify/nginx-tools.conf.example` 开始配置。模板假设反代和后端位于同一台主机、后端监听 `127.0.0.1:8787`，实际端口应与项目启动命令一致；云服务器反代不能直接访问用户电脑的 `127.0.0.1`。模板没有申请证书或部署到任何服务器，必须由实际有域名、证书及目标主机访问条件的环境验证后生效。

任务创建、业务界面和 Dify 回调使用同一后端及数据库。不能将本机数据库的任务 ID 交给另一台服务器的独立数据库；迁移后从云端工作台或连接同一服务的受控隧道操作。

## 2. 导入主 Chatflow

1. 在已有 Dify 云端工作区进入 Studio，选择“导入 DSL 文件”，上传 `dify/huawei-pc-chatflow.yml`。创建独立应用，不覆盖已有业务应用。
2. 导入后检查应用类型为 Chatflow / `advanced-chat`。节点依次为：任务输入 → 安全编码请求 → 调用受控任务服务 → 解析结果与交付状态 → 保留本次任务上下文 → 回复与追问，另有连接失败分支。
3. 在环境变量中，将 `PUBLIC_API_BASE` 改为真实的公共 HTTPS 地址。将 `TOOL_TOKEN` 保持为 **Secret** 类型，填入与后端相同的凭证。交付文件中的 Secret 值为空；未配置时调用不会成功。
4. 打开 HTTP 节点，确认 URL 为 `{{#env.PUBLIC_API_BASE#}}/api/dify/execute`，认证类型为 `no-auth`，自定义请求头为 `X-Tool-Token: {{#env.TOOL_TOKEN#}}`，另保留 `Content-Type: application/json`，证书校验开启。不要再配置 `Authorization`。
5. 保持 POST 自动重试关闭，避免网络超时后重复生成、重复付费调用或重复保存版本。可以查看任务后再决定重试。
6. 主流程不直接配置 Dify 的 LLM 插件；实际文本和多模态模型由后端配置管理。只导入 DSL 不会自动获得 DeepSeek 或 Qwen 的可用凭证。

这份 DSL 使用 `0.6.0`，参照 Dify 官方当前 CLI 的 Chatflow 测试样例；查验时官方主分支的 DSL 常量为 `0.7.0`。用户工作区运行版本尚未读取，不能由主分支版本推断云端已支持所有新特性。若导入提示版本或资源问题，应保留具体错误，在该工作区导出空白 Chatflow 后对照结构迁移；不得通过删掉核验或鉴权节点来消除错误。

## 3. 正式入口与用户身份

自研后端调用 Dify 的 `/chat-messages`，并为已经创建的业务任务传入以下 `inputs`。下面均为占位符，没有真实凭证：

```json
{
  "query": "给即将入学的大学新生制作一篇小红书内容，先帮我确认软件适配",
  "inputs": {
    "task_id": "已有的后端任务ID",
    "user": "local",
    "context_token": "服务器按任务计算的HMAC签名",
    "action": "chat",
    "platform": "xiaohongshu"
  },
  "user": "稳定的业务用户标识",
  "conversation_id": "首轮留空，后续使用Dify返回的conversation_id",
  "response_mode": "blocking"
}
```

- 请求头 `Authorization: Bearer <DIFY_API_KEY>` 由服务器添加，浏览器不持有该应用密钥。
- 本地单用户模式的业务 owner 为 `local`。任务签名由服务器计算：`HMAC-SHA256(TOOL_TOKEN, user + ':' + task_id)`，使用十六进制摘要。用户不能通过手填名称和任务 ID 获得任务权限。
- Chatflow 将任务 ID、任务签名和业务用户保留在会话变量中。业务任务 ID 与 Dify 的 `conversation_id` 是两个不同标识；切换业务任务时需要同步切换 Dify 会话。
- `action` 为 `chat / generate / retrieve / verify`；平台值为 `wechat / xiaohongshu / moments / poster`。自然语言内容通过 `sys.query` 进入，不能额外创建名为 `sys.query` 的开始变量。
- Dify `sys.user_id` 是 Dify 内部用户标识，不能当成当前业务账号或 ima 账号名称。
- 未传业务任务时，DSL 只允许进入 `preview:<sys.user_id>` 预览命名空间。是否允许创建该预览任务由后端决定；预览身份无权读取 `local` 的任务。Dify 原始 WebApp 不作为正式登录界面发布。
- `context_token` 是任务专用签名，仍应限制工作区日志访问。`TOOL_TOKEN` 只在 HTTP 认证中以 Secret 引用，不进入代码节点参数与正文。

后端返回合同：

```json
{
  "task_id": "后端任务ID",
  "reply": "需要继续追问的信息或本次结果说明",
  "status": "后端真实业务状态",
  "result": {"id": "后端任务ID", "brief": {}, "draft": null, "checks": []}
}
```

解析节点仅把 `reply` 交给 Answer；保留 `task_id`、`status` 和精简的 `result_json`。完整原文、历史消息和证据仍在后端，业务界面根据已有任务读取。过大结果会被明确标记为 `truncated`，不会伪装成完整结构化交付。

HTTP 失败或无效 JSON 不生成替代事实、价格或成品。传输超时时，后端任务可能已经处理了一部分，应先在业务界面重新打开该任务查看状态。

## 4. 发布并配置后端

1. 在工作区完成预览与节点日志检查后发布主 Chatflow。
2. 在应用的“访问 API / API Access”页生成应用密钥，在后端配置 `DIFY_API_KEY`；`DIFY_BASE_URL` 使用该工作区 API 文档显示的地址（项目默认值为 `https://api.dify.ai/v1`，以实际工作区为准）。
3. 在业务界面选择 Dify 模式。先提交一个故意缺少目标人群的任务，确认从界面 → 本地代理 → Dify → 公共后端 → 同一业务任务的整个往返成功。
4. 检查后端任务 ID、owner、版本与 Dify 会话保持一致。失败时明确显示连接失败，不能退回其他模式后仍显示“Dify 已运行”。
5. 补全任务并执行生成；比较至少两个场景和四个平台，查看事实依据、图片来源、待确认项，再测试保存、取消、重开和导出。

## 5. 可选：导入独立业务工具

### 方式 A：Workflow 工具

三个独立 Workflow 各自导入后，同样配置 `PUBLIC_API_BASE` 和 Secret `TOOL_TOKEN`。测试通过后，可使用 Dify 的“发布为工具”功能供其他工作流调用。

| 工具 | 输入 | 后端行为 |
| --- | --- | --- |
| ima 检索 | `query`、可选 `model` | 检索指定 ima 库，返回来源与事实；失败不补造 |
| 报价 | `offers_json` 数组、`buyer_json` 对象、`region` | 由独立 Decimal 规则引擎计算；完整证据字段见 `docs/pricing.md` |
| 核验 | `draft_json`、`facts_json`、`assets_json`、`quotes_json`、`platform` | 运行当前事实关联、图片型号、价格与表达规则；保留未执行语义核验的状态 |

正常输出为 JSON 字符串 `result` 与布尔 `ok`；连接失败分支为 `error_result` 与 `error_ok`，以符合多 End 节点输出名唯一的要求。调用方必须读取失败分支，不能只判断请求是否获得 HTTP 200。

### 方式 B：OpenAPI 自定义工具

1. 复制 `dify/tools.openapi.yml` 或 JSON 版本到受控配置位置，把 `servers[0].url` 从 `.invalid` 占位地址改成真实公共地址；此处不是 Dify 环境变量替换语法。
2. 在 Dify“工具 → 自定义工具”导入定义，认证配置选择 API Key 自定义 Header，名称为 `X-Tool-Token`，值填写后端的 `TOOL_TOKEN` 原值，不加 `Bearer ` 前缀。OpenAPI 已声明此请求头；不要改用平台保留的 `Authorization`。
3. 分别测试搜索、空报价列表以及缺少事实的核验，确认鉴权、中文传输与错误结果。
4. 确定性工具的输入应由证据采集程序或已确认的业务数据组织。LLM 不能因为想得到低价而将 `verified` 改为 true，或自行填写优惠金额、身份资格、来源与有效期。

报价引擎只会计算传入证据，不会凭空联网取得七个渠道的结算价。额外渠道信息必须通过已实现的搜索、平台接口或带时间的人工记录获取；没有验证的数据不能进入已核实最低价排序。

## 6. 重新生成与本地校验

更新后端平台/场景规则后，重新生成交付快照：

```sh
.venv/bin/python dify/build_delivery.py
.venv/bin/python dify/validate_delivery.py
```

本地校验覆盖图连通、变量引用、失败分支、嵌入 Python、Secret 空值、`X-Tool-Token` 请求头与 OpenAPI 认证一致性、输入 JSON 编码、会话 ID/签名保留与错误响应。它没有 Dify 工作区凭证，不执行 Dify 官方导入服务，也不验证沙箱与公共网络。

重新导出 Dify 应用时，取消包含 Secret 实际值；先检查再交付。平台写作规则与官方发布规则分开维护，`policy-pack.json` 是本项目内容策略，不等于平台官方统一规定。

## 官方依据与查验范围

以下页面与源码在 2026-10-19 查验，仅支持相应配置与格式事实；不是用户工作区已部署的证据。

- [Dify 应用导入导出](https://docs.dify.ai/en/cloud/use-dify/workspace/app-management)：DSL 内容、导入和 Secret 导出选项。
- [Dify HTTP 节点](https://docs.dify.ai/en/cloud/use-dify/nodes/http-request)：HTTP、Bearer、超时、Secret 日志遮罩与失败处理。
- [Dify Code 节点](https://docs.dify.ai/en/cloud/use-dify/nodes/code)：输入输出和沙箱边界；网络调用放在 HTTP 节点。
- [Dify Chatflow Service API](https://docs.dify.ai/en/api-reference/guides/chatflow)：会话、API 和工作流级事件。
- [官方 Chatflow e2e 样例](https://github.com/langgenius/dify/blob/main/cli/test/e2e/fixtures/apps/echo-chat.yml)：`advanced-chat`、DSL 0.6.0、图结构和开始变量。
- [官方 HTTP 工作流样例](https://github.com/langgenius/dify/blob/main/api/tests/fixtures/workflow/http_request_with_json_tool_workflow.yml)：HTTP 节点与输出选择器。
- [官方 HTTP 节点构建定义](https://github.com/langgenius/dify/blob/main/api/core/workflow/generator/prompts/builder_prompts.py)：`no-auth` 与自定义 Headers 字段结构。[魔搭 Docker 应用要求](https://github.com/modelscope/modelscope-skills/blob/main/skills/ms-studio-deploy/references/docker-templates.md)：入站保留头限制。
- [官方会话变量样例](https://github.com/langgenius/dify/blob/main/api/tests/fixtures/workflow/test_streaming_conversation_variables.yml)：会话变量与 Assigner v2。
- [官方当前 DSL 版本常量](https://github.com/langgenius/dify/blob/main/api/constants/dsl_version.py)、[官方 DSL 构建参考](https://github.com/langgenius/dify/blob/main/skills/difyctl/references/build-workflow/dsl.md)：版本与失败分支结构检查。
