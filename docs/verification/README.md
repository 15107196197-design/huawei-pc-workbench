# 验收证据（摘录）

这里是 `output/verification/`（本地 309 个文件、15M）的**摘录**，只挑能证明结论的那部分。完整原始集含大量过程快照，不进仓库。

所有路径已替换为 `<LOCAL>`；不含密钥、账号、会话令牌。

---

## 一、测试演进：从 195 到 338

这些日志是真实跑出来的，**包含失败的那几轮**，按时间排列：

| 文件 | 时间 | 结果 | 说明 |
|---|---|---|---|
| `baseline-tests.log` | 10-20 03:46 | 195 项，**27 errors / 11 skipped** | 起点。错误多为缺依赖导致的 import 失败，不是逻辑错 |
| `v2-first-regression.log` | 10-20 03:52 | 225 项，**3 failures / 1 error** | 首次回归，暴露了 4 个问题 |
| `v2-regression.log` | 10-20 04:01 | 273 项，**OK** | 修复后转绿 |
| `v2-regression-final.log` | 10-20 04:06 | 275 项，**OK** | — |
| `v2-latest-tests.log` | 10-20 04:17 | 297 项，**1 failure** | 新增用例后，`test_P4_exhausted_quota_keeps_specific_gap_without_network_or_retry` 未过 |
| `v2-final-tests.log` | 10-20 10:13 | **338 项，OK** | 最终发布前的完整跑，全过 |

**为什么不删掉失败的那两份**：因为它们才是这份证据的意义。一个只会记录"全绿"的验收日志证明不了什么；能看到 195→338 的成长曲线、以及中途那次 P4 失败如何被处理，才说明测试是真的在跑。

**需要说清的边界**：`v2-final-tests.log` 的 338 项全过，只证明**代码层面**的契约成立。它不调用付费模型，不访问公网，不能推出"准确率 > 95%"或"业务可用"。

## 二、发布与部署

| 文件 | 证明什么 |
|---|---|
| `v2-release-summary.json` | 发布记录：空间 URL、状态 `Running`、`sdk_type: docker`、公开可见、免费 2vCPU/8G 资源、源码修订 `25f58ad`、26 个源文件与清单 hash 全部匹配 |
| `v2-final-publish-manifest.json` | 发布清单与逐文件 hash |
| `deployment-v2.json` | 部署配置与运行时状态 |
| `v2-scope-preservation.json` | 第二版改动的范围边界：改了哪些、没动哪些 |

`v2-release-summary.json` 里 `all_source_files_match: true` 这一条尤其重要——它证明**跑在云上的代码，就是 `25f58ad` 这个修订的代码**，不是本地改了没推的版本。

## 三、独立验收审查

| 文件 | 证明什么 |
|---|---|
| `v2-final-acceptance-independent-review.json` | 只读独立审查：`passed: true`，逐项布尔检查（最终修订正确、r18 草稿、无阻断项、语义通过、草稿事实 ID 全部存在且同产品、claim 引用存在、接口表述只来自实际端口事实、不越界推断等） |
| `v2-acceptance-matrix.json` | 2001 行的验收矩阵：每条要求的通过状态 |

这份独立审查的价值在于**它查的是"有没有越界"**——比如模型有没有把"USB-A 接口"说成"USB-C"、有没有从"Windows 系统"推出"必带某软件"。这类错误在营销文案里很常见，也是这个项目 37 段门禁代码主要防的东西。

## 四、前端流程

| 文件 | 内容 |
|---|---|
| `login-js-final.log` | 登录表单行为回归（`node tests/*.mjs`） |
| `brief-js-final.log` | 需求表单的保存/重试行为回归 |

---

## 完整集在哪里

本地：`output/verification/`（309 文件、15M，含各轮 live 响应、截图、嵌套的发布校验仓库）。它被 `.gitignore` 排除，因为它属于**过程快照**而不是成果。

想让我们补公开某一份具体证据，提 issue 说明要看哪个结论即可。
