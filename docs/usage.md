# 使用说明

## 环境

- Python 3.10 以上；
- 首期只支持 Ren'Py 8.x（开发验证使用 Ren'Py 8.6）；
- 无第三方依赖，`pip install -e .` 或直接用 `python3 pgf.py`。

```bash
git clone <repo> PaperGalFlow && cd PaperGalFlow
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
pgf --version
```

`PGF_ADAPTERS` 仅用于无安装调试，例如：

```bash
PYTHONPATH=src PGF_ADAPTERS=pgf_adapter_renpy.adapter:RenPyAdapter python3 -m pgf_core inspect <game>
```

安装后 entry point 会自动注册 Ren'Py 适配器，无需环境变量。

## 命令

### `pgf adapters`

列出已注册适配器和加载来源。

### `pgf detect <路径>`

识别 Ren'Py 根目录或 `game/` 目录，打印游戏名、引擎版本、实际 base/game 目录。

### `pgf inspect <路径>`

完整解析但**不写文件**。输出降级链、节点/连线/结局数量、布局尺寸、主题来源、入口选择与诊断。适合先确认解析结果是否符合预期。

```bash
pgf inspect "/home/rhopaper/.local/share/Steam/steamapps/common/永恒与星辰与日常"
```

### `pgf build <路径> --out <目录>`

把两份生成文件写到输出目录（默认 `out/`），不修改游戏。适合审阅或手动部署。

```bash
pgf build <game> --out out/game1
```

### `pgf install <路径> [--dry-run] [--force]`

生成并写入游戏 `game/` 目录：

- 写入 `pgf_flowchart_screen.rpy`、`pgf_menu_hook.rpy`、`pgf_manifest.json`；
- 如果目标文件存在但不含 PaperGalFlow 标记，默认拒绝覆盖；`--force` 才会覆盖；
- `--dry-run` 只打印计划；
- 安装后建议跑一次游戏 lint。

### `pgf status <路径>`

读取 manifest，列出已安装版本、入口模式、风格来源、文件和完整性检查。

### `pgf uninstall <路径> [--force] [--dry-run]`

按 manifest 删除生成的 `.rpy` 及其对应的 `.rpyc`；如果文件在安装后被修改，默认保留并告警，`--force` 强制删除。

### `pgf preview <路径> --out <html>`

生成离线 HTML+SVG 预览，布局与配色来自真实生成数据。`--seen label1,label2` 可以模拟一批已读节点。预览页打开后会自动横向滚动到入口附近；在浏览器里可继续滚动/缩放查看整张图。

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--entry LABEL` | 入口 label，默认 `start` |
| `--preset paper_dark\|paper_light` | 证据不足时使用的内置主题 |
| `--include-side-labels` | 包含仅通过 `call` 到达的 label（默认裁剪，避免把成就/系统脚本画进剧情图） |
| `--show-condition-labels` | 在连线上显示 `if` 条件表达式（默认隐藏，避免代码与剧透） |
| `--entry-mode quick_menu_patch\|ai_rewrite\|overlay_button` | 强制入口模式；`ai_rewrite` 当前不可用 |
| `--json` | 机器可读输出 |

## 游戏内行为

- 打开：快捷菜单旁的“流程图”按钮；或 **F10**；`ShowMenu("pgf_flowchart")`。
- 关闭：右上角“关闭”按钮、`Esc`。
- 浏览：拖拽 viewport、鼠标滚轮、底部 ↑↓←→ 按钮；`－/＋/适应` 调整缩放。
- 场景/结局节点：跳到该 label 的开头（场景的第一个 label）。
- 选择节点：不会退回场景开头，而是**重放该选择菜单**（相同标题与选项），选择后跳到对应分支。菜单前的对白不会重放，选项块内的 `$` 副作用与条件也不会执行，因此只用于“重新选择并进入分支”。
- 条件分歧节点：不提供跳转（`if` 条件无法安全地在游戏外重放）。
- 锁定节点不可点击，且标题显示为“？？？”。
- 状态：节点在正常游玩中经过 label 时自动记录；状态存于 `persistent`，跨存档有效。删掉 `pgf_manifest.json` 不会清状态；想重置可用控制台执行 `persistent.pgf_progress = None`（Ren'Py 控制台）。

## 回滚

推荐：

```bash
pgf uninstall "<game>"
```

手动回滚时请删除：

- `game/pgf_flowchart_screen.rpy`
- `game/pgf_menu_hook.rpy`
- 同名 `.rpyc`（Ren'Py 运行后生成）
- `game/pgf_manifest.json`

只删 `.rpy` 而不删 `.rpyc` 时，Ren'Py 会继续加载旧的编译文件。

## 常见问题

### `quick_menu source is available` 和 `ships only as compiled code`

前者会改写（复制+包装）quick_menu；后者会在原快捷菜单旁放一个悬浮按钮。两者都安装 F10 热键。这是由游戏是否随包发布 `.rpy` 决定的，不是错误。

### 安装后游戏打不开 / 报错

1. 用游戏自己的 lint 检查：`./游戏启动脚本 . lint`；
2. 查看 `game/log.txt` 的异常堆栈；
3. 临时执行 `pgf uninstall "<game>"` 确认是否与生成文件相关；
4. 把 `pgf inspect --json` 的输出与 `log.txt` 一并反馈。

### 快捷菜单按钮位置不理想

悬浮按钮的位置由 quick_menu AST 中的 `xpos/ypos` 与 PNG 尺寸推断；如果游戏把快捷菜单放在非常规位置，可能不理想。可以：

- 用 `--entry-mode overlay_button` 以外的模式（如果有源码）；
- 修改生成的 `pgf_menu_hook.rpy` 中 `xpos/ypos` 后重新运行（注意下次 `pgf install` 会覆盖）。

### 流程图里出现 `条件分歧` 和“否则”

这是正常的条件分支节点。条件表达式默认不显示；加 `--show-condition-labels` 可调试。

### 主题颜色与游戏不完全一致

主题优先级：gui 定义 → UI PNG 采样 → 内置主题。部分游戏只发布编译脚本、或 UI 背景是纯色/透明/多层叠加，这时会使用采样或预设。`pgf inspect` 会显示 `style source` 和置信度。

### Windows

代码使用 `pathlib` 与标准库；未在 Windows 原生测试。建议：

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
pip install -e .
pgf inspect "D:\Games\Game"
pgf install "D:\Games\Game"
```

如果游戏目录在 Program Files 等受保护位置，请用有写权限的账号或先复制游戏再安装。

## 给开发/Mod 作者

- 生成的 screen 数据都是普通 Python 字面量，可以在 `init -35 python` 区块直接改坐标/颜色后重新启动验证。
- 若游戏更新覆盖或删除了文件，重新运行 `pgf install` 即可；更新后剧情变化需要重新生成（这是“纯文件修补”的边界）。
- 想在 CI 里检查生成的代码：`pgf build --out` + 游戏自带的 `lint`。
