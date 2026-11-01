# 路线图

v0.1.0 的目标是“能解析、能生成、能安装、能回滚、能看见状态”，以下按优先级列出后续方向。

## 0.2.x 运行时与状态

- **选项记录**：在不修改游戏原始 screen 的前提下，记录玩家实际选择的选项（研究 `config.choice_callbacks` / menu screen hook 的可行注入点）。
- **结局达成面板**：把 `ending_read` 汇总为独立成列表，支持“结局收集”展示。
- **跳转确认**：从流程图跳到远距离 label 前给出可选的确认提示，避免误触；支持“只跳转到已读节点”的强制开关。
- **重置入口**：在流程图内提供“重置已读状态”按钮（带二次确认），避免玩家依赖控制台。
- **最近节点高亮**：记录 `persistent` 中的当前 label，在图上标出“你在这里”。

## 0.3.x 样式与视觉

- **九宫格圆角资产**：生成小尺寸 PNG（纯 Python 写 PNG），用 `Frame` 实现真正的圆角节点/面板与柔和阴影。
- **截图分析后端**：接入外部视觉模型，实现需求中的 `screenshot` 风格链路；结果与现有证据做置信度融合。
- **UI 资产选择增强**：识别渐变/半透明面板，按区域采样而不是整图平均；支持从 `images.rpa` 读取 nine-patch 边框。
- **主题编辑器**：`pgf preview --theme theme.json`，让玩家/Mod 作者自定颜色并立即预览。
- **缩放记忆**：把最近一次缩放/滚动位置写进 `persistent`。

## 0.4.x 解析与入口

- **screen language 反编译**：对只有 `.rpyc` 的游戏，重建 `quick_menu` 的可读源码，从而支持源码式追加；需要覆盖 SL2 节点类型与缩进还原。
- **RPA 完整性**：支持 RPAE 加密归档、跨平台字节序变体、恶意归档资源上限。
- **更完整的 Ren'Py 语法**：`while`/`for` 循环内的控制流、`translate` 变体、局部 label 的精确 fallthrough、`call expression` 动态目标。
- **更多入口模式**：标题画面入口、游戏菜单入口、手柄按键提示。

## 0.5.x 平台与生态

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
