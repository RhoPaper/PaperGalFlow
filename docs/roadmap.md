# 路线图

v0.4.3 的边界是“只读游戏状态、只复用游戏自身的历史回滚”。以下方向保持这一原则：不注入游戏流程、不替玩家做选择、不写游戏状态、不合成历史。

## 0.3.x 只读状态与 UI

- **结局达成摘要**：把 `ending_read` 汇总成独立列表，支持“结局收集”展示（只读 `seen_label`）。
- **跳转确认**：从流程图跳到远距离 label 前给出可选的确认提示，避免误触；支持“只跳转到已读节点”的开关（纯 UI）。
- **当前场景标记**：读取 Ren'Py 当前 label，在图上标出“你在这里”，不写 persistent。
- **历史检查点可视化**：在节点上区分“可回滚 / 无历史”，让玩家在点击前知道结果。
- **缩放记忆**：仅在本次 screen 生命周期内记住缩放/滚动位置，不落盘。

## 0.4.x 样式与视觉（v0.4.0–v0.4.3，已完成）

- [x] **九宫格圆角资产**（v0.4.0）：纯 Python 生成小尺寸 PNG，用 `Frame` 实现圆角节点/面板与柔和阴影；安装器支持二进制资产。
- [x] **截图分析后端**（v0.4.3）：OpenAI 兼容视觉模型，`screenshot` 风格链路，结果与本地证据按置信度融合。
- [x] **UI 资产选择增强**（v0.4.1）：中心区域取色、渐变/半透明识别、`images.rpa` 面板扫描与 nine-patch 边框探测。
- [x] **主题编辑器**（v0.4.2）：`pgf theme` 导出 JSON，`pgf preview/install --theme theme.json` 立即预览与应用。

## 0.5.x 解析与入口（v0.5.0–v0.5.2，已完成）

- [x] **screen language 反编译**（v0.5.0）：从 `.rpyc` 的 SL2 树重建 `quick_menu` 可读源码，覆盖 displayable、`use`、`if/elif/else`、`for`、属性和缩进；不支持安全重建时回退悬浮按钮。
- [x] **RPA 完整性**（v0.5.1）：RPAE-2.0 AES-256-CTR（需 `PGF_RPA_KEY`）、RPYC2 大小端、索引/条目/名称/前缀/读取资源上限。
- [x] **更完整的 Ren'Py 语法**（v0.5.2）：`while`/`for` 循环与 `break`/`continue`、`translate` 变体跳过、编译局部 label、动态 `jump/call expression` 的字面量/`define` 解析。
- [x] **更多入口模式**（v0.5.0）：标题画面、游戏菜单、`pad_y`/`pad_start` 手柄按键。

## 0.6.x 平台与生态

- Windows 原生测试与打包（PyInstaller 单文件 / MSI）。
- 第二个引擎适配器（例如 RPG Maker / Unity 系 Galgame 框架），验证协议的通用性。
- 本地化管理：CLI/屏幕文案抽取；左到右/右到左布局。
- 插件 API：允许第三方 adapter 与 style provider 独立发布。

## 1.0

- 稳定的 adapter 协议与 CLI 参数；
- 至少 3 个引擎、5 个商业游戏验证；
- 完整的迁移/回滚/兼容性测试矩阵；
- 代码生成格式版本化（`PGF_META["format"]`），旧生成文件可被新版本识别并提示重新生成。

## 技术债

- 生成 screen 的 UI 自动化测试目前依赖真实游戏启动 + 截图；可以把“screen 交互”外包给 Ren'Py 的 lint / 单元级 screen 分析。
- `pgf_core.pipeline` 的 error 分类（failed vs unavailable）还可以更细，便于 UI 展示。
- `entry.quick_menu_patch` 目前只复制 screen 正文，尚未复制 screen 级属性与 variants。
- 布局在极端宽图（单层 > 12 节点）下仍可能超出屏幕宽度，需要更智能的分列/换行策略。
- 生成代码中的 `PGF_STYLE` 以字面量写入；如果主题需要频繁调整，增加一次“只改主题”的增量生成会更快。
- 选择/结局节点目前用所属场景 label 的 `seen_label` 近似；要精确到“具体选项/是否到达 return”，必须注入回调或写状态，与最小侵入原则冲突，暂不实现。
- 历史长度有限，超出 `config.history_length` 的节点不可回滚；若要支持任意节点，需要合成历史（0.1.1 的 replay 方案），与“影响最小”冲突，暂不实现。
