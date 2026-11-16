# 连接设置：填什么、按什么顺序

查验日期：2026-10-19。密钥在工作台的密码框中填写，不发送到聊天，也不截图展示完整值。留空表示保留已经保存的密钥。

先接通 DeepSeek 与北京百炼；**这两把 Key 已能覆盖文本、图片、视觉核验与联网线索搜索**，Tavily 可不填。公网后端和域名准备好后，再接 Dify。Dify 工作区订阅、DeepSeek 账户和百炼账户分别管理余额与权限，不共用密钥。

## 1. 获取 DeepSeek 密钥

1. 打开 [DeepSeek API 开放平台的 API Keys](https://platform.deepseek.com/api_keys)，登录并创建用于此项目的密钥。
2. 在工作台右上角“连接与设置”，填入“DeepSeek API Key”。
3. “文本模型”填 `deepseek-flash`。DeepSeek API 地址使用 `https://api.deepseek.com`。
4. 保存后点击 DeepSeek 的“测试连接”。连接成功只能证明当前凭证/接口可用；还需要生成一次小任务，确认结构化内容正常。

当前官方文档推荐 `deepseek-flash`，不要沿用旧教程中的 `deepseek-chat`。官方已公告旧别名于 2026-07-24 停止使用。[首次调用](https://api-docs.deepseek.com/zh-cn/)、[更新日志](https://api-docs.deepseek.com/zh-cn/updates/)

## 2. 获取北京百炼密钥

1. 打开 [百炼 API Key 页面](https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key)，右上角确认地域为 **华北2（北京）**。
2. 选择或创建本项目使用的业务空间，在该空间创建 API Key，并确认该空间有要调用模型的权限。Key、业务空间接入域名和模型地域必须匹配。
3. 将 Key 填入工作台“阿里云百炼 API Key”；同一个有相应权限的北京 Key 可以用于视觉理解和图片生成，不必分别创建两个。
4. “视觉理解模型”填 `qwen3-vl-plus`；“图片生成模型”填 `qwen-image-2.1-pro`。
5. “百炼服务地址”先使用 `https://dashscope.aliyuncs.com`。若使用官方推荐的业务空间专属域名，则填 `https://你的WorkspaceId.cn-beijing.maas.aliyuncs.com`；`WorkspaceId` 从百炼业务空间详情复制，不能把中文占位符原样填入。
6. 保存后分别测试 Qwen 视觉和 Qwen-Image；正式图像生成测试会产生对应模型调用费用。

**工作台的“百炼服务地址”只填域名根地址**，不要再附加 `/compatible-mode/v1`、`/api/v1` 或模型路径，代码会自动补齐。官方通用示例里的完整 OpenAI 兼容 Base URL 是 `.../compatible-mode/v1`，它与本项目这个字段的含义不同。官方表示旧 `dashscope.aliyuncs.com` 域名仍可使用，专属域名为推荐迁移方案。[Key 与地域说明](https://help.aliyun.com/zh/model-studio/get-api-key)、[接口与域名说明](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)

`qwen3-vl-plus` 的官方模型页明确列出北京地域、图片输入与结构化输出；它负责辅助检查图片和文字，不生成海报背景。`qwen-image-2.1-pro` 用于当前实现的背景生成；产品主体仍来自 ima 原图。[视觉模型能力](https://help.aliyun.com/zh/model-studio/qwen3-vl-plus)、[图像生成 API](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)

当前图像实现使用 DashScope 异步协议：创建任务 `POST /api/v1/services/aigc/image-generation/generation`，请求头 `X-DashScope-Async: enable`，再以 `GET /api/v1/tasks/{task_id}` 查询。不要把同步接口的 `/multimodal-generation/generation` 地址套进异步调用。

## 3. 部署后填写公网地址与工具 Token

1. 完成服务器、DNS 与 HTTPS 后，将真实根地址填入“公网业务 API 地址”，例如 `https://agent-api.你的真实域名`；末尾不带 `/`。
2. 为后端生成独立、足够长的随机“Dify 工具调用 Token”，安全保存于服务端。它不是 DeepSeek、百炼或 Dify 应用 API Key。
3. 该 Token 的同一份值还要写入 Dify Chatflow 的 Secret 环境变量 `TOOL_TOKEN`。不要写进代码、自然语言输入或聊天。
4. 如果尚未部署公网后端，这两项和 Dify 项可以暂不填写；本地模型功能的验证可以先继续。

**Dify 回调与业务界面必须使用同一套后端和数据库。** 部署至云服务器后，应从云端那套工作台创建任务并让 Dify 回调同一云端服务；或者由受控隧道访问那套云端工作台。不能在本机 A 库创建任务，却把回调地址指向云端 B 库，否则会返回“任务不存在”。迁移时需要一起转移业务数据及安全配置，不是在两边各运行一套就自动同步。

若准备通过公网访问整个工作台，先在服务器运行 `.venv/bin/python scripts/configure_access.py` 设置单操作人登录，再配置 HTTPS；该脚本交互输入密码并只保存加盐哈希。只公开回调与工具时，可继续通过 SSH 隧道管理工作台；工具 Bearer 凭证和工作台登录密码彼此独立。

服务器与域名建议见 `docs/cloud-options.md`。

## 4. 导入并连接 Dify

1. 在现有云端工作区进入 Studio → 导入 DSL，选择 `dify/huawei-pc-chatflow.yml`，创建独立 Chatflow。
2. 进入应用环境变量，`PUBLIC_API_BASE` 填上一节的真实公网根地址；`TOOL_TOKEN` 保持 **Secret** 类型，填同一份工具 Token。
3. 核对 HTTP 节点调用 `{{#env.PUBLIC_API_BASE#}}/api/dify/execute`，Bearer 认证引用 `{{#env.TOOL_TOKEN#}}`。
4. 发布应用。进入这个应用的“访问 API / API Access / Service API”页，从应用内创建 API Key。不要拿工作区知识库 API Key 代替应用 Key。
5. 回到工作台：“Dify Service API 地址”填 `https://api.dify.ai/v1`（若你的工作区 API 页显示其他地址，以页面为准）；“Dify 应用 API Key”填上一步的应用密钥。
6. 保存、测试 Dify 连接，再从工作台提交一轮需求并补充第二轮。以同一任务获得追问、保存状态及结果，验证真正的双向往返。

`https://api.dify.ai/v1` 是工作台调用 Dify 的地址；`https://agent-api.你的真实域名` 是 Dify 回调本项目的地址。这两个地址不相同。[Dify 官方接入说明](https://docs.dify.ai/en/api-reference/guides/get-started)

## 字段速查

| 工作台字段 | 应填内容 |
| --- | --- |
| DeepSeek API Key | DeepSeek API 开放平台创建的项目密钥 |
| 文本模型 | `deepseek-flash` |
| 阿里云百炼 API Key | 华北2（北京）、对应业务空间的 Key |
| 百炼服务地址 | `https://dashscope.aliyuncs.com`；或真实 Workspace 专属域名根地址 |
| 视觉理解模型 | `qwen3-vl-plus` |
| 图片生成模型 | `qwen-image-2.1-pro` |
| 公网业务 API 地址 | 已部署且可从 Dify Cloud 访问的真实 HTTPS 根地址 |
| Dify 工具调用 Token | 自研后端与 Dify Secret `TOOL_TOKEN` 共用的独立随机凭证 |
| Dify Service API 地址 | `https://api.dify.ai/v1`，以工作区 API 页为准 |
| Dify 应用 API Key | 已发布主 Chatflow 内创建的应用 Key |
| Tavily 联网检索 API Key | 可以留空；当前版本优先复用 DeepSeek Key 搜索，仅无 DeepSeek Key 时使用 Tavily |

## 联网检索的配置边界

当前实现优先复用 DeepSeek Key 调用原生 Search；只在没有 DeepSeek Key 时使用已配置的 Tavily，并非 DeepSeek 请求失败后悄悄自动切换。保存配置后仍须测试实际搜索成功，不能把“密钥已配置”当成“已联网”。

DeepSeek Search 返回网页线索，不能替代商家结算价与资格核验。直接 API 的搜索与抓取各为 5 元/千次成功且有结果的请求；本项目不能套用 DeepSeek Harness 等特定入口的临时免费政策。[官方 Search/Fetch 文档](https://api-docs.deepseek.com/zh-cn/guides/search/)

搜索未配置时，仍可导入有来源与时间的商家报价。不要让模型填充未知优惠金额、库存或补贴资格。
