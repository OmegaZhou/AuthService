# 从零配置邮箱登录

认证服务直接连接管理员配置的 SMTP 服务器发送登录临时密码。VPS 只需能
访问该 SMTP 地址；无需预装本地邮件服务器，也无需接入邮箱插件。
发信账号和登录账号分别配置：前者负责发邮件，后者是管理员允许登录的用户，
可以使用不同邮箱。临时密码只发给账号文件中已存在的邮箱用户名。

## 1. 准备 SMTP 发信账号

向邮箱或邮件服务提供商获取以下信息，并按其要求启用 SMTP 发信：

| 配置 | 用途 |
| --- | --- |
| SMTP 服务器及端口 | 通常为 587（STARTTLS）或 465（TLS） |
| SMTP 用户名 | 用于连接发信服务器的账号 |
| SMTP 密码／应用授权码 | 由提供商签发，可能不同于网页登录密码 |
| 发件地址 | 提供商允许该账号使用的地址 |
| 登录用户邮箱 | 管理员创建的账号，也是临时密码的收件地址 |

以下路径与仓库默认 systemd 样例一致。先按 README 构建 `artifacts/authelia`。
后面的复制步骤用于全新安装；已有服务应保留自己的账号、数据库和配置。
部署命令由 root 执行，真实信息只填写到 `/etc` 和 `/var/lib` 的私有文件。

## 2. 安装程序和私有配置

```bash
id auth-service >/dev/null 2>&1 || useradd --system --home-dir /var/lib/auth-service --shell /usr/sbin/nologin auth-service
install -d -o root -g auth-service -m 0750 /etc/auth-service
install -d -o auth-service -g auth-service -m 0700 /var/lib/auth-service
install -d -o root -g root -m 0755 /opt/auth-service
install -o root -g root -m 0755 artifacts/authelia /opt/auth-service/authelia
install -o root -g auth-service -m 0640 deployment/configuration.example.yml /etc/auth-service/configuration.yml
install -o auth-service -g auth-service -m 0600 deployment/users.example.yml /var/lib/auth-service/users.yml
```

编辑私有 `configuration.yml`，替换认证地址、cookie 域、OAuth 客户端及所有
密钥占位符。`notifier.smtp` 负责发信，例如：

```yaml
notifier:
  smtp:
    address: 'submission://smtp.example.com:587'
    username: 'sender@example.com'
    sender: 'AuthService <sender@example.com>'
    identifier: 'auth.example.com'
    startup_check_address: 'owner@example.com'
    subject: '[Account login] {title}'
    timeout: '15 seconds'
```

587 使用 `submission://`；465 使用 `submissions://`。保留 TLS 和证书校验。
`sender` 必须是提供商允许的发件地址，`identifier` 使用部署者自己的主机名。
`startup_check_address` 仅用于启动时检查收件地址是否被 SMTP 接受，不会发送邮件。

创建 `/etc/auth-service/smtp.password`，通过编辑器填入 SMTP 密码或授权码，
文件中只放密码。设置权限：

```bash
chown root:auth-service /etc/auth-service/smtp.password
chmod 0640 /etc/auth-service/smtp.password
```

服务通过 `AUTHELIA_NOTIFIER_SMTP_PASSWORD_FILE` 读取该文件。使用此方式时，
不要在 YAML 中同时设置 `notifier.smtp.password`；否则 Authelia 会拒绝启动。
SMTP 账号凭据是发信服务的秘密，用户登录的一次性密码仍只以哈希存入账号文件。

## 3. 创建登录用户

编辑 `/var/lib/auth-service/users.yml`，把 `owner@example.com` 的用户名和 `email`
都替换为实际收件邮箱，使用小写完整地址，保留配置中的授权组。
为初始 `password` 生成随机密码的 Argon2id 哈希：

```bash
/opt/auth-service/authelia crypto hash generate argon2 --random --random.length 64 | sed -n 's/^Digest: //p'
```

把输出哈希写入账号文件的 `password` 字段。该初始密码不用于登录；每次成功
发起邮件登录挑战时，服务会设置新的临时密码哈希。账号文件及其所在目录须
允许 `auth-service` 写入，成功验证后服务才能消费临时密码并替换哈希。

## 4. 启用邮件模式并启动

```bash
install -o root -g root -m 0644 deployment/auth-service.service /etc/systemd/system/auth-service.service
install -d -o root -g root -m 0755 /etc/systemd/system/auth-service.service.d
install -o root -g root -m 0644 deployment/email-login.conf /etc/systemd/system/auth-service.service.d/email-login.conf
AUTHELIA_NOTIFIER_SMTP_PASSWORD_FILE=/etc/auth-service/smtp.password /opt/auth-service/authelia validate-config --config /etc/auth-service/configuration.yml
systemctl daemon-reload
systemctl enable --now auth-service
```

在现有 HTTPS server 中加入 `nginx-auth-service.conf` 的 `/auth` 代理，验证 Nginx
配置后重载。OAuth 接入方继续按 README 登记客户端、资源、权限和用户身份。
登录方式由 `AUTH_LOGIN_MODE` 控制；改用 `password` 时先由管理员设置已知密码。

## 5. 验证真实发信

打开部署后的 `/auth/` 登录页，填写已创建的邮箱用户名，点击“发送登录临时密码”。
确认邮箱收到邮件并能登录。同一账号 15 分钟内不会重复发信；临时密码 15 分钟
过期且成功使用一次后失效。单纯通过配置校验或启动检查不能证明邮件已经投递。

收不到邮件时，检查提供商要求的授权码、发件地址权限、VPS 出站端口、TLS 和
垃圾邮件目录；服务日志和配置均留在私有部署环境中。

`prepare-email-login.py` 可一次性复用已有 `SMTP_HOST`、`SMTP_PORT`、
`SMTP_USERNAME`、`SMTP_PASSWORD_FILE`、`MAIL_FROM` 配置，但不是新安装的前提。
`install-email-login.sh` 用于已部署认证服务的升级切换，不能代替上述首次安装。
它生成的私有 YAML 已含 SMTP 密码，因此不要额外安装引用密码文件的 drop-in。

参数说明见 Authelia 官方 [SMTP 配置](https://www.authelia.com/configuration/notifications/smtp/)
和 [文件密钥配置](https://www.authelia.com/configuration/methods/secrets/)。
