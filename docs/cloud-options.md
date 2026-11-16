# 后端服务器与域名选择

查验日期：2026-10-19。本建议针对单用户 MVP：FastAPI、SQLite、图片合成与文件导出；DeepSeek、Qwen 均调用云端 API，不在服务器加载模型。配置是本项目工程建议，尚未经过真实云端负载测试。

## 主推荐

**阿里云轻量应用服务器，中国香港，2 vCPU / 4 GiB，Linux，SSD 系统盘至少 40 GiB，先买 1 个月。** 若主要验证连通与低频文字任务，可以先试 2 vCPU / 2 GiB；图片、PDF 导出和并发增加后优先保留 4 GiB。无需 GPU，也不在这台机器自托管 Dify。

轻量适合小型应用、开发测试和快速建站。阿里云官方确认套餐包含计算、磁盘和网络资源，并分配公网 IP；与 ECS 相比，这种套餐更适合当前单用户试运行。[产品说明](https://help.aliyun.com/zh/simple-application-server/)、[计费概述](https://help.aliyun.com/zh/simple-application-server/product-overview/overview)

购买入口：[轻量应用服务器购买页](https://common-buy.aliyun.com/?commodityCode=swas)。选择“中国香港”后再看套餐，不要把内地地域的新客促销价当成香港报价。

香港方案适合先打通公网回调；**不能承诺杭州访问香港更快**。官方说明内地到香港/海外可能发生更高延迟与丢包，轻量标注的峰值带宽也不是稳定带宽保证。先用月付完成“杭州操作端 → 后端、Dify Cloud → 后端、后端 → ima / DeepSeek / 北京百炼”的真实联调，再决定年付。[官方地域与网络说明](https://help.aliyun.com/zh/simple-application-server/product-overview/regions-and-network-connectivity)

## 备选

**阿里云 ECS，中国香港，2 vCPU / 4 GiB，SSD 系统盘至少 40 GiB，公网固定带宽起步。** 当轻量所需套餐缺货，或后续需要更灵活的 VPC、网络和资源配置时采用。具体实例族以香港购买页当前供应为准，不预先锁定可能售罄的老规格。

ECS 账单要同时核对实例、系统盘和公网带宽/流量，不能只比较裸计算价格。阿里云也将固定公网带宽 ECS 作为需要更强公网质量保证时的选项。[ECS 官方入口](https://www.aliyun.com/product/ecs)、[实例费用说明](https://help.aliyun.com/zh/ecs/instance-types)、[网络说明](https://help.aliyun.com/zh/simple-application-server/product-overview/regions-and-network-connectivity)

## 域名

**优先复用你已有域名的子域名**，例如在你控制的域名下增加 `pc-agent` 或 `agent-api` 的 A 记录，指向服务器公网 IPv4。无需为这个子域名单独注册一个新域名。

没有域名时，再在 [阿里云域名注册平台](https://wanwang.aliyun.com/) 查询一个简短、你愿意长期持有的 `.com`；`.cn` 也可用于此技术方案。注册时比较首年价与续费价，确认所有者、实名认证和 DNS 管理权；未查询前不声称任何名字仍可注册。[域名注册步骤](https://help.aliyun.com/zh/dws/getting-started)

域名后缀不决定 ICP 备案义务。阿里云说明：网站/App 使用中国内地服务器时，需要在接入商完成备案；资源位于中国香港及海外时，无需在阿里云进行 ICP 备案。以后若将后端迁至杭州等内地地域，应先处理对应接入备案；域名实名认证是另一项注册要求。[备案服务器检查](https://help.aliyun.com/zh/icp-filing/basic-icp-service/user-guide/icp-filing-server-access-information-check)、[域名实名认证](https://help.aliyun.com/zh/dws/user-guide/how-to-complete-domain-name-authentication)

## 价格与需要确认的订单

本轮未能从动态购买页核实你账号可买的香港 2 核 2/4 GiB 套餐价格，也未核实指定域名的注册/续费报价，因此不提供未经核实的月费或年费范围。官方计费说明同样要求以购买页实际价格为准。[轻量计费项](https://help.aliyun.com/zh/simple-application-server/product-overview/billable-items)

具体费用包括：服务器套餐或 ECS 资源费、新注册域名年费（复用已有子域名通常无新增注册费）、证书方案、可能的流量超额，以及独立计算的模型/搜索调用费。不能因为使用小服务器就把模型费用视为包含在套餐中。DNS 与证书均可选择合适的免费方案，不必在首版同时购买负载均衡、托管数据库或 GPU。

付款前形成一张具体订单：产品、香港地域、CPU/内存、磁盘、带宽/流量、购买时长、首购价、续费价、是否自动续费，以及最终域名。**用户确认该订单及费用后再购买**；当前没有购买服务器、域名或开通付费云资源。

## 购买后的交接

部署时需要服务器公网 IP、受控 SSH 登录方式和域名 DNS 控制权。凭证不贴到聊天；使用安全的本机配置或密钥授权。完成 DNS 与证书后，公网地址应类似 `https://agent-api.你的真实域名`，不能填 `localhost`、`127.0.0.1` 或示例域名。

默认公网只开放已鉴权的 `/api/dify/execute`、`/api/tools/`，管理界面通过受控 SSH 隧道访问。需要公网工作台时，先在云服务器运行 `.venv/bin/python scripts/configure_access.py` 配置单操作人登录，再启用 HTTPS；当前登录不是多人权限系统。工具 Token 与登录密码分别管理。

任务创建、界面、Dify 回调必须连接同一云端后端和数据库；本机与云服务器上的两份 SQLite 不会自动同步。否则本机创建的任务传给云端回调会返回“任务不存在”。

仅公开工具的配置模板见 `dify/nginx-tools.conf.example`，详细 Dify 步骤见 `docs/dify-setup.md`。必须实际从 Dify Cloud 发起回调，才能确认它可访问这个公网 HTTPS 服务。
