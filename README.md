# Scholar Search — 学术论文搜索下载 MCP

通过 **CDP 连接用户真实 Chrome/Edge**，一站式搜索和下载 IEEE / ScienceDirect / CNKI 论文。

无需自动化登录 — 用户在浏览器里手动登录一次，登录状态保存在专用浏览器配置中，之后自动沿用。

```
chrome/msedge --remote-debugging-port=9222 --user-data-dir=~/.carsi_chrome_profile   ← 自动启动（如未运行，Windows 优先 Edge）
       ↓
CDP 连接 (carsi_search/engine.py)      ← 只在工具自己新开的标签页里操作
       ↓
┌──────────┬───────────┬──────────┐
│   IEEE   │Elsevier   │   CNKI   │
│  CARSI   │  CARSI    │   CDP    │
└──────────┴───────────┴──────────┘
```

## 安装

```bash
git clone https://github.com/zhdzh12138/scholar-search.git
cd scholar-search
pip install -r cnki-ieee-download/requirements.txt
```

注册 MCP（全局配置，把 `<克隆目录>` 换成你 clone 仓库的绝对路径）：

```bash
claude mcp add cnki-ieee-download -- python <克隆目录>/cnki-ieee-download/server.py
```

或编辑 `.mcp.json`（参考 `.mcp.json.example`）：

```json
{
  "mcpServers": {
    "cnki-ieee-download": {
      "command": "python",
      "args": ["<克隆目录>/cnki-ieee-download/server.py"]
    }
  }
}
```

## MCP 工具

| 工具 | 说明 |
|------|------|
| `ieee_login` | 连接浏览器，检测 IEEE 登录状态 |
| `ieee_search` | 搜索 IEEE 论文（无需登录）；支持 `page` 翻页、`year_start`/`year_end` 年份筛选 |
| `ieee_detail` | 获取 IEEE 论文详情（无需登录）：作者、期刊/会议、年份、DOI、页码、关键词，以及带标题的下载命令 |
| `ieee_download` | 下载 IEEE PDF（需登录；同名文件不覆盖） |
| `sciencedirect_login` | 连接浏览器，检测 ScienceDirect 登录状态 |
| `sciencedirect_search` | 搜索 ScienceDirect 论文（无需登录）；支持 `page`、`year_start`/`year_end`，标出每篇是否可下载 |
| `sciencedirect_detail` | 获取 ScienceDirect 论文详情（无需登录），附带标题和带标题的下载命令 |
| `sciencedirect_download` | 下载 ScienceDirect PDF（需登录）：先打开文章页，取文章自己的 "View PDF" 链接再打开；遇到安全验证会请你手动完成 |
| `cnki_search` | 搜索 CNKI（无需登录），支持 `page`、`sort`；可选 `author`/`journal`/`year_start`/`year_end` 触发专业检索 |
| `cnki_login` | 检测 CNKI 登录状态 |
| `cnki_detail` | 获取 CNKI 论文详情（无需登录） |
| `cnki_download` | 下载 CNKI 论文（需登录）：优先 PDF，没有 PDF 则下载 CAJ；按标题命名，同名文件不覆盖 |
| `status` | 显示 CDP 连接状态和各数据库已打开的页面 |
| `logout` | 断开 CDP 并关闭工具打开的标签页（浏览器和登录状态保持不变） |

## 首次使用

1. 打开 Claude Code
2. 首次调用 MCP 工具时**自动启动 Chrome/Edge**（带 `--remote-debugging-port=9222` 和专用配置目录 `~/.carsi_chrome_profile`，Windows 优先 Edge）。如需手动启动，必须同时带上 `--user-data-dir`，新版 Chrome/Edge 否则不会打开调试端口
3. 在浏览器窗口中**手动登录**：
   - CNKI：点击"机构登录" → 校外访问 → 选择学校
   - IEEE：点击"Institutional Sign In" → CARSI → 学校认证
   - ScienceDirect：点击"Institutional Sign In" → CARSI → 学校认证
4. 登录状态保存在 `~/.carsi_chrome_profile` 里，后续启动无需重新登录（不会另外生成 cookie 文件）
5. 搜索和查看详情不需要登录；下载时如果未登录，Claude 会提示你在浏览器中登录
6. 工具只在自己新开的标签页里操作，不会动你在这个浏览器里打开的页面；碰到安全验证或滑块验证码时，会把显示验证的那个标签页切到浏览器最前面，并提示你手动完成
7. PDF 下载到调用项目的 `downloads/` 目录

## 功能覆盖

| 功能 | 数据源 | 实现 |
|------|--------|------|
| 英文学术论文搜索/详情 | IEEE Xplore | 读取搜索页自己请求的接口 JSON（`/rest/search`）和页面元数据（`xplGlobal.document.metadata`） |
| IEEE PDF 下载 | IEEE Xplore | 在页面内 fetch（带浏览器登录状态） |
| 英文学术论文搜索/详情 | ScienceDirect | 结果页 DOM + 文章页 `citation_*` 元数据 |
| ScienceDirect PDF 下载 | ScienceDirect | 打开文章页 "View PDF" 按钮上带访问令牌的链接，在 PDF 页内 fetch（安全验证可能需手动完成） |
| 中文学术论文搜索/详情 | CNKI 知网 | CDP 连接真实 Chrome/Edge |
| CNKI PDF/CAJ 下载 | CNKI 知网 | 浏览器级 CDP 下载事件（Browser.setDownloadBehavior + downloadProgress），按标题重命名 |

## 适配其他学校

和学校、账号类型有关的只有 `cnki-ieee-download/carsi_search/registry.py` 里每个数据库的三个字段：

| 字段 | 含义 |
|------|------|
| `logged_in_markers` | 正则列表；数据库首页文字命中任意一个，就算已登录 |
| `logged_out_markers` | 正则列表；没有命中上一项、但命中这里任意一个，就算未登录（都不命中也算已登录） |
| `login_steps` | 未登录时提示用户在浏览器里做的步骤 |

如果你的学校登录后页面上的文字不同（例如没有 "Institutional Sign In"，而是别的按钮），改这几个字段即可。

## 项目结构

```text
scholar-search/
├── cnki-ieee-download/             # MCP 服务器
│   ├── server.py                   # 入口 + 工具定义 + handler 函数
│   ├── requirements.txt            # 依赖（playwright + mcp）
│   ├── requirements-dev.txt        # 测试依赖（pytest）
│   ├── carsi_search/               # CDP 引擎 + 数据库适配器
│   │   ├── engine.py               # CDP 连接（自动启动浏览器）
│   │   ├── registry.py             # 数据库注册表（首页、适配器、登录判断配置）
│   │   └── databases/              # ieee / sciencedirect / cnki 适配器
│   └── tests/                      # 离线测试（模拟站点）、真实页面夹具、live_smoke.py、capture_fixtures.py
├── downloads/                      # PDF 下载目录
├── .mcp.json.example               # MCP 配置模板
└── README.md
```

## 依赖

| 组件 | 必需 | 用途 |
|------|------|------|
| Claude Code | 是 | MCP 宿主 |
| Chrome / Edge | 是（自动启动） | CDP 连接真实浏览器（Windows 优先 Edge） |
| Playwright + mcp | 是 | MCP 服务器运行时 |
| 机构账号 | 下载需要 | IEEE/ScienceDirect CARSI 认证；CNKI 机构登录 |

## 开发与测试

```bash
cd cnki-ieee-download
pip install -r requirements-dev.txt
python -m playwright install chromium   # 离线测试用的无头浏览器（也可以用本机 Chrome/Edge）
python -m pytest                        # 离线测试：无头浏览器 + 模拟站点，不访问真实网站
python tests/live_smoke.py              # 真实网站冒烟测试，需要在弹出的浏览器里登录
python tests/capture_fixtures.py        # 网站改版后重新抓取真实页面夹具（tests/fixtures/）
```

- 离线测试会以无头模式启动 Playwright 自带的 Chromium（找不到时改用本机 Chrome/Edge），也可以用环境变量 `TEST_BROWSER_PATH` 指定浏览器。测试会隔离浏览器配置和下载目录，不会动你真实的登录状态。
- IEEE 和 ScienceDirect 的模拟站点按 `tests/fixtures/` 里的真实页面片段构造。网站改版导致提取出错时，先运行 `capture_fixtures.py` 重新抓取，再对照新夹具修改适配器和模拟站点。夹具只保存公开的书目信息。
- `live_smoke.py` 会检查返回内容是否正确（年份、作者分隔、DOI、年份筛选、耗时等），可以只测某个库（`python tests/live_smoke.py cnki`）。可选参数：`--caj` 让知网下载优先走 CAJ，验证 CAJ 下载；`--sd-downloads=N` 连续下载 N 篇 ScienceDirect 论文并统计安全验证出现的次数。

## 免责声明

- 本项目仅在**西安电子科技大学**账号下测试通过。其他学校如果登录判断不对，请按上面"适配其他学校"修改 `registry.py`。
- 本项目仅供学术研究使用，请遵守各数据库的使用条款。
- 旧版本生成的 `cnki-ieee-download/.carsi_state.json`（明文 cookie）已不再使用，可以删除。

## 致谢

- [cnki-skills](https://github.com/cookjohn/cnki-skills) — CNKI 知网 Skills
- [cnki-codex-skills](https://github.com/cfh-7598/cnki-codex-skills) — CDP 连接模式参考

## License

MIT

## Links

**[Linux DO](https://linux.do/)**
