# PaperGalFlow

[![tests](https://github.com/RhoPaper/PaperGalFlow/actions/workflows/tests.yml/badge.svg)](https://github.com/RhoPaper/PaperGalFlow/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

为 Ren'Py Galgame 生成「柚子社式剧情流程图」的模块化工具。

PaperGalFlow 解析游戏脚本，还原 label / 选项 / 条件分支 / 结局之间的剧情图，按游戏自身的 UI 颜色与字体做布局，然后把流程图**固化**成若干个 `pgf_*.rpy` 文件写进游戏目录。游戏运行时不再解析脚本，也不依赖外部进程；删除生成文件即回滚。

> 首个可用版本：**v0.1.0**。首期只支持 Ren'Py 8.x；已在 Linux + Ren'Py 8.6 上用《永恒与星辰与日常》和《小小的身影，重叠的内心》验证。

## 功能

- **剧情图**：自动解析 `.rpy` 源码或 `.rpyc` 编译脚本（含 `.rpa` 归档），识别场景、选项、条件分歧、跳转、call 支线与结局。
- **流程图 UI**：独立的 `screen pgf_flowchart`，通过 `ShowMenu("pgf_flowchart")` 打开；包含标题栏、进度、图例、缩放、拖拽/滚轮浏览和节点点击跳转。
- **节点状态**：锁定 / 未读 / 已读 / 结局（未达成、已达成）。状态直接读取 Ren'Py 自身的 `seen_label` 数据库，不写 `persistent`、不挂 label 回调；锁定节点不泄露标题。
- **历史回滚跳转**：可点击节点会先确认，然后复用游戏 HISTORY 界面同款的 `RollbackToIdentifier`，回滚到该节点在**当前存档历史记录**中的检查点。历史列表自动变为“目标及其之前的内容”，变量/分支状态也由游戏精确恢复；只使用 `_history_list` 里已有的检查点，不合成菜单、不改写历史、不写游戏状态。历史中不存在的节点标为“无历史”，不可点击。
- **风格提取**：读取游戏的 `gui.rpy` / `screens.rpy`（或 `.rpyc`）中的颜色、字体、字号、按钮状态，并直接采样游戏自己的 UI PNG（`dialog_bg`、选项按钮、快捷菜单按钮），还原主题；证据不足时回退到内置主题。
- **最小侵入入口**：源码可读时复制并包装 `quick_menu`，在其后追加“流程图”按钮；只有编译脚本时在快捷菜单旁绘制一个同样风格的悬浮按钮；F10 热键始终可用。
- **可回滚**：安装清单、SHA-256 校验、原子写入；`pgf uninstall` 同时删除 Ren'Py 编译产生的 `.rpyc`。
- **离线预览**：`pgf preview` 生成与游戏内布局/配色一致的 HTML+SVG，便于在没有启动游戏时检查。

## 模块

| 模块 | Python 包 | 职责 |
| --- | --- | --- |
| `pgf-core` | `pgf_core` | 引擎无关的剧情图、节点状态机、布局、持久化接口、降级链调度、适配器协议、CLI、离线预览 |
| `pgf-adapter-renpy` | `pgf_adapter_renpy` | Ren'Py 适配器：RPA/RPYC/RPY 解析、剧情图分析、UI 探测、screen 生成、入口注入、安装/卸载 |
| `pgf-style` | `pgf_style` | 风格 token 模型、颜色工具、证据融合、预置主题、Ren'Py 样式翻译 |

依赖方向：`pgf-adapter-renpy → pgf-core + pgf-style`，`pgf-style → 标准库`，`pgf-core → 标准库 + pgf-style`。CLI 只导入 `pgf_core`，适配器通过 `pgf.adapters` entry point 或 `PGF_ADAPTERS` 环境变量注册。

## 安装

需要 Python 3.10+，无第三方运行时依赖。

```bash
git clone https://github.com/RhoPaper/PaperGalFlow.git
cd PaperGalFlow
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
pgf --version
```

不安装也可以直接使用开发启动器（会临时把 `src/` 加入路径并注册内置 Ren'Py 适配器）：

```bash
python3 pgf.py --version
```

## 快速开始

以两个测试游戏为例（路径含中文，命令中请保留引号）：

```bash
# 只看解析结果，不写任何文件
pgf inspect "/home/rhopaper/.local/share/Steam/steamapps/common/永恒与星辰与日常"

# 生成到输出目录（不会改游戏）
pgf build "/home/rhopaper/.local/share/Steam/steamapps/common/永恒与星辰与日常" --out out/game1

# 直接安装进游戏；--dry-run 只打印计划
pgf install "/home/rhopaper/.local/share/Steam/steamapps/common/永恒与星辰与日常" --dry-run
pgf install "/home/rhopaper/.local/share/Steam/steamapps/common/永恒与星辰与日常"

# 查看状态、回滚
pgf status  "/home/rhopaper/.local/share/Steam/steamapps/common/永恒与星辰与日常"
pgf uninstall "/home/rhopaper/.local/share/Steam/steamapps/common/永恒与星辰与日常"

# 离线预览（浏览器打开生成的 HTML）
pgf preview "/home/rhopaper/.local/share/Steam/steamapps/common/小小的身影，重叠的内心" \
    --out out/game2.html
```

安装后进入游戏：

- 点击快捷菜单（AUTO / SKIP / SAVE 那一排）左侧新增的 **流程图** 按钮；
- 或按 **F10** 随时打开（快捷菜单被隐藏时也可用）；
- 关闭按钮或 `Esc` 返回游戏。

点击任意带历史检查点的节点，会先弹出与游戏 HISTORY 相同的确认框，然后调用 `RollbackToIdentifier` 回到该处；历史、变量和分支状态由 Ren'Py 恢复。只有当前存档历史里仍存在的节点可以回滚，未访问或超出历史长度的节点会标记“无历史”。请阅读 [已知边界](docs/limitations.md)。

## 生成的游戏文件

安装到 `game/` 目录，文件名统一以 `pgf_` 开头：

| 文件 | 作用 |
| --- | --- |
| `pgf_flowchart_screen.rpy` | 流程图 screen、内嵌的运行时状态机、预计算的节点/连线/样式数据、label 回调 |
| `pgf_menu_hook.rpy` | 入口：quick_menu 源码改写或悬浮按钮 + F10 热键 |
| `pgf_manifest.json` | 安装清单（版本、入口模式、文件哈希），供 `status` / `uninstall` 使用 |

Ren'Py 首次运行后会额外生成同名的 `.rpyc`。**手动回滚时请同时删除 `.rpy` 和 `.rpyc`**，否则 Ren'Py 仍会加载残留的编译文件；使用 `pgf uninstall` 则会自动处理。

## 降级链

PaperGalFlow 的 Core 统一编排三条链路，适配器只报告每一步的成功/失败：

- **剧情数据**：游戏脚本解析 → AI 截图分析（本版本未配置后端）→ 预置占位图。
- **样式**：游戏 GUI/PNG 采样 → AI 截图分析（本版本未配置后端）→ 内置主题。
- **入口**：`quick_menu` 源码追加 → AI 辅助改写（本版本未配置后端）→ 悬浮按钮。F10 热键始终随入口一起安装，作为最后的可达性保底。

每一步的结果都会在 `pgf inspect/install --json` 和终端输出里列出，方便判断当前游戏实际走了哪条路径。

## 已验证环境

| 项目 | 结果 |
| --- | --- |
| Linux x86_64、Ren'Py 8.6.0（游戏自带运行时） | ✅ 解析、生成、lint、实际启动、打开流程图、节点跳转、关闭、缩放、滚动 |
| 《永恒与星辰与日常》：仅 `.rpyc`、2560×1440、自定义快捷菜单图标、`images.rpa` | ✅ 45 节点 / 54 连线 / 4 结局；入口走悬浮按钮 |
| 《小小的身影，重叠的内心》：仅 `.rpyc`、1920×1080、粉白主题、两张结局 | ✅ 25 节点 / 30 连线 / 2 结局；主题与按钮位置来自游戏 UI 采样 |
| 单元/集成测试 | ✅ 188 项（两个游戏的测试在未安装时自动 skip） |

Windows 原生尚未验证；代码只使用 `pathlib`、`zlib`、`pickle` 白名单反序列化等标准库能力，不依赖 POSIX 路径、符号链接或外部进程。建议在 Windows 上：

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
pip install -e .
pgf install "D:\Games\SomeRenPyGame"
```

## 开发与测试

```bash
python -m unittest discover -s tests -t . -v
```

测试包含合成游戏目录、合成 PNG/RPA/RPYC、恶意 pickle 防护、安装/回滚，以及两个真实游戏的集成测试。若游戏不在默认 Steam 路径，可设置：

```bash
export PGF_GAME1_DIR=/path/to/game1
export PGF_GAME2_DIR=/path/to/game2
```

静态检查（不启动游戏）：

```bash
# 生成的文件会经过内置解析器检查；安装前也会检查
pgf build <game> --out out
```

建议安装后运行游戏自带的 lint（Ren'Py 的 `lint` 参数）：

```bash
cd "/path/to/game"
./GameLauncher.sh . lint
```

## 文档

- [架构与数据流](docs/architecture.md)
- [使用说明](docs/usage.md)
- [已知边界与限制](docs/limitations.md)
- [路线图](docs/roadmap.md)
- [变更记录](CHANGELOG.md)

## 版本策略

语义化版本；每完成一个模块/功能递增一次版本，并打 git tag。当前 `v0.3.0`；首个可用版本是 `v0.1.0`：

- `0.0.1` 核心图模型、状态机、布局
- `0.0.2` RPA 读取
- `0.0.3` 编译脚本读取
- `0.0.4` `.rpy` 文本解析
- `0.0.5` 虚拟文件系统
- `0.0.6` 剧情图分析
- `0.0.7` 风格 token
- `0.0.8` UI 采样与风格探测
- `0.0.9` screen 生成 + 离线预览
- `0.0.10` 入口注入 + 安装器
- `0.0.11` 降级链 / 适配器协议 / CLI
- `0.1.0` 文档、双游戏端到端验证、发布
- `0.1.1` 选择节点回放（已在 `0.2.0` 移除）；重装排除自身生成文件；清理旧 `.rpyc`
- `0.2.0` 仅跳转到已有场景 label；移除 replay menu；状态改读 Ren'Py `seen_label`，不再写 `persistent` / 挂回调
- `0.3.0` 复用 HISTORY 的 `RollbackToIdentifier`：只跳历史中已有的场景/选项检查点，历史与变量状态和游戏自身回滚完全一致

## 许可证

MIT（代码）。生成文件只写入工具自己的 `pgf_*` 文件，不修改游戏原始资源；请在遵守游戏许可的前提下自行使用。
