# AuthService

网站、应用、内部工具和插件共用的独立 OAuth/OIDC 认证服务。管理员维护账号，
支持用户名密码或邮件一次性密码登录；各接入应用独立配置客户端、回调地址、
资源和权限。本仓库不读取业务系统配置，不调用邮箱插件发信接口。

```text
邮箱插件 ─┐
网站应用 ─┼─ OAuth/OIDC ─ AuthService ─ 认证库适配器（当前为 Authelia）
内部工具 ─┘
```

## 依赖和构建

`authelia/` 是固定提交的上游 Git submodule。`src/emailotp/` 保存独立的邮件
登录策略，`providers/authelia/adapter.patch` 保存认证库的后端和界面适配。
构建工具在被忽略的 `.build/` 创建源码副本、应用适配、复制策略并构建；
上游依赖 checkout 保持原样。

```bash
git clone --recurse-submodules https://github.com/OmegaZhou/AuthService.git
cd AuthService
go test -race ./src/emailotp
python3 -m unittest discover -s deployment -p 'test_*.py'
bash scripts/build.sh
```

完整构建需要 Linux、CGO/C 编译器、满足上游 go.mod 的 Go 版本、Python 3.10+
以及 pnpm 12 和满足上游要求的 Node.js。管理工具另外需要 python3-yaml 和
python3-argon2。构建产物在 `artifacts/`，真实配置、密钥、邮件和数据库不提交。

## 接入多个应用

为每个应用创建不同的 `client_id`，配置精确回调白名单、PKCE S256 和该应用
独立的 resource audience。在 `identity_providers.oidc.scopes` 声明权限，并在
每个客户端的 scopes 中只允许所需权限。客户端分别申请自己的资源令牌。
样例配置展示邮箱和笔记两个客户端；示例域名和账号均为占位符。

资源服务器独立验证签名、issuer、audience、client_id、subject、过期时间和
业务 scope；认证模块不修改资源服务器的授权名单。相同账号的永久 subject
在修改登录名时保持稳定。不同应用的数据隔离由各资源服务器负责。

对外接口是授权码 + PKCE、刷新令牌、OIDC discovery 和 JWKS。当前签发 RS256
RFC 9068 access token（typ: at+jwt），包含 sub、client_id、iat、exp、jti、aud
和 scopes。接入方不得将 ID token 当作业务访问令牌。

## 登录和账号管理

`AUTH_LOGIN_MODE=password` 使用认证库原有密码登录。
`AUTH_LOGIN_MODE=email_otp` 使用邮箱地址作为用户名。管理员先创建账号，
用户请求邮件临时密码后登录：密码为八位随机数字，15 分钟内最多发送一次，
15 分钟过期，最多五次失败检查；认证成功后先消费挑战并替换密码哈希，
再创建登录会话。账号存储仅保存 hash，挑战文件只保存时间、尝试次数和状态。
邮件由认证服务自身的 SMTP 配置发送。此模式是邮箱验证登录。

`AUTH_EMAIL_OTP_STATE` 指向服务私有可写目录，冷却期跨重启保留。
仅允许一个进程使用同一挑战文件。SMTP 失败保留冷却期，因为发送是否被接收
可能不明确；成功消费后发生崩溃可能需要等下一个窗口。切换回密码模式前应
由管理员设置已知密码；现有 OAuth 令牌寿命独立于临时密码寿命。

`deployment/change-password.py` 通过隐藏终端输入修改密码；
`deployment/rename-user.py` 修改单账号开发部署的用户名并保留永久 subject。
它们只管理认证服务，输出的 account-registration.json 由各接入应用自行登记。
相关 PowerShell 包装脚本仅负责 SSH 调用。修改密码不会撤销已签发的令牌。

## 部署和配置

复制 `deployment/configuration.example.yml` 和 `users.example.yml` 到私有配置
目录并替换所有占位符，再通过 Authelia validate-config 检查。邮件模式需
禁用密码重置、更改和 passkey 登录，配置真实 SMTP，且账号文件必须可写。
默认样例使用 SMTP 发信；从零部署的发信账号、密码文件、收件账号和启动配置
见 [邮箱登录部署说明](deployment/email-login.md)。不需要 VPS 预装邮件服务器。
systemd/Nginx 样例为 `deployment/auth-service.service` 和
`deployment/nginx-auth-service.conf`，使用服务名 `auth-service` 和 `/auth` 路径。
管理员命令名为 `auth-service-password` 和 `auth-service-rename-user`。

`prepare-email-login.py` 是一次性预配置工具，可以复制管理员指定 SMTP 环境
文件中的凭据；运行时不会读取其来源。`--group` 选择用户所属认证组。
这是复用现有 SMTP 配置的可选工具；新部署可直接填写配置样例。
`smoke-email-login.py` 用独立数据库副本和回环端口检查构建产物；
`install-email-login.sh` 用于现有服务切换，失败自动回滚。新账号注册仅执行一次。
部署工具的 AUTH_* 参数可指定实际服务、目录和健康地址。

## 更换认证库

上游 Authelia 是本仓库的实现依赖，接入应用依赖本模块的协议契约。更换认证库时
新增 provider 适配器并替换构建/部署步骤，保留 OAuth/OIDC 和令牌契约。
邮件策略通过 Account 与 Sender 接口接入，不依赖特定认证库。
目前只有 Authelia 适配器；设置其他 AUTH_PROVIDER 会明确失败。
不满足令牌契约的库需要对应资源服务器适配器，不能仅改依赖名称。

派生适配基于 Authelia，保留其上游历史、许可证和版权声明；本仓库见 LICENSE。
