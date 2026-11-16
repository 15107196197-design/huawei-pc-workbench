# 魔搭完整应用部署适配

这份配置运行 FastAPI 后端和现有静态工作台，支持真实任务、ima 检索、文本生成、报价规则、海报合成、核验与导出；不是评审静态展示页。应用通过远程模型 API 推理，不需要本地 GPU。

## 构建与入口

从项目根目录构建：

```sh
docker build -f deploy/modelscope/Dockerfile -t huawei-pc-studio:modelscope .
```

魔搭上传包须把本目录的 `Dockerfile` 复制为上传包根目录的 `Dockerfile`，同时保留 `requirements.lock`、`huawei_agent/`、`static/` 与 `deploy/modelscope/`。不要上传 `.env`、本机 `data/`、模型令牌或发布令牌。

必须使用 Docker 类型创空间，并从平台接口查询账号当前可用的 CPU 规格。`ms_deploy.example.json` 只给出 SDK 和端口，不硬编码资源套餐、费用或未经查询的硬件标识。Docker 创空间的阿里云绑定、实名和资源资格须由账号验证；静态创空间已上线不证明 Docker 资格通过。

默认入口为 `0.0.0.0:7860`，单进程单实例。容器 `/healthz` 只报告进程存活，不查询 ima、不发起计费模型请求，也不输出账号或配置。应用登录和上游连接必须另行验收。

## 持久化与权限

容器服务用户为 UID/GID `10001:10001`。应用直接通过 `STUDIO_DATA_DIR=/mnt/workspace/huawei-pc-content-studio` 使用持久目录，包含 SQLite、版本、图片缓存、海报及服务端设置。可改为 `/mnt/workspace` 下的另一个专属子目录。

容器启动器先以 root 创建专属应用目录、`media/` 与 `generated/`，仅调整这三个目录的属主；不会修改挂载根目录、递归修改数据文件或设置 `chmod 777`。随后清空附加组、切换为 UID/GID 10001，再检查写权限，最后启动应用。应用不以 root 运行，不会静默回退到临时目录。如果平台强制容器直接以 10001 运行，专属目录需要提前可写；否则启动明确失败。

平台 `/mnt/workspace` 可保存跨重启数据，但迁移、转让或重命名空间仍可能丢失数据；重要内容应备份到私有存储。SQLite 不适合多个独立实例共享写入。本版本使用一个工作进程，不启用横向扩容。

## 运行时私有配置

通过创空间的私有环境变量注入配置，禁止写入公开仓库、构建参数、Dockerfile 或镜像层：

| 变量 | 用途 |
|---|---|
| `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`TEXT_MODEL` | 文本和原生联网查询 |
| `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL`、`VISION_MODEL`、`IMAGE_MODEL` | 视觉核验及背景生成 |
| `IMA_OPENAPI_CLIENTID`、`IMA_OPENAPI_APIKEY` | 指定 ima 知识库的实际账号权限 |
| `DIFY_API_KEY`、`DIFY_BASE_URL`、`PUBLIC_API_BASE`、`TOOL_TOKEN` | 完整 Dify 云端工作流和同一后端回调；四项必须匹配 |
| `STUDIO_USERNAME`、`STUDIO_PASSWORD_HASH` | 单操作人工作台身份；密码哈希按项目脚本生成 |
| `STUDIO_ALLOWED_ORIGINS` | 反向代理下允许的固定 HTTPS Origin，使用非空 JSON 字符串数组；发布工具按已验证账号和应用自动设置 |
| `STUDIO_HOSTED=1`、`STUDIO_MANAGED_CONFIG=1` | 强制托管登录要求和平台管理配置；已由 Dockerfile 设置 |
| `STUDIO_DATA_DIR` | 默认 `/mnt/workspace/huawei-pc-content-studio` |

这些变量的值不能出现在上传包。ima 凭证不能依赖本机 `~/.config/ima/`：容器没有开发者主目录。Qwen 等具体模型须在对应账号和地域中验证。

## 平台鉴权验收

魔搭官方 Docker 说明保留 `Authorization`、`X-modelscope-*` 和 `X-studio-*` 请求头。托管应用须使用工作台会话 Cookie 与非保留的工具凭证头，并验证代理中的请求来源检查。仅更换 Dockerfile 不能证明登录和 Dify 已上线可用。未配置工作台身份时必须拒绝托管启动，不能通过空密码或开发模式绕过。

平台可能改写容器收到的 Host。`STUDIO_ALLOWED_ORIGINS` 应精确列出该空间的 `https://…ms.show` 浏览器入口与已核实的 `https://studio-….api-inference.modelscope.net` API 入口，均不带路径或尾斜线。应用不根据 forwarded 请求头扩展信任范围；不接受通配符、HTTP、空数组或格式错误的配置。未配置白名单时继续严格比对 Origin 与 Host。

应先部署至新应用空间或独立发布版本，保留已上线的静态评审页。必须实际验证：登录/退出、无登录拒绝业务数据和计费操作、补充需求、真实检索生成、编辑保存重开、报价、海报、核验、导出、重启后任务与媒体仍在。接口或模型未配置时应明确显示未接通。

## 本配置的验证范围

当前开发机没有 Docker/Podman；能完成 Python 启动器、专属目录初始化、写权限、非 root 降权顺序的隔离测试，无法在本机宣称镜像构建通过。运行 `python deploy/modelscope/test_runtime.py -v` 可复现这些无外部调用测试。部署后必须依据魔搭实际构建日志和在线行为验收。

官方依据：

- [魔搭官方创空间技能与部署限制](https://modelscope.cn/skills/modelscope/modelscope-studio)
- [Docker 创空间说明](https://modelscope.cn/docs/studios/docker)
