# OnlyOffice 在线编辑 · 部署指南

让 LIMS 在浏览器里「像 Word/Excel 一样」编辑报告正文、导出数据列表。本方案自托管
OnlyOffice Document Server（社区版，免费），报告以真 `.docx` 为准，打印/归档/盖章
都走 Word 原生态排版。

---

## 一、整体架构

```
浏览器 ──http──> LIMS (FastAPI, 原生 Windows 进程, :8000)
   │                │ 生成 .docx/.xlsx + 编辑器配置(token)
   │                │
   └────http────> OnlyOffice Document Server (Docker 容器, :8088)
                    │  浏览器内嵌 iframe 加载编辑器
                    │
                    └─回调/下载─> LIMS 的 /api/oo/callback、/api/oo/download
```

三个地址，两个方向：

| 谁访问谁 | 地址 | 配置项 |
|---------|------|--------|
| 浏览器 → OnlyOffice 编辑器 | `http://<服务器IP>:8088` | `LIMS_ONLYOFFICE_URL` |
| OnlyOffice 容器 → LIMS（下载/保存文档） | `http://host.docker.internal:8000`（或局域网 IP） | `LIMS_ONLYOFFICE_CALLBACK_BASE` |

> 关键点：OnlyOffice 是「服务器端」去下载/保存文档，不是浏览器。所以
> `LIMS_ONLYOFFICE_CALLBACK_BASE` 必须是 **OnlyOffice 容器** 能访问到的 LIMS 地址，
> 而不是浏览器看到的地址。

---

## 二、步骤

### 1. 启动 OnlyOffice 容器

Windows 服务器上先装好 **Docker Desktop + WSL2**，然后：

```powershell
cd C:\path\to\LIMS\lims
docker compose -f deploy\docker-compose.onlyoffice.yml up -d
```

首次会拉取约 2GB 镜像，耐心等待。验证：

```powershell
curl http://localhost:8088/healthcheck
# 期望返回 "true"（首次启动后 1~2 分钟内可能先返回 false，属正常）
```

> 如需指定固定版本（更稳），把镜像改成 `onlyoffice/documentserver:8.0` 之类。

### 2. 配置 LIMS 环境变量

LIMS 启动时读取以下环境变量（可写进 `run.bat` 顶部或系统环境变量）：

```bat
set LIMS_ONLYOFFICE_URL=http://192.168.1.10:8088
set LIMS_ONLYOFFICE_JWT_SECRET=与docker-compose里JWT_SECRET完全一致
set LIMS_ONLYOFFICE_CALLBACK_BASE=http://host.docker.internal:8000
set LIMS_ONLYOFFICE_WORK_DIR=D:/temp/lims_oo
```

| 变量 | 必填 | 说明 |
|------|------|------|
| `LIMS_ONLYOFFICE_URL` | 是 | 浏览器访问 OnlyOffice 的地址（前端据此显示「在线编辑」按钮并加载编辑器脚本） |
| `LIMS_ONLYOFFICE_JWT_SECRET` | 是 | 与容器 `JWT_SECRET` 一致；**只要两个都设了才启用**，否则自动降级 |
| `LIMS_ONLYOFFICE_CALLBACK_BASE` | 建议 | OnlyOffice 容器回连 LIMS 的地址；Docker Desktop 用 `host.docker.internal`，纯内网部署可用服务器局域网 IP |
| `LIMS_ONLYOFFICE_WORK_DIR` | 否 | 临时 .docx/.xlsx 工作目录，默认 `D:/temp/lims_oo`（本机须放明文区，避免 TSD 加密） |

> **`host.docker.internal` 打不通时**：改成服务器的局域网 IP，例如
> `http://192.168.1.10:8000`。此时浏览器访问 LIMS 也应是该 IP，保证 OnlyOffice
> 容器能路由回这台机器。

### 3. 重启 LIMS

改完环境变量后重启 `run.bat`（uvicorn）。打开 LIMS → 实验报告 → 编辑 → 工具栏出现
「**在线编辑**」按钮即代表启用成功；没有该按钮说明 `LIMS_ONLYOFFICE_URL`/`JWT_SECRET`
未同时配置（此时报告编辑自动回退到浏览器 HTML 编辑 / 本机 Word COM，功能不受影响）。

---

## 三、可选：单入口反向代理

多台内网机器访问、想统一用一个域名/端口时，可在前面加一层反向代理
（nginx / Caddy / IIS 均可）。要点：

- 把 `/` 转发到 LIMS `:8000`
- 把 `/web-apps/`、`/web/`、`/d/`、`/doc/` 等 OnlyOffice 路径转发到 `:8088`
- OnlyOffice 容器仍需能访问 LIMS（保持 `LIMS_ONLYOFFICE_CALLBACK_BASE` 指向其可达地址）

示例（Caddyfile，仅示意，路径按实际调整）：

```
your-domain.local {
    handle /api/* /uploads/* /static/* /web-apps/* /d/* {
        # 简化起见，这里用两个 server 分别反代更清晰，此处略
    }
}
```

> 实际生产建议用 nginx 的 `location /web-apps { proxy_pass http://127.0.0.1:8088; }`
> 等精确规则拆分，避免路径冲突。此文件不展开，需要时再单独配置。

---

## 四、故障排查

| 现象 | 原因 / 处理 |
|------|-------------|
| 编辑报告工具栏没有「在线编辑」按钮 | `LIMS_ONLYOFFICE_URL` 与 `LIMS_ONLYOFFICE_JWT_SECRET` 未同时配置；或前端未刷新（Ctrl+F5） |
| 打开编辑器报「下载文档失败/无法连接」 | `LIMS_ONLYOFFICE_CALLBACK_BASE` 容器不可达，改用 `host.docker.internal` 或局域网 IP |
| 保存后 LIMS 里没更新 | 回调失败：确认容器能访问 LIMS 的 `/api/oo/callback`；JWT 密钥两端是否一致 |
| token 校验失败 / error 1 | 两处 `JWT_SECRET` 不一致，改一致后重启两侧 |
| 报告排版与 Word 不一致 | 内置报告走 HTML→docx 兜底，精度有限；**正式报告请用「模板库」上传 .docx 模板**（占位符 `{{字段名}}`），页眉页脚/盖章/复杂表格可 100% 保留 |

---

## 五、安全与备份

- `JWT_SECRET` / `LIMS_ONLYOFFICE_JWT_SECRET` 请用随机长字符串，且不要提交到版本库。
- 文档下载/回调接口靠「HMAC 签名的文档 key + OnlyOffice JWT」互信，无需 LIMS 登录态，
  请勿把 `LIMS_ONLYOFFICE_JWT_SECRET` 与 LIMS 的用户登录密钥混用。
- 定期备份：容器数据卷（`onlyoffice_*`）可选，报告 .docx 已存在 LIMS 的 SQLite/数据库
  `reports.docx_content`、`report_drafts.docx_content` 字段里，备份 LIMS 数据库即可保住报告。
