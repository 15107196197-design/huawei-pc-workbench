# 华为 PC 图文工作台 · 第二版独立副本

本目录基于第一版当前文件复制开发，原目录与第一版线上应用保持独立。第二版仅新增需求理解、候选匹配和卖点证据链；原平台策略、报价、图像、登录及 Dify 接入沿用。

[打开第二版工作台](https://a1211joy-huawei-pc-agent-app-v2.ms.show) · [第二版创空间](https://modelscope.cn/studios/A1211JOY/huawei-pc-agent-app-v2?mode=full) · [第二版验收与限制](docs/v2-acceptance.md)

第二版当前发布修订：`25f58ad2a5d70ccbf15d42cc1c82bbf19c0f83ed`。登录账号由部署者自行设定，密码通过平台私有 Secret 设置，不保存在说明或源码中。下方保留的原部署与成果说明均为第一版历史记录；第二版验证以单独验收记录为准。

## 源码与许可

- **许可证**：[Apache-2.0](LICENSE)。
- **源码仓库**：<https://github.com/15107196197-design/huawei-pc-workbench>（`v2.0` 标签对应本次发布修订）。
- **Dify 画布版（同项目另一条路线）**：<https://github.com/15107196197-design/huawei-pc-dify-flow> —— 112 节点画布快照 + 5 份可直接导入 Dify 的 DSL，以及配置手册 `docs/HOW-TO-CONFIGURE.md`。
- **验收证据**：[docs/verification/](docs/verification/README.md) 收录测试演进日志（195→338 项）、发布清单、独立验收审查与前端流程回归；完整 309 个过程快照不随仓库发布。
- **本机运行**：`cp .env.example .env` 后填入自己的 Key，`docker compose up` 或按[部署说明](docs/full-app-deployment.md)启动。`data/` 与 `output/` 是运行时产物，已在 `.gitignore` 中排除。
- **前端零构建**：不需要 Node.js，页面直接由后端渲染；仅表单行为回归需要 `node tests/*.mjs`。

# 华为 PC 图文工作台

面向杭州华为 PC 运营场景的图文 Agent：可接入 Dify 云端编排，自研 Python 后端负责 ima 证据、生成、报价规则、图层合成和版本留档。前端不需要 Node.js 或构建步骤。

## 完整在线应用

[打开完整工作台](https://a1211joy-huawei-pc-agent-app.ms.show) · [魔搭应用空间](https://modelscope.cn/studios/A1211JOY/huawei-pc-agent-app) · [登录、使用与部署说明](docs/full-app-deployment.md)

**当前状态：完整应用已发布，云端接口及实际重启恢复已验证，浏览器登录由用户实际网页登录确认通过。** 用户已明确确认“已进入工作台”。已通过官方 API 网关实际执行登录、ima 检索、文章生成与搜索、改稿重开、海报背景与核验及各格式导出；重启后任务和 PNG/PDF 哈希保持一致。浏览器确认范围为登录进入，未将全部云端按钮标为自动化端到端通过。下方静态成果展示页继续保留。

这是带登录的单操作人工作台，使用同一账号的授权操作者共享任务。部署者可在本机[完整应用发布页](http://127.0.0.1:8791/)验证发布授权后复制登录名和密码；请自行保存，不把密码写进仓库、说明书或聊天。云端模型和 ima 配置由平台私有 Secret 管理，工作台不开放修改。免费 CPU 资源与外部模型费用分别计算，真实模型和搜索调用仍按对应账号规则计费。


2026-10-20 修复需求保存：适配魔搭网关的 POST 写入入口，编辑窗口内显示保存进度与错误，失败保留输入并允许重试；新增 3 项后端回归及 `node tests/brief_flow.mjs` 表单行为回归。详见[验收记录](docs/acceptance.md)。

## 作品材料与演示

- [魔搭公开项目页](https://modelscope.cn/studios/A1211JOY/huawei-pc-content-studio)：已发布为公开静态创空间，22 个公开文件已通过匿名访问与哈希核验；可打开[成果展示站](https://a1211joy-huawei-pc-content-studio.ms.show)、下载[说明书 PDF](https://a1211joy-huawei-pc-content-studio.ms.show/docs/manual.pdf)及查看[三分钟演示脚本](https://a1211joy-huawei-pc-content-studio.ms.show/docs/demo-script.html)。页面只读展示已生成成果，不提供在线生成或共享调用凭证。
- [作品说明书](docs/作品说明书.md)：功能、真实运行结果、架构、提示词、ima 调用、部署和已知限制。
- [3 分钟全流程演示脚本](docs/三分钟演示脚本.md)：按 180 秒安排口播、屏幕操作和检查点。
- [公开展示页源码](review-site/README.md)：纯静态展示真实成果，不开放付费模型调用。展示页包含说明书 PDF、演示脚本与可下载的真实文章、海报。
- [材料状态清单](docs/submission-manifest.json)：三份材料共用的功能与验证状态；公开链接以实际发布后的记录为准。

**GitHub 源码仓库仍待发布，当前没有可提交的仓库链接。** Dify Cloud 导入和公网后端回调也仍待独立联调，不能用静态展示页的发布代替。

本地预览展示页：`python3 -m http.server 8788 --directory review-site`，然后访问 <http://127.0.0.1:8788>。它与下方完整工作台分别运行。

## 可选：重新构建说明书 PDF

已交付的 PDF 可以直接阅读。只有修改说明书后才需要运行文档构建工具，构建不调用模型，也不需要 Word、LibreOffice 或 `python-docx`。

在选定的 Python 环境中安装文档工具所需的 ReportLab、Pillow，以及用于构建后内容检查的 pypdf，再执行：

```sh
python -m pip install "reportlab>=4" "Pillow>=11" "pypdf>=5"
python scripts/build_manual_pdf.py
```

正文来自 `docs/作品说明书.md`，输出为 `output/submission/作品说明书.pdf`。脚本直接嵌入支持中文的 TrueType 字体。macOS 默认使用系统 `Arial Unicode.ttf`；其它系统通过 `MANUAL_FONT` 指定已有授权的中文 TrueType `.ttf`，例如：

```sh
MANUAL_FONT=/path/to/CJK-font.ttf python scripts/build_manual_pdf.py
```

不要依赖没有嵌入字体的替换渲染。字体需覆盖正文中的中文、拉丁字母和符号；构建后仍应渲染 PDF 并逐页检查，不能仅以文字提取成功验收。字体文件不随仓库分发。

架构图已提交在 `docs/assets/architecture.png`，PDF 构建可以直接使用。只有修改架构时才需运行 `python scripts/build_architecture.py`；该工具使用 Pillow，可通过 `--font /path/to/CJK-font.ttf` 或同一个 `MANUAL_FONT` 选择字体。文档工具的安装步骤不增加核心启动要求，完整应用仍按下方方法运行。

## 本机启动

双击 `启动工作台.command`，或在项目目录运行：

```sh
sh scripts/start.sh
```

默认访问 <http://127.0.0.1:8787>。端口被占用时：`STUDIO_PORT=8788 sh scripts/start.sh`。

依赖管理使用 `uv sync`；没有 uv 时启动脚本会创建 Python venv 并安装依赖。Python 3.11 以上。

## 能力和真实状态

- 对话补全需求、需求卡编辑、八类场景和四平台的不同策略。
- 按型号读取指定 ima 库已接入档案中的产品事实、参数限制和原图索引，保留来源。
- DeepSeek 生成与辅助审校；Qwen 视觉核验；Qwen-Image 仅生成背景。
- DeepSeek Search 联网查找价格线索，Tavily 为可选备用；搜索结果不自动成为已核实价格。
- 独立 Decimal 报价引擎：互斥、门槛、顺序、身份、国补、回收款、商品状态及服务条件分别处理。
- 图文预览、人工修改、图片编排、保存取消、历史重开和版本恢复。
- 四部分报告及 TXT/HTML/JSON/ZIP 导出；海报 PNG/PDF 原图独立贴层，不重绘产品。

未配置文本模型时，界面明确显示“规则草稿”。规则模板用于验证链路，不冒充模型创作。价格线索和未知资格不会自动成为最低可得价。核验阻断时只允许导出 JSON/审核报告。

本地已实测图形界面的需求追问、人工编辑、保存/取消/重开、剪贴板及文件导出。新增云端接口实测：检索 13 条事实，文章实际引用 4 条并配 3 张原图；DeepSeek Search 返回 12 条未核实线索；海报使用 1 张 ima 原图与实际 Qwen-Image 背景，视觉核验和渲染一致性通过，文章四格式及海报 PNG/PDF/JSON/报告接口返回成功，实际重启后任务和媒体恢复一致。自动化主测试 192 项、部署启动器 13 项通过，DSL 结构校验通过；真实接口运行另行留档。用户实际网页登录确认已进入工作台；全部云端控件尚未逐一完成浏览器自动化端到端验证。Dify Cloud、店铺接口和最低到手价仍无已验证结论。详情见 [验收记录](docs/acceptance.md) 与 [完整应用部署状态](docs/full-app-deployment.md)。

## 配置

本地运行时，打开“连接与设置”配置 DeepSeek / 百炼。密钥仅发送到本机后端；不回显、不写入浏览器存储。项目私有配置在被 Git 忽略的 `data/settings.json`，权限为 600。也支持 `.env`，字段见 `.env.example`。魔搭托管应用由部署者通过平台私有 Secret 注入配置，界面的配置项只读。

ima 只读取既有的环境变量或 `~/.config/ima/client_id`、`~/.config/ima/api_key`，不会复制到项目配置。

模型初始配置（2026-10-19 官方文档核对）：

| 字段 | 初始值 |
|---|---|
| 文本模型 | `deepseek-flash` |
| DeepSeek 地址 | `https://api.deepseek.com` |
| 视觉模型 | `qwen3-vl-plus` |
| 图片模型 | `qwen-image-2.1-pro` |
| 百炼服务地址 | `https://dashscope.aliyuncs.com`，北京地域的域名根地址；也可配置业务空间专属域名 |

模型、地域、密钥和服务地址必须匹配。免推理连接测试不证明该模型在账号中可用；实际任务单独验证。

只有 Dify API Key、工具 Token 和公网业务地址都配置后才启用 Dify 编排。详细步骤见 [Dify 接入](docs/dify-setup.md) 和 [配置指南](docs/connection-guide.md)。

## 报价输入

在“报价方案”导入实际报价 JSON，或用联网查询寻找证据后补齐报价字段。完整契约见 [报价引擎说明](docs/pricing.md)。

必须绑定具体卖家、SKU、商品状态、发票保修等服务条件、时间、运费和来源。闲鱼二手、已激活与全新未激活分开比较；小红书笔记和微信群宣传不是已确认交易报价。国补规则由输入证据给定，不内置一个永久有效比例。

## 服务器部署

适合单个操作人的版本，业务状态存 SQLite；不适合直接以多实例共享本地 SQLite 部署。

1. 复制 `.env.example` 为 `.env`，填写该服务器自己的配置。
2. 设置工作台登录账号：`uv run python scripts/configure_access.py`。只保存密码加盐哈希。
3. 凭证只配置到服务端。ima 凭证通过部署环境注入，不放源码、镜像或公开静态文件。
4. `docker compose up -d --build`，或使用 systemd 运行 `scripts/start.sh`。源码提供 Docker 配置，当前开发机没有 Docker，镜像未在本机运行验证。
5. 通过带 TLS 的反向代理提供 HTTPS，应用端口只绑定回环。`dify/nginx-tools.conf.example` 是只暴露已鉴权工具接口的模板。
6. 如果业务界面也在服务器提供，先设置工作台登录并为全站配置 HTTPS，再参考 `dify/nginx-studio.conf.example`；不要直接把无登录的应用端口公开。
7. Dify 回调与业务界面必须使用同一后端和数据库。不要让本机界面指向一套数据库、云端 Dify 回调指向另一套数据库。

Docker bind mount 的 `data/` 需允许容器 UID 10001 写入；目录权限只开放给对应服务账号。服务器登录名会显示在工作台身份区，ima 的连接身份另外展示。

## 检查

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python dify/validate_delivery.py
.venv/bin/python deploy/modelscope/test_runtime.py -v
```

单元/集成测试会隔离数据库与外部调用，不产生真实模型费用。真实来源与浏览器验收记录见 `docs/acceptance.md`。

可选的前端登录回归使用 Node.js 18 及以上：

```sh
node tests/login_flow.mjs
```

该脚本检查 4 个登录分支，不联网、不等同于浏览器端到端验收，也不计入上述 Python 测试数量。Node.js 仅用于这项开发检查，运行完整工作台仍只需 Python 环境。

## 数据和交付边界

`data/` 包含任务、版本、凭证配置及媒体缓存，不进入 Git 或发布包。定期备份 SQLite 和媒体文件，备份文件也按私有业务数据管理。当前不自动发布到公众号、小红书或商家账号；输出由操作者预览、核验后导出。
