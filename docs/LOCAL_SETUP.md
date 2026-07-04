# 本地部署与即梦登录校准 — `feature/short-drama-suite`

> 在你自己机器上独立跑这条主力分支（脱离原容器环境）。手审 + dreamina 后端已合体，全套 5723 测试绿。

## 1. 拉代码

```bash
git clone https://github.com/liqi155134/ArcReel.git
cd ArcReel
git checkout feature/short-drama-suite
```

## 2. 装依赖

```bash
uv sync                        # 后端（需 uv + Python 3.12）
cd frontend && pnpm install    # 前端（需 node + pnpm）
```

外部还需：
- `ffmpeg`（视频拼接与后期）
- `dreamina` CLI（即梦官方，用你的会员账号那套；按即梦官方渠道安装到 PATH）

## 3. 配置

```bash
cp .env.example .env           # 设 AUTH_USERNAME / AUTH_PASSWORD / AUTH_TOKEN_SECRET
uv run alembic upgrade head    # 建库（默认 SQLite: projects/.arcreel.db）
```

起服务后进 WebUI `/settings` 配供应商：

- **AI 助手（大脑）凭据留空** → 自动回落机器上的 Claude Code 订阅登录态。
  - 前提：机器上 `claude` 已登录过（`~/.claude` 有登录态）。这是已验证的订阅 fallback，大脑不额外花钱。
- **生成侧**选「即梦 CLI (Dreamina)」，`cli_path` 填 `dreamina`（或绝对路径）即激活，**无需 API key**（走 OAuth 本机登录态，按账号积分计费）。
  - 备用：ark-agent-plan（填方舟 key，走 AgentPlan 抵扣）。

## 4. 启动

```bash
# 后端（--reload-dir 限定监视目录，否则 watchfiles 扫 node_modules/.venv 拖满 CPU）
uv run uvicorn server.app:app --reload --reload-dir server --reload-dir lib --port 1241

# 前端（另开终端）
cd frontend && pnpm dev
```

## 5. 登录即梦

```bash
dreamina login     # 自己机器直接扫码，比 --headless 方便
```

---

## ⚠️ 两个落地必知

### 1. dreamina 后端的 stdout 解析层尚未对真实 CLI 校准

代码逻辑、四路由、126 个单测都就位，但**真实即梦 CLI 输出的 submit_id / 任务状态 / 错误文案的确切格式，我们从没见过**——单测锁的是「解析器能吃下我们假设的格式」，不是「匹配真实 CLI」。

所以**第一次真跑生成，很可能因解析不匹配而失败、或判不出完成**。届时：

- 把那次真实 stdout 贴出来对照，改 `lib/dreamina_cli_shared.py` 里标注「实测校准点」的几处（submit_id 的 JSON 键 / status 词表 / 错误文案匹配）；
- 同步更新 `tests/test_dreamina_cli_backend.py`。

参数面（flag 名、比例/时长白名单、参考上限）已按 `dreamina <subcommand> -h` 校准过，不用动。**这是 dreamina 落地绕不过的最后一公里。**

### 2. 订阅 fallback 依赖 `~/.claude` 已登录

AI 助手（Claude Agent SDK）在助手凭据留空时回落 Claude Code 订阅；机器上没登录过 `claude` 的话助手不工作。
