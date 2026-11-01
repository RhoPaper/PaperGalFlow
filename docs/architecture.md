# 架构与数据流

## 模块与依赖

```
                 ┌──────────────────────────────┐
                 │           pgf-core           │
                 │  model / state / layout      │
                 │  persistence / preview       │
                 │  adapter protocol / chains   │
                 │  CLI (只依赖 core)            │
                 └───────▲──────────────▲───────┘
                         │              │
        ┌────────────────┘              └─────────────────┐
        │                                                 │
┌───────┴──────────────┐                         ┌────────┴─────────┐
│ pgf-adapter-renpy    │───── 使用 ────────────▶│    pgf-style     │
│ rpa/rpyc/rpy 解析     │                         │ tokens / presets │
│ 剧情图分析 / UI 探测   │                         │ evidence → theme │
│ screen / 入口 / 安装   │                         │ Ren'Py 样式翻译   │
└──────────────────────┘                         └──────────────────┘
```

- `pgf-core` 不知道 Ren'Py 的存在；它只消费适配器返回的 `AdapterInfo / StoryResult / StyleResult / EntryResult / EmitResult / InstallResult`。
- `pgf-style` 是引擎无关的 token 层 + 一个单独的 `renpy_theme.py` 翻译器；后者是首期唯一知道目标引擎的 style 文件。
- `pgf-adapter-renpy` 通过 entry point `pgf.adapters`（或 `PGF_ADAPTERS=module:Class`）注册到 Core 的注册表。

## Core 数据模型

`pgf_core.model`：

- `FlowNode(id, kind, title, subtitle, route, tags, meta)`，`kind` 为 `entry / scene / choice / condition / ending`。
- `FlowEdge(source, target, kind, label, condition, meta)`，`kind` 为 `flow / choice / condition / call / end`。
- `FlowGraph` 提供去重、可达性、裁剪、子图、校验与 JSON 往返；`meta["label"]` 是引擎侧跳转目标。
- 只有带 `meta["label"]` 的场景/结局节点可以跳转；选择/条件节点只用于显示，不生成任何可执行逻辑。

节点状态机 `pgf_core.state`：

- `NodeState = locked / unread / read / ending_locked / ending_read`。
- 规则：entry 永远可用；任一非 call 入边的源节点已读 → 当前节点 unread；已访问 → read；结局只有“已达成/未达成”两种，未达成的标题不展示。
- 这套状态机现在只用于**宿主预览与测试**（`pgf preview`）。游戏内不再嵌入它：生成文件直接读取 Ren'Py 自己的 `seen_label` 数据（跨存档/跨周目的 `_seen_ever`），避免写状态或挂回调。

布局 `pgf_core.layout`：

1. DFS 断环（back edge）。
2. 最长路径分层。
3. 长边插入虚拟节点，让每条边拥有自己的走线槽位。
4. 重心法多轮排序降低交叉。
5. 正交折线布线（水平/垂直线段），回边与 call 边走右侧通道。
6. 全部整数坐标、确定性输出；同一图永远得到同一份代码。

## 适配器协议

`pgf_core.adapter.Adapter` 的每个方法只负责一步：

| 方法 | 职责 |
| --- | --- |
| `detect(path)` | 识别游戏、给出 base/game 目录与版本 |
| `build_story(...)` | 解析脚本 → `FlowGraph` |
| `screenshot_graph(...)` | AI 截图补全入口/分支（当前返回 None） |
| `preset_graph(...)` | 无法解析时的占位图 |
| `build_style(...)` | GUI/资产探测 → `StyleTokens` |
| `screenshot_style(...)` | AI 截图风格提取（当前返回 None） |
| `plan_entry(...)` | 给定模式尝试生成入口方案；不可用则返回 `available=False` |
| `emit(...)` | 图 + 布局 + token + 入口 → 生成文件 |
| `install / uninstall` | 写文件、manifest、回滚 |

适配器**不实现回退**。回退由 `pgf_core.pipeline` 的三条链按顺序尝试，并记录 `success / unavailable / failed`。

## Ren'Py 适配器流水线

```
GameArchive（磁盘 + RPA 虚拟文件系统）
   │  解析 .rpy（自研文本解析器）或 .rpyc（白名单反序列化 + 惰性 stub）
   ▼
ScriptFile（统一语句模型）
   │  analyze.py：label 遍历、menu/if 决策节点、jump/call/return、局部 label、fallthrough
   ▼
FlowGraph
   │
   ├── style_probe.py：gui.* define、style、screen 树、gui.init、PNG 采样
   │        ▼
   │   pgf_style.tokens_from_evidence → StyleTokens → build_theme → Ren'Py 样式片段
   │
   ├── compute_layout
   │
   └── screen_emit.emit_flowchart_screen
            + entry.build_entry_plan
                 ▼
        pgf_flowchart_screen.rpy + pgf_menu_hook.rpy
                 ▼
        installer.install_files（static_check → 原子写 → manifest）
```

### 生成文件结构

`pgf_flowchart_screen.rpy`：

1. 头部注释（版本、游戏、节点统计、风格来源、卸载提示）。
2. `init -35 python:` 预计算数据：`PGF_META`、`PGF_CANVAS`、`PGF_NODES`、`PGF_PREDECESSORS`、`PGF_EDGE_SEGMENTS`、`PGF_EDGE_LABELS`、`PGF_STYLE`、`PGF_LEGEND`。
   - 每个节点是 `(id, kind, title, subtitle, jump_label, seen_label, x, y, w, h)`。
   - `jump_label` 只在场景/结局节点上非空；选择/条件节点为空。
3. `init -30 python:` 只读辅助函数：`pgf_read_states()` 读取 `renpy.seen_label`，以及节点标题、敏感度、滚动和 `pgf_jump_to()`。
4. `style pgf_*:` 文本/按钮样式（由 pgf-style 翻译）。
5. `screen pgf_flowchart():` 标题栏、图例、缩放/滚动、viewport 与节点绘制。

没有 `init -40` 状态机、没有 `init 999` label 回调、没有 replay label、没有 `persistent` 读写。全部剧情数据在生成时固化；运行期只读 `seen_label`，不解析任何游戏脚本。

### 状态读取

- 生成文件用 `renpy.seen_label(label)` 读取 Ren'Py 自己的已读数据库；这是引擎维护的数据，PaperGalFlow 不写入、不 hook、不改变游戏流程。
- 节点可用性由 `PGF_PREDECESSORS` 中的前驱节点是否已读推导；结局节点用其场景 label 是否已读推导（因此是“到达过该场景”的近似，而不是精确的 `return` 计数）。
- 选择/条件节点没有自己的 label，用其所属场景 label 的已读状态推导；它们只显示状态，不参与跳转。
- 打开流程图时计算一次状态；关闭后重新打开会重新读取，跟随游戏进度。

### 入口

两种生成文件：

- **quick_menu_patch**：仅当 `quick_menu` 有 `.rpy` 源码时可用。生成文件把原始 screen 正文原样复制为 `pgf_quick_menu_base`，再在 `init offset = 999` 后定义同名 `quick_menu`（优先级 499，晚于游戏原始 screen），内容为 `use pgf_quick_menu_base` + 新按钮。
- **overlay_button**：只有 `.rpyc` 时使用。从 quick_menu 的 SL2 AST 中提取每个按钮的 `xpos/ypos` 与实际 PNG 尺寸，算出包围盒，选一个不与原按钮重叠的位置（优先右、左，其次下、上），生成一个 `config.overlay_screens` 中的同伴按钮。

两种模式都会生成 `pgf_hotkey` screen 并注册 `config.keymap["pgf_flowchart"] = ["K_F10"]`，因此快捷菜单被隐藏时仍可打开。

## 安全与确定性

- `.rpyc` / RPA 索引都是 pickle。适配器使用白名单 `Unpickler`，只允许容器/少量已知类型，其余落到惰性 stub；任何全局函数都不会被调用。测试覆盖了“索引里塞 `os.system`”与“语句里塞 `eval`”两种情况。
- 代码生成是纯函数：输入图 + 布局 + token + 选项，输出相同字节序列；不写时间戳到 `.rpy`。manifest 里有安装时间，但不影响游戏代码。
- 安装只碰 `pgf_` 前缀文件；manifest 记录 SHA-256，回滚会校验，避免误删用户修改过的文件。

## 目录结构

```
src/
  pgf_core/
    model.py state.py layout.py persistence.py
    adapter.py pipeline.py preview.py cli.py
    runtime/pgf_runtime.py     # 嵌入游戏的同一份状态机源码
  pgf_adapter_renpy/
    rpa.py archive.py rpyc.py rpy_text.py script_model.py
    analyze.py style_probe.py png.py
    screen_emit.py entry.py installer.py adapter.py
  pgf_style/
    tokens.py colors.py evidence.py sources.py presets.py renpy_theme.py
tests/                         # 合成 + 真实游戏集成测试
docs/
```
