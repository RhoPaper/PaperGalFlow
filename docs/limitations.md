# 已知边界与限制

本文明确列出 v0.1.0 的能力边界，避免把“生成时快照”误解为运行时动态解析。

## 1. 纯文件修补 = 生成时快照

- 流程图数据在 `pgf install` 时固化进 `.rpy`。玩家之后安装剧情 Mod、新增 label 或修改分支，**流程图不会自动更新**，需要重新运行 `pgf install`。
- 这是设计选择，不是 bug：它换来“无需外部进程、无需运行时解析脚本、删除文件即回滚”。

## 2. quick_menu 源码改写并非总是可用

- 商业发行版常常只带 `.rpyc`。本版本不反编译 screen language AST，因此走“悬浮同伴按钮”降级路径，而不是修改 quick_menu。
- 悬浮按钮位置由 quick_menu 的 `xpos/ypos` 和按钮 PNG 尺寸推断；极端自定义布局（相对定位、动态 HLayout、运行时计算坐标）可能得到不理想的位置。此时仍可用 F10。
- `quick_menu_patch` 模式会复制原始 screen 正文；如果原 screen 依赖 `screen` 级属性/变体/参数，包装层只覆盖了正文，极端情况下需要人工调整生成文件。

## 3. AI 环节尚未配置

需求中的“截图 AI 分析”和“AI 辅助改写”需要外部视觉/语言模型后端。v0.1.0 在降级链里保留并诚实报告：

- `screenshot`（剧情/风格）→ `unavailable: AI screenshot analysis is not configured`
- `ai_rewrite`（入口）→ `unavailable: AI 辅助改写需要外部后端`

因此实际可用的路径是：

- 剧情：脚本解析（`.rpy` / `.rpyc`）
- 风格：GUI 定义 + UI PNG 采样 → 内置预设
- 入口：quick_menu 源码改写 → 悬浮按钮（+ 热键）

后续版本接入后端时，只需实现 adapter 的 `screenshot_*` / `plan_entry("ai_rewrite")`，Core 的编排不变。

## 4. 跳转只到 label 开头

- 节点点击执行 `renpy.jump_out_of_context(label)`。它不会回放该节点的历史变量状态：如果目标场景依赖前面章节设置的 flag，可能出现剧情不一致或跳过校验。
- call 栈、`renpy.retain_after_load`、中途变量都可能影响结果。玩家应把流程图跳转视为“重新观看某段剧情”的便利入口，而不是精确的存档回溯。
- 特殊结局节点（跳转到 `splashscreen` / `quit` 等）没有可跳转 label，会被置为不可点击。

## 5. 图的粒度

- 一个 label 通常是一个节点；label 内若有多处 menu/if，会生成额外的选择/分歧节点。
- 纯跳转的“路由 label”会被折叠；不可达 label 会被裁剪；仅通过 `call` 到达的支线默认裁剪（可用 `--include-side-labels` 保留）。
- 条件表达式默认不显示，避免剧透与代码噪声。
- 循环、`while`/`for` 内的流程不被展开；`return` 与“跑到脚本末尾”都会被视为结局。极少数非线性脚本可能因此与真实控制流有偏差。

## 6. 状态记录

- 只有经过 label 才会记录；selector 内的局部 `.label` 会被解析为 `parent.local`，但跳转/记录仍依赖游戏实际执行的 label 名称。
- 状态写入 `persistent.pgf_progress`，与具体存档无关；卸载/重装不会清除它。这与“已读/结局收集”通常的预期一致。
- 目前只记录“访问过哪些 label”，不记录玩家具体选了哪个选项（kernel 预留了 `mark_chosen`，但还没有侵入菜单回调去采集）。

## 7. 视觉与布局

- 节点为矩形（圆角仅在离线预览/主题 token 中预留），Edges 为正交折线；没有使用游戏 UI 的九宫格图片，避免依赖可能缺失的 `gui/button/*.png`。
- 画布高度按 19~30 层可达 3000~4000 px；screen 内用 viewport + 缩放，默认缩放到适配宽度。超长图的整体可读性有限。
- 字体使用游戏 `gui.text_font` 文件名；若游戏字体缺少 `？`、`－`、`＋` 等字形，Ren'Py 会走 fallback，可能出现方框。
- 深色/浅色主题由采样面板亮度自动选择；个别 UI 的亮度处于临界值时会选到相反的明暗风格。

## 8. 平台与引擎

- 只在 Linux x86_64 + Ren'Py 8.6 实测；Windows 未原生测试（尽管实现上无 POSIX 依赖）。
- 只支持 Ren'Py；其他引擎需要新 adapter，Core/CLI/协议已按扩展预留。
- 未处理 RPAE 加密归档；遇到会明确报错/警告。
- 未反编译 `.rpyc` 的 screen language，因此“源码改写”只对有 `.rpy` 的游戏可用。

## 9. 安装与更新

- 游戏商店更新可能删除/覆盖未知文件，或重置 `game/` 目录；更新后建议重新 `pgf install`。
- 安装器只管理 `pgf_*` 文件；manifest 丢失时 `uninstall` 会扫描带标记的 `pgf_*.rpy`，但无法恢复已被用户改名/删除的文件。
- 手动回滚必须同时删除 `.rpy` 和 `.rpyc`。

## 10. 法律与分发

- 生成的流程图包含游戏剧情文本（label 首句/末句），属于游戏内容的衍生显示。请只在合法拥有的游戏上使用，不要随 Mod 包分发大段剧本文本。
- 测试截图/游戏资源不随本仓库分发。
