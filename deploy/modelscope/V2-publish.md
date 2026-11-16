# 第二版独立发布

本副本的 `scripts/publish_app.py` 固定发布到登录账号下的
`huawei-pc-agent-app-v2`。第一版 `huawei-pc-agent-app` 不作为发布、重启、
日志或接口验收目标。第二版使用独立创空间及该空间自己的 `/mnt/workspace`；
不迁移、清理或覆盖第一版的任务、媒体与历史。

仍沿用 Docker 创空间、`0.0.0.0:7860`、单工作进程、原模型与服务配置、
免费 CPU 资源校验和平台 Secret 注入。公开上传只收集现有应用白名单，
不包含 `data/`、`.env`、发布环境、令牌或工作台密码。

## 本机授权入口

在第二版目录准备原有隔离发布工具环境（不改变应用依赖）：

```sh
uv venv output/publish-env --python .venv/bin/python
uv pip install --python output/publish-env/bin/python modelscope-hub==0.4.0
.venv/bin/python scripts/publish_app.py
```

打开 `http://127.0.0.1:8791/`。第二版自己的运行配置应已安全准备到本副本
的私有 `data/settings.json`，或经当前进程环境传入；不要把数据目录指向第一版。
ima 沿用现有已授权凭证读取方式。服务密钥只经现有 Secret API 注入第二版，
不得把私有配置放进上传包。

用户在密码框提交自己已有的魔搭可写 Token。该动作只验证账号身份，
不会自动创建空间或发布。令牌保存在当前进程内存，关闭进程后失效；
不从浏览器 Cookie、SDK 缓存或第一版进程中提取授权。页面会显示本次生成的
第二版工作台登录凭证，由部署者自行保存，不能从第一版密码哈希恢复原密码。

## 审查与发布

沿用现有动作：获取首页返回的 `X-CSRF-Token`；POST 同时携带该头和
`Origin: http://127.0.0.1:8791`。

1. `POST /api/actions/prepare`，请求体 `{}`。审查返回的文件清单和摘要。
2. `POST /api/actions/publish`，请求体为 `{"manifest_sha256":"审查后的摘要"}`。
3. `POST /api/actions/status` 读取实际构建、运行和资源状态。
4. 必要时分别读取 `/api/actions/logs` 的 `build`、`run` 日志；部署完成后
   用现有 diagnostics 和受限 request 接口验收第二版。

可使用无 Token 参数的本机检查脚本。它从首页响应头取得 CSRF，拒绝连接未标为
固定第二版的发布器，不读取 `/api/access`，且没有发布、重启或任意接口动作：

```sh
.venv/bin/python deploy/modelscope/v2_control.py local-status
.venv/bin/python deploy/modelscope/v2_control.py prepare
.venv/bin/python deploy/modelscope/v2_control.py status
.venv/bin/python deploy/modelscope/v2_control.py logs --kind build
.venv/bin/python deploy/modelscope/v2_control.py logs --kind run
.venv/bin/python deploy/modelscope/v2_control.py diagnostics
```

`local-status` 和 `prepare` 只检查本机；`status`、`logs`、`diagnostics` 通过原发布器
检查第二版线上状态。`diagnostics` 验证原有两层认证和健康检查，不调用生成模型。

发布器会实时查询可用硬件，仅接受平台返回的免费 Docker CPU 规格；
没有免费资源、空间配额不足或 Docker 实名资格不满足时明确停止，不自动转用付费资源。
`whoami` 成功只证明身份，硬件列表和创建表单可见也不证明写权限。
只有针对第二版的实际 `create_repo` 成功才证明该次创建权限；不通过创建临时空间探测权限。

已有但不属于本次进程创建的第二版空间会被拒绝覆盖。新建发布不设置
`PUBLISH_RESUME_LOGIN_*`。以后如需恢复第二版修复发布，必须同时具备第二版
原工作台凭证和 `output/submission/full-app-v2-deployment.json` 收据；
收据中的 URL 必须对应已验证账号和第二版 slug。第一版收据及 URL 不能恢复第二版发布权限。

免费 CPU 不代表上游模型免费。文本、检索、搜索、视觉核验及背景生成的费用与限额
仍由原服务账号决定；真实调用和线上浏览器验收应与模拟、本地测试分别记录。

## 当前验证边界

部署脚本测试使用合成凭证和模拟传输；启动器测试在本机验证目录权限及降权。
这些检查不证明本机 Docker 构建、实际创建权限、线上登录或上游模型已验证。
最终地址以第二版官方元数据返回的 host 为准。
