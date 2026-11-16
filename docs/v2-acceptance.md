# 华为 PC 图文工作台 V2 验收记录

记录日期：2026-10-20（Asia/Shanghai）。本文件是第二版新增验收记录，不覆盖第一版历史说明或验收结论。

**第二版已独立上线，最终修订 `25f58ad2a5d70ccbf15d42cc1c82bbf19c0f83ed`。338 项主测试、13 项部署测试、2 项 JS 流程及 Dify 本地结构校验通过；新账号 `pcadmin` 登录接口已实测，最终 A 任务 r18、候选/卖点证据清理、复制与 HTML 接口均已独立读取核对。** 原需求未要求先补型号、预算或软件；示例后来两处人工收窄如实保留，不称为完全未经编辑的自动成稿。

仍有三个边界：云端浏览器完整业务 UI 未验；末次 retrieve 返回 504，但随后完整 GET 200 证明 r18 实际持久化成功；5 个 ima 图片目录曾返回 403，可读证据继续使用。报价、AI 图片/视觉和 Dify Cloud 本次未重复真实联调。

## 1. 版本、范围与保全

- V2：[独立创空间](https://modelscope.cn/studios/A1211JOY/huawei-pc-agent-app-v2)。修订顺序分开记录：

| 修订 | 归属与验收状态 |
| --- | --- |
| `b21068a7ceb97972905782640cf418d6e9902aee` | 首个部署修订，Running；真实业务结果发现两类证据缺口，未通过，不覆盖原始失败 |
| `d0657aa4d4f05bc76fa1af014efaba69f6d5b4e2` | 中间上传修订，后续又追加 L 的数字形态守卫；不是最终验收或最终发布版本 |
| `056386f17cbde187966de2e33e9b7dc6934cc2ac` | 已归档前修订；云端正文及交付接口已核对，r11 完整候选/卖点计划仍有缺口，未通过全链验收 |
| `1722917ce6dc639ab7079682b9f37d777296c718` | 前修订，r15 缓存清理持久化通过，但另发现 USB 形态/包装相关缺口；对应当时 327 项回归 |
| `25f58ad2a5d70ccbf15d42cc1c82bbf19c0f83ed` | 最终 338 项源码，Running、26 文件匹配、pcadmin 新鲜登录通过；r18 持久状态及复制/HTML 已核对，retrieve 504 局限保留 |

- V1：[原创空间](https://modelscope.cn/studios/A1211JOY/huawei-pc-agent-app)，部署前后提交仍为 `2248ff7c7553cf9bc52677c4c380014207ade741`。
- 上述首个修订发布清单中的 26 个文件与远端 SHA-256 全部一致；清单摘要为 `e20855d90bcd8669f6ca4cafe9885c215130d2e24deabffd56bf3ba1ee799842`。该旧证据只证明当时上传内容与该清单一致，不证明后来发现的业务缺口已修复。本文件编写不修改应用或触发部署。
- 最终 25f58ad2 的 26 文件 SHA-256 全部匹配，清单摘要为 `6b2f211e253fa5085137dc4b2432414017fbff60cfd05a3905251c5e70195eb3`；证据为 [最终清单](../output/verification/v2-final-publish-manifest.json)、[源码核对](../output/verification/v2-remote-source-check.json)、[Running 状态](../output/verification/v2-final-guard-status-06.json)。1722917 的 `276ff3cd…` 清单见 [归档清单](../output/verification/v2-final-publish-manifest-pre-final-1722917c.json)，056386 的 `9a1e7be0…` 另见 [归档索引](../output/verification/v2-056386f1-archive-index.json)，不以新文件覆盖旧失败。
- V1 最新远端核对中，提交、Running 状态、最后修改时间、硬件及 host 五项未变；运行实例创建时间已变为 `2026-10-20T02:05:42Z`（上海时间 10:05:42），因此不再声称六项全部不变。该实例变化已有另一聊天密码重置流程请求 V1 重部署的直接状态证据；本 V2 组未对 V1 发出写请求。
- 原目录最新 771 文件核对中有 2 项发布工具差异，769 项未变；其中核对的 25 个应用文件未变。两项工具差异已由精确写日志归因于另一既有聊天的 V1 发布鉴权修复，本组未覆盖或恢复。
- V2 使用独立 Studio 的持久卷。虽然数据库相对路径仍为 `/mnt/workspace/huawei-pc-content-studio/studio.sqlite3`，它位于 V2 实例；未上传 V1 数据，V2 初始任务列表为 0。

首修订证据：[b210 发布摘要](../output/verification/v2-release-summary-old-b21068a7.json)、[b210 远端源码核对](../output/verification/v2-remote-source-check-old-b21068a7.json)、[V1 云端保全](../output/verification/v1-post-v2-preservation.json)、[V1 本地保全](../output/verification/v1-local-preservation.json)、[b210 初始数据隔离](../output/verification/v2-initial-data-isolation-old-b21068a7.json)。[范围保全记录](../output/verification/v2-scope-preservation.json)另列出未改动的报价、媒体、导出、供应商、权限和平台策略源码；源码未改不等于外部行为全部重新实测。

本次只改需求理解、候选匹配、卖点计划、相关证据审校和必要的保存/展示衔接。现有平台策略、报价引擎、原图合成与视觉核验、导出格式、登录及 Dify 接入契约沿用原实现。ima 只读取，不修改知识库内容。

## 2. 验证层次与完成情况

| 层次 | 已执行与结果 | 不能由此推出的结论 |
| --- | --- | --- |
| 合成回归 | 最终 25f58ad2 源码包含数字候选 caveat、接口形态与配件范围补丁，主测试 338 项通过（2.906 秒）；部署运行测试另 13 项通过；需求/编辑表单 JS 流程、4 类登录 JS 流程及 Dify 本地结构校验通过 | 所有无单位数字均已独立核验；Dify Cloud 已联调 |
| 本地真实调用 | 案例 A 经真实 ima、现有文本模型和审校形成稿件；复核发现两个无 fact_ids 候选仍有规格和适配解释，故候选理由未通过验收 | conditional/unknown 状态即可证明解释没有越界；稿件通过即可证明整个匹配过程正确 |
| 本地真实界面 | A 稿件人工编辑保存、取消重开、重新读取、复制、HTML 下载与文件内容核对完成 | 所有平台转换、全部导出格式或海报新生成均已在 V2 再次真实执行 |
| 云端部署/鉴权接口 | 25f58ad2 V2 Running；新鲜 pcadmin 登录及未登录401已查；26 文件清单匹配。首次建实例时任务数为 0，随后已创建 QA 任务，不把“初始空库”写成当前仍无任务 | 云端全部控件可用；所有媒体重启恢复通过 |
| 云端原修订 A | chat 请求超时后重新读取取得 r7 稿件；发现无依据候选解释，以及“Windows 路线便于对接课程软件”的外推，旧修订未通过 | draft 状态、P5 pass 或 HTTP 读取成功即代表业务验收通过 |
| 真实样本离线重放 | 修复代码对旧云端 A 实际证据重放：原 Windows 外推句被 blocked，10 候选保留，6 个无事实候选的说明已清理，P3 不再携带该外推；0 次 ima/模型调用 | 已完成修复后云端生成、浏览器或真实接口复测 |
| 056386 云端守卫 | 对同一旧 A 稿实际请求审核报告，HTTP 200、1.144 秒；报告明确阻断原 Windows→课程软件适配句 | 旧稿因此已成为可交付稿；最终新生成已完成 |
| 跨重部署任务持久化 | 最终修订重启后实际 GET 仍取回原任务 ID、r7、57 条事实和原稿；HTTP 200，大响应耗时 183.917 秒 | 已检查所有媒体文件哈希；已完成另一次独立重启后的全部业务恢复 |
| 056386 云端 A | 同一任务 r10 于 07:25:45 落库；正文旧 Windows 外推消失。纯标题保存后 r11、重开、复制文本与 HTML 接口均通过；完整任务却仍保存无依据候选规格与 P3 外推 | 长响应请求成功返回；完整匹配过程已验收；接口导出等于浏览器下载与视觉复核 |
| 最终 25f58ad2 A | 单次末次 retrieve 返回 504，完整 GET 200 取回 r18/draft；20 项持久检查通过，P3 为接口原文、接口引用无包装资料，复制与 HTML 接口 200 | 长请求正常返回；所有自然语言陈述均可由独立字面规则证明；云端 UI 已完成 |
| 云端浏览器 UI | IAB 多次超时；Safari 初次因锁屏无法操作，用户已解锁，现已显示真实 V2 登录页。原生自动化未能填写输入框，随后报告窗口不可用；未观察到登录成功或业务页面 | 登录页可见等于已登录；自动化失败等于业务逻辑失败；尚需用户再次解锁 |

固定日志：[338 项主测试](../output/verification/v2-final-tests.log)、[13 项部署运行测试](../output/verification/deployment-runtime-final.log)、[表单 JS](../output/verification/brief-js-final.log)、[登录 JS](../output/verification/login-js-final.log)、[Dify 结构校验](../output/verification/dify-final.log)、[首修订云端鉴权诊断](../output/verification/v2-online-auth-diagnostics-old-b21068a7.json)。编写本记录时读取这些日志，不把读取日志表述为重新执行测试。

25f58ad2 部署后的鉴权结果另见 [最终鉴权诊断](../output/verification/v2-online-auth-diagnostics.json)，与首修订记录分开引用。

浏览器阻断证据：[云端浏览器尝试记录](../output/verification/v2-online-browser-attempt.json)。该尝试没有修改登录或网络配置。

## 3. A–O 验收映射

“模拟通过”表示对应业务边界由隔离数据库、合成产品/文档、模拟模型或时钟的断言覆盖；不代表相应真实故障已在线上制造并验证。测试名称、文件和分层状态另见 [机器可读矩阵](../output/verification/v2-acceptance-matrix.json)。

| 项目 | 合成回归覆盖 | 本地真实覆盖 | 云端接口 / 云端 UI |
| --- | --- | --- | --- |
| A 不完整需求先查库 | 原句可检索、形成条件方向并生成有事实内容；无型号/预算/软件固定门槛，相关新守卫回归已加入 | 原句实际生成稿，三字段保持空值；候选理由另发现证据缺口，修复已做真实样本离线重放 | 1722917 r15 已清理 GT/D 16 理由和软件外推，接口交付可读；USB 形态/包装关联另有缺口，最终25f58ad2 r18匹配与引用持久化通过；两处人工收窄保留；UI 未完成 |
| B 自然选型诉求不是型号 | 旧 product 自然语言保留为需求；按任务召回，不作型号字符串过滤 | 未单独提交 B 原句；A 的未选型发现只能作为相关观察 | 未单独执行 / 未完成 |
| C 建模与 AI 歧义 | 多任务保留；不推导硬独显、本地大模型或复杂渲染 | A 记录编程/建模为暂定探索方向，没有真实提交 C 原句 | 未单独执行 / 未完成 |
| D 网页 AI 更新推断 | 网页 AI 明确更新旧推断，相关状态可重算 | 未真实执行该纠正序列 | 未执行 / 未完成 |
| E 不知道预算/软件 | 不重复索要；换成“程序”仍不能重问相同技术信息 | 未真实执行该不知道序列 | 未执行 / 未完成 |
| F 指定产品后比较另一款 | 比较、引用、排除与选定分开；不替换已有选择；查不到指定产品不改推比较款 | 未真实执行指定→比较序列 | 未执行 / 未完成 |
| G 年份/系统/配置不串用 | 精确身份、原文定位、系统选项、事实与图片范围；同目录异身份隔离 | 从已保存真实原文离线核对系统别名与未定选项；没有真实交叉错配注入 | 未单独执行 / 未完成 |
| H 规格不能证明性能 | CPU/内存/系统名称不能证明兼容或适配；完整稿附 missing_evidence 也不能豁免实际性能承诺 | 本地 A 候选中发现无依据适配解释；修复后样本重放已清理 | 056386 真实阻断旧句；1722917 r15 的候选/P3 软件外推已清理，正文保留软件版本核对条件；最终r18 P3和接口引用已清理，20项持久核对通过；UI 未完成 |
| I 无价格证据不认预算 | 预算 fit 保持 unknown，历史快照不作现价；原报价边界回归 | A 无核实报价并保留价格 warning；未真实执行“有预算”的 I 条件 | 未执行该条件 / 未完成 |
| J 缺失/冲突/无匹配/故障分类 | 原文不可达、服务故障、部分索引、冲突隔离、重试/查询上限、Schema 格式纠正与保全证据 | 5 个图片目录 HTTP 403；可读目录证据继续使用，故障未归责于用户需求 | 业务取证故障未单独注入 / UI 未完成 |
| K 必要限定 | 约、最高、部分配置及测试条件；压缩后的最终文本仍复核，各属性限定不互相替代 | A 成稿保留“约”、配置/测量差异、典型值及标准版/SE 区别；未真实重跑全部平台压缩 | 未单独执行 / 未完成 |
| L A 数字不能给 B 作证 | 带单位数字及后补的屏幕比例/像素对归属守卫都已纳入 338 项通过结果；新增 4 项覆盖中英文冒号与 ×/x/✕、限定和普通数字边界 | 未真实注入跨型号错误 | 未执行 / 未完成 |
| M 更新与保存状态 | 需求事件顺序、人工保存优先、平台切换复用、旧稿兼容、重新核验及版本/并发保护 | A 编辑保存、取消重开、读取、复制与 HTML 导出完成；未真实跑完需求变更→四平台转换的组合序列 | 同任务跨重部署保留；056386 r11 标题编辑及1722917 r15两处手改持久化、缓存清理、复制/HTML接口可读；422响应保留，最终r18读取及复制/HTML通过；其他更新组合与云端UI未完成 |
| N 没有目标证据可返回缺口 | 合成全库为空/缺少目标依据时返回具体缺口；软任务未知可生成条件稿；stop 不被默认计划吞掉 | 未证明真实全库没有某结论；本轮部分目录不可达且读数有上限，不能作全库否定结论 | 未执行真实全库否定验证 / 未完成 |
| O 范围回归 | 原报价、图片/媒体一致性、复制导出、平台规则、权限登录及 Dify 契约等既有测试随最终源码的 338 项主套件回归；部署另测 | 真实编辑/复制/HTML 与原图选取相关链路已验；报价搜索结算、AI 背景/海报/视觉、Dify Cloud 本次未重复真实调用 | 首次隔离/Running/鉴权/26 文件匹配与交付接口已查；V1 远端五项未变、实例创建时间变化来自另一聊天重部署流程，原本地两工具差异已归因另一聊天；媒体重启恢复和业务 UI 未验 |

## 4. 本地真实案例 A

提交原句：`给工科新生写条朋友圈，推荐适合学习的华为电脑。`

首个修订保存任务的 `product`、`budget`、`software` 均为空，平台为朋友圈。真实查询记录保留 57 条事实、146 个证据引用、15 个可用图片资产和 10 个候选；10 个候选均为 `conditional`。稿件引用 3 条事实、选择 2 张原图，保存 6 条陈述依据映射，记录中的语义审校通过且没有阻断项。价格和发布标识仍有 warning。**这些状态不能作为整个匹配输出正确的结论：后续复核发现候选解释仍有未绑定事实的产品规格，见下节。**

稿件围绕接口、携带及屏幕比较组织；保留重量约数、配置与测量差异、屏幕典型值以及标准版/SE 版差异。编程与建模适配仍需按真实课程文件核实。写作模型曾对未写出的角度报告 missing_evidence；完整稿最终通过独立最终文本检查，而不是凭作者列出的引用或缺口清单自行放行。

真实界面进一步把标题保存为“工科新生选本，先对照学习任务”，取消编辑后重开保持已保存内容，重新读取一致；复制的标题已核对。HTML 下载为 9,952 字节，SHA-256 为 `d222ebe773e58fda5cd5003864a99262ad079bbde353f7afeafd48fca75167bd`，文件包含保存后的标题及来源标记。

证据：[原修订 A 任务](../output/verification/live-ui-A-final.json)、[保存后重新读取](../output/verification/live-ui-edit-reopen.json)、[界面保存/取消/复制/下载核对](../output/verification/local-ui-save-copy-export.json)、[保存后成品截图](../output/verification/local-saved-draft.png)。截图只证明该本地稿件的展示，不证明后续候选理由修复；旧结果均保留。

## 5. 原修订发现的候选解释缺口

原始证据保留在 [A 任务](../output/verification/live-ui-A-final.json) 的 `candidates`，没有覆写成修复后的结果：

- `MateBook D 16` 的 `fact_ids` 为空、逐项 fit 为 unknown，但解释仍出现 16 英寸、16:10、数字键盘、1 TB SSD 等规格。
- `MateBook GT 系列` 的 `fact_ids` 为空、逐项 fit 为 unknown，但解释出现 3:2 OLED、32 GB、1/2 TB、约 1.49 kg 等规格，并有“更适合高负载学习”等排序解释。

云端旧修订 A 在同一输入下也出现无事实候选仍有规格/排序解释，且稿件实际写出“Windows 11 家庭版路线便于对接常见课程软件”。对应 OS 原文只有 Windows/Linux，不能证明课程软件适配；P5 当时在 notes 中认可、claim_support 标为 requires_semantic_review 而未阻断，均不是有效依据。完整旧结果与判定保留在 [云端 A 任务](../output/verification/v2-online-A-reopen-after-timeout.json) 和 [旧修订验收摘要](../output/verification/v2-online-A-summary-old-revision.json)。

云端 chat 初次请求返回 504/upstream_timeout，执行记录活跃耗时 300.529 秒、墙钟耗时 2,100.35 秒，期间记录两段主机睡眠，不能把墙钟时长视为模型响应时长。没有重发原需求；随后 GET 耗时 3.086 秒，读取到同一任务 r7 的 draft。旧修订未继续生成、编辑、复制或导出。

这两类问题说明只标 unknown/conditional 或只获得 P5 pass，不能保证解释与最终陈述有依据。修复包括：候选说明/排序及 P3 方向、价值、限定的证据守卫；肯定式软件适配表述独立复核，系统/CPU/内存不能作适配证据；缓存决策重新清理，stop/read 语义保留。被拒绝文本留作独立审计，不再交给生成器当作可写事实。

修复后的 **真实样本离线重放** 已通过：[本地 A 理由重放](../output/verification/live-ui-A-reason-replay.json)、[旧云端 A 守卫重放](../output/verification/v2-live-evidence-guard-replay.json)。后者实际阻断原 Windows 句，保留 10 候选、清理 6 个空事实候选理由，P3 不再保留该外推；两项都没有调用 ima 或模型，也没有覆写原始失败。此层次不能升级成修复后的云端实测通过。

前修订 `056386…` 上又实际请求了旧稿审核报告：[JSON 调用记录](../output/verification/v2-online-A-old-draft-final-guard-report.json)、[文本报告](../output/verification/v2-online-A-old-draft-final-guard-report.txt)。接口 1.144 秒返回 HTTP 200，报告头为“核验阻断，仅供审核”，并明确指出旧 Windows 句无适配依据。这是**056386 部署代码的真实云端阻断验证**，与离线重放不同；它没有修正旧稿，也不证明新生成稿已成功。

随后对 L 做的两项合成离线复现发现：A 原文为 16:10、B 原文为 3:2，A 文案写 3:2；A 为 2160×1440、B 为 2880×1920，A 文案写后者。修复前独立检查均只标 requires_semantic_review 而没有 blocked。已最小追加屏幕上下文中的比例、像素对，沿用产品归属与限定检查；中英文冒号及 ×/x/✕ 等价表达可通过，错型号阻断，不扩展普通日期、时间或无关乘法。新增 4 项数字形态测试已纳入目前 338 项通过日志。该修复晚于 d065 中间修订，所以 d065 不作为最终版。

## 6. 已知局限与未执行项目

1. 本轮 ima 的 5 个图片目录返回 HTTP 403，分别涉及 MateBook Pro S、MateBook 14 的 images/商城款式图片、MateBook Fold 非凡大师和 MateBook Pro。系统保留各分支 service_failure 与其他可读资料，不能将部分权限故障解释为全库无匹配。可用原图来自成功读取并绑定型号的目录；没有绕过权限，也没有改库。详见 [真实取证记录](../output/verification/live-ima-discovery.json)。
2. 查询有文档数、动作数与耗时上限；未读资料不等于没有产品或没有证据。真实调用没有覆盖全库所有 SKU、软件和工作负载；软件兼容与性能不能由规格推定。
3. 现有报价计算、价格搜索与优惠规则未改。本次没有重新做真实价格搜索、七渠道采集、购买资格或结算验证。原合成价格回归通过不能作为当前价格证据。
4. 图片生成、原图合成和视觉核验流程未改。本次未重新调用 AI 背景、海报合成及视觉模型全链路；原媒体回归仅证明相应代码边界在本地合成条件下仍成立。
5. Dify 接入方式和线上配置保持原契约，仅本地 DSL/鉴权结构校验通过；本次未进行 Dify Cloud 导入、沙箱执行、公共 HTTPS 回调或真实编排联调。
6. 用户已解锁，Safari 可以显示真实 V2 登录页；自动化尚未完成输入/登录，IAB 仍超时。当前限制是业务 UI 尚未验证，不是继续等待解锁；不能以 Running、鉴权接口或本地 UI 通过代替它。
7. 同一 QA 任务跨重部署保留：056386 时取回 r7，最终25f58ad2取回 r18，事实、证据、需求版本、缓存键及取证记录保持一致。见 [早期持久化](../output/verification/v2-online-A-persisted-final-release.json) 与 [最终20项持久检查](../output/verification/v2-online-A-final-persistence-checks.json)。此次没有核对媒体文件哈希，也未另行执行独立重启后的完整业务恢复实验。
8. 056386 `/generate` 的返回链路耗时 120.632 秒后为 504；没有自动重试或重发需求。随后小列表 1.051 秒返回，显示任务早在 07:25:45 已落为 r10/draft；短报告可读取新稿。约 16 秒是按发起与落库更新时间推算，不是模型性能测试。该响应链路局限保留，未改网络或代理配置。

## 7. 056386 云端案例 A 与完整状态复核

2026-10-20 07:25:29（Asia/Shanghai）在原 QA 任务上发起唯一一次最终版 `/generate`，没有新建任务，也没有重发原需求。该调用返回链路为 504，随后通过只读小列表及短报告确认 r10 新稿已生成。正文改为“Windows 11家庭版与Linux V20版可选，课程软件是否适配需按实际版本核对”，原“便于对接常见课程软件”句已消失。短报告引用 4 条事实、2 张原图，无阻断项，仍有价格与发布标识 warning。

证据：[唯一生成调用](../output/verification/v2-online-A-final-generate-attempt.json)、[504 返回记录](../output/verification/v2-online-A-final-generate.json)、[只读列表](../output/verification/v2-online-A-final-list-after-gateway-timeout.json)、[新稿短报告](../output/verification/v2-online-A-final-report-after-gateway-timeout.txt)。

纯标题保存只执行一次，将标题加上“｜保存验收”，重新读取为 r11/draft，其他正文、产品事实及内容任务保持一致。复制接口 HTTP 200 返回保存后的标题与正文，HTML 接口 HTTP 200 返回 7,719 字符；这是接口内容核对，没有执行云端浏览器下载或视觉 QA。见 [交付核对摘要](../output/verification/v2-online-A-final-delivery-checks-pre-cachefix-056386f1.json)、[标题保存差异](../output/verification/v2-online-A-title-save-comparison.json)、[复制响应](../output/verification/v2-online-A-final-copy-pre-cachefix-056386f1.json)、[HTML 响应](../output/verification/v2-online-A-final-html-response-pre-cachefix-056386f1.json)、[导出 HTML](../output/verification/v2-online-A-final-export-pre-cachefix-056386f1.html)。

随后独立阅读 [r11 完整任务](../output/verification/v2-online-A-final-reopened-task-pre-cachefix-056386f1.json) 发现：57 条事实、146 个证据引用、15 个资产、10 个条件候选与 20 个 fit 项仍保存；稿件 4 条事实、2 张原图、6 条 claim_support。最终完整任务共有 7 个 checks，无 blocked，价格、发布标识及未写角度依据边界为 warning。但以下内部内容仍不合格：

- GT 的 `fact_ids=[]`，解释/排序仍含“32GB内存、最高2TB”“约1.49kg”等规格；D 16 同为空事实，仍含“16英寸”“约1.7kg”等规格。
- `selling_point_plan.content_direction` 仍有“Windows通用软件路线”，`value_explanation` 仍称“Windows通用软件路线便于对接常见课程软件”。对应操作系统原文不能支持这种软件适配解释。

因此，本次真实结果只支持“新正文已收窄、保存及交付接口可用”，不能支持“候选和卖点计划均已完成证据清理”。此观察已反馈给主代理，保留原始 r11 记录；离线重放通过不能覆盖实际持久状态的反例。云端 UI 仍只有登录页可见，任何接口结果均不升级为 UI 完成。

## 8. r11 复核后追加的最小修正记录

上述 056386 真实失败仍保留，后续源码修正不能追溯改写为已通过。已查明实际 `generate_task` 的有效缓存分支跳过 `prepare_matching`；现该分支明确执行不调用模型的清理，沿原保存机制落库。新增 4 个实际生成→保存→读取测试，覆盖缓存候选/P3 清理及 stop/read 仍不写作。云端缓存路径是否修复仍需新修订实际读取证明。

另补充端口卖点的 claim_support 映射：原 r11 实际“带HDMI和两个USB-A，接投影、U盘少转接”未独立记录。新增 USB/HDMI/接口陈述抽取；相同产品且有效的接口原文可以记录为候选依据，标记 `relevance_only`、`requires_semantic_review`，不得凭引用 ID 自行标 supported。只对完整原句及后端已知产品/类别前缀的字面复述标 supported；原句后添加减少转接等效益仍需语义审查。3 个针对性合成测试新增后，该文件 32 项通过（0.014 秒，无外部调用）；随后主代理统一执行 327 项主测试（4.323 秒）、13 项部署测试、Dify 本地结构和 2 项 JS 检查，全部通过。该结果尚不代替新云端发布验收。

关于 USB-A，后续资料快查在 ima 卖点原文中找到相关表述，当前参数 fact 仍未确认此形态。因此不作“全库没有 USB-A 依据”的结论；1722917 案例安排一次人工编辑，将“两个USB-A”改为“两个USB3.2 Gen1接口”，同时将导语从“往往比跑分更影响日常”收窄为“如果主要看课件、写文档和查资料，可以先对照屏幕比例、常用接口与实际课程软件需求。” 原自动生成的 Windows/Linux 软件适配条件句保留。编辑记录列明 writer 和 generate 调用为 0、P5 最多 2 次；首次 PUT 返回 422“内容已更新，请重新打开后再保存”，但随后 GET 已确认两处修改持久保存；第二次 P5 经 retrieve 后最终为 r15/draft。见 [人工收窄记录](../output/verification/v2-online-A-manual-narrowing-record-pre-final-1722917c.json)。不能把两处人工修正表述成模型首次自动输出已正确。

实际入口的本地重放另见 [generate→save→get 缓存路径重放](../output/verification/v2-online-A-actual-generate-cache-replay.json)：从真实 r11 原件复制到隔离数据库，实际运行规则生成及保存重开，所得本地副本为 r4/draft，10 候选保留，GT/D 16 无依据规格理由及 P3 软件适配外推均已清理。额外 ima/模型调用为 0，原失败文件 SHA-256 仍为 `38ed6a6f57eb37e39b157907563497429d55f40605c368ce99e1a9d3279a0655`。这是本地实际入口验证，与直接调用清理函数的旧重放不同；当时尚不代表云端缓存已验；1722917 后续 retrieve 结果见下节。

1722917 已 Running，鉴权诊断通过，当时 V1 六项云端指标及本地文件核对无变化；后续原目录两文件的新差异另列于下节，先前观察不作为当前全目录未变的结论。r15 后续已证明候选/P3 清理和人工修改持久保存；端口形态及包装资料关联另有缺口，不升级为该版本全绿。

## 9. 参数断言与候选限定的补充反例

1722917 云端只读核对期间，又复现一个本地 L 边界：A 原文为 16GB、B 为 32GB，A 写“可作为32GB内存候选”会因候选措辞跳过数字归属；“软件适配待核实且内存32GB”同样被豁免。A/B 屏幕比例也可被“可作3:2屏幕候选”绕过。带逗号的“可作候选，内存32GB”原本已阻断，不能把它写成实际失败反例。

已最小将数值的不确定判断与推荐 caveat 分开：候选、值得比较、软件适配未知均不能豁免确定规格，沿用原同型号数字和限定检查；真正的“内存是否32GB”“32GB吗/？”及参数待核实保持未知，不因缺值新增门槛。3 个业务测试新增，包含中/英文问号、候选数字/比例、软件未知邻接及真实参数疑问；该文件 35 项通过（0.015 秒、无外部调用）。该修正已纳入当前 338 项主测试通过结果，不追溯归属于 1722917 云端；已随 25f58ad2 发布，真实读取已在最终r18确认。

## 10. 1722917 的 r15 真实读取与交付

保留前版失败后，在同一 A 任务上手工收窄两处表达，不新建任务、不调用 writer 或 generate。第一次 PUT 120.891 秒返回 422，不能记为保存接口成功；后续读取已确认两处字段落库，事实、报价和内容任务保持一致。随后只执行一次 `retrieve refresh=false`，8.583 秒返回 HTTP 200、r15/draft；这是 1722917 阶段的第二次 P5，未新增 ima/P2/P3 查询；随后最终新修订另执行一次缓存 retrieve（总第 3 次 P5），最终 r18 结果见第13节。真实 GET 1.772 秒返回 r15：57 条事实、146 证据引用、15 资产、10 条件候选、20 fit 项、8 条 claim_support，稿件仍用 4 条事实和 2 张原图。GT/D 16 空事实候选的规格/排序解释和 P3 Windows 软件外推已经清理；P3 不再把它们交给写作。

7 个 checks 无 blocked，价格、发布标识和写作依据边界为 warning。此结果不能证明所有相关映射正确：P3 `allowed_expression` 仍将 USB3.2 Gen1 推为 USB-A；正文接口陈述虽为 relevance_only，其候选资料还含包装清单中的 USB-C 电源适配器。原 r15 记录保留，未改写为全绿。

复制接口 HTTP 200（1.108 秒）、HTML 接口 HTTP 200（26.003 秒，7,731 字符），内容均包含手工收窄后的导语和 USB3.2 Gen1。它们是接口内容验证，没有执行云端浏览器下载或视觉 QA。证据：[人工编辑响应](../output/verification/v2-online-A-manual-narrowing-save-pre-final-1722917c.json)、[编辑字段比较](../output/verification/v2-online-A-manual-narrowing-comparison-pre-final-1722917c.json)、[retrieve 调用](../output/verification/v2-online-A-cache-retrieve-response-pre-final-1722917c.json)、[r15 完整 GET](../output/verification/v2-online-A-final-reopened-task-pre-final-1722917c.json)、[复制响应](../output/verification/v2-online-A-final-copy-pre-final-1722917c.json)、[HTML 响应](../output/verification/v2-online-A-final-html-response-pre-final-1722917c.json)。

r15 之后仅作最小修正：产品参数中的 USB 协议代际不能证明 Type-A/B/C 形态；包装、附件和电源适配器不作机身接口的候选依据，只有原句明确讨论配件时才可关联。7 个接口形态测试、3 个数值断言测试、1 个包装范围测试合计比旧 327 项增加 11 项，当前 338 主测试、13 部署测试、Dify 本地结构和 2 个 JS 检查全部 exit 0。独立检查文件 36 项亦通过。新源码对真实 r15 离线重放已通过，0 次 ima/模型调用，P3 改用接口原文且正文接口映射只保留同型号接口资料；见 [r15 最后守卫离线重放](../output/verification/v2-r15-final-guard-replay.json)。这仍是本地结果；修正现已随 25f58ad2 发布，最终云端实际 retrieve 的持久结果已在第13节核对；请求返回504仍保留。

## 11. 最终账号与调用范围

用户追加第二版用户名为 `pcadmin`，指定密码只经既有私密 Secret 机制和发布进程内存配置，本记录不保存或展示密码、认证哈希、Token。25f58ad2 已 Running；新鲜登录诊断 7.082 秒 HTTP 200，安全 Cookie 属性保留，未登录业务接口 401；这是接口登录验证，不是浏览器业务 UI 完成。同一 A 任务 r15 重部署后保留，见 [任务持久化列表](../output/verification/v2-online-A-final-persistence-list.json)。末次缓存 retrieve 总第 3 次 P5，只执行一次，不新增 writer、generate、价格或图片调用；最终完整 GET 已取回 r18，后续不再执行模型或任务写操作。原 1722917、327 项历史和 r15 结果与最终修订分开记录。

## 12. 原工作目录并发改动与 V1 实例变化

最新 [V1 本地核对](../output/verification/v1-local-preservation.json) 的 771 文件中，`scripts/publish_app.py`、`tests/test_publish_app.py` 有变化，`preserved=false`，另外 769 项未变；其中核对的 25 个应用文件未变。先前“全无变化”只代表当时观察，不能作当前全目录保全保证。

[独立归因记录](../output/verification/v1-concurrent-tool-changes.json) 已定位另一既有聊天中 `publisher_auth_guard` 在原目录的精确写操作：2026-10-20 09:59–10:02 修改 V1 发布工具的凭证保持与登录校验，与文件修改时间一致。这两项工具改动来自该并发聊天，不是本 V2 组写入。本组未覆盖、重置或恢复这些文件，避免抹掉并发修复；本次应用改造只在第二版副本进行。

V1 远端另有独立变化：[10:22:55 核对记录](../output/verification/v1-post-v2-preservation.json) 中，提交仍为 `2248ff7…`，Running、最后修改时间、硬件及 host 共五项未变；运行实例创建时间已变为 `2026-10-20T02:05:42Z`（上海时间 10:05:42）。[独立归因记录](../output/verification/v1-concurrent-tool-changes.json) 的 runtime_attribution 已查到另一既有聊天密码重置流程：实例变化前记录 deployment_requested，随后记录 runtime_changed 及新登录完成；对应工具明确对 V1 执行 deploy_repo。此证据解释实例变化，未保存精确云端请求 ID，不能改写成六项都未变。本 V2 组未对 V1 发出写请求；应用源码、发布工具和运行实例分别记录。

最终 25f58ad2 的缓存 retrieve 已实际返回 504（120.636 秒），见 [调用响应](../output/verification/v2-online-A-final-cache-retrieve-response.json)。没有追加 mutation 重试；随后完整 GET 200 证实 r18 已落库，不能把请求超时写成任务没有执行，也不能把后台完成写成该请求成功返回。

## 13. 最终 25f58ad2 / r18 定稿结果

同一 A 任务最终完整 GET 返回 HTTP 200，耗时 122.579 秒，任务为 r18/draft。`product`、`budget`、`software` 仍为空；57 条真实事实、146 个证据引用、15 个资产、10 个条件候选及 20 个逐项 fit 保留，6 个空事实候选明确保持 unknown，不再携带无依据规格或排序承诺。P3 允许表述已改为对应产品的接口原文，没有 USB-A 形态或 Windows 软件适配外推。事实、证据、需求版本、缓存键与取证记录未被重置或改写。

稿件仍引用同型号 4 条事实、2 张原图。10 条 claim_support 映射对应 9 条实际原句：14.2 英寸与 3:2 在同一句中各作一次数字归属检查；3 条映射为 supported，另外 7 条保留 requires_semantic_review，其中 4 条接口相关映射仅引用真实接口资料 `aae8…`，标为 relevance_only，包装清单 `d07…` 已移除。没有因候选限定跳过数字核验，也没有凭真实引用 ID 将改写的效益自证为成立。需求版本 2、证据版本 `73f57f…` 与本轮计划一致。

最终实际 P5 为 passed、issues 为空，7 个既有检查无 blocked；价格、发布标识及未写角度的依据边界仍为 warning。正文保留“课程软件是否适配需按实际版本核对”和建模兼容核对建议，不声称规格能证明真实建模表现。两处已说明的人工收窄保持不变。

复制接口 HTTP 200（1.672 秒，349 字符），HTML 接口 HTTP 200（1.151 秒，7,731 字符），均核对了保存后的标题、导语、接口协议表述及软件条件句。此为接口内容通过，未升级为云端浏览器下载或视觉 QA。发布代理 20 项持久检查全部通过；主代理及本审查代理分别只读检查最终原件，均没有新增外部调用或任务写操作。第3次P5后不再突变或调用模型。

最终证据：[r18 完整 GET](../output/verification/v2-online-A-final-reopened-task.json)、[20 项持久检查](../output/verification/v2-online-A-final-persistence-checks.json)、[主代理独立审查](../output/verification/v2-final-independent-inspection.json)、[本代理独立审查](../output/verification/v2-final-acceptance-independent-review.json)、[最终复制](../output/verification/v2-online-A-final-copy.json)、[最终 HTML 响应](../output/verification/v2-online-A-final-html-response.json)、[HTML 文件](../output/verification/v2-online-A-final-export.html)。旧版本原始失败及172/r15证据继续使用各自归档链接，不覆写为通过。
