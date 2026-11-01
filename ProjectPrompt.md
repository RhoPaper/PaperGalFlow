## PaperGalFlow 项目需求描述

PaperGalFlow 是一个为 Galgame 提供“柚子社式流程图”能力的模块化工具项目。目标是让玩家在游戏内查看剧情分支流程图，支持已读/未读/锁定/结局等节点状态显示，并支持从节点跳转回对应剧情。项目采用组件式架构，核心层（Core）负责引擎无关的图数据模型、节点状态机、布局算法、持久化接口和降级链调度；适配器层（Adapter）按引擎实现“脚本解析、文件修补、UI 风格提取”三项能力；风格层（Style）负责从目标游戏的 menu 源码或截图提取颜色、字体、间距、按钮状态等设计 token，并翻译为各引擎可用的样式定义。

**实现方式：纯文件修补，不做运行时注入。** 所有流程图数据在生成时固化为 Ren'Py screen 代码，写入游戏目录，游戏运行时不再动态解析脚本。流程图 screen 通过 `ShowMenu("pgf_flowchart")` 以独立界面调出，不影响原游戏其他 screen 的渲染状态。节点状态用变量记录，读写逻辑全部在生成的 screen 代码内完成，不需要外部进程介入。代价是放弃运行时动态解析，玩家安装剧情 Mod 新增 label 时流程图不会自动包含，此边界在文档中明确说明。

**入口设计：最小侵入。** 首期只支持 Ren'Py。默认方案是在目标游戏的quick_menu末尾追加一个“流程图”按钮，同时原样保留原有按钮和条件分支。生成文件以pgf为前缀单独命名（如 `pgf_menu_hook.rpy`、`pgf_flowchart_screen.rpy`），回滚即删除文件。若目标游戏 quick menu 高度定制，则走 AI 辅助改写：由 AI 读取原 screen 源码，生成保留原结构、仅追加按钮；随后做静态校验，简单检查按钮数量等，校验不通过则降级为快捷键入口（），不改 quick menu。

**降级链由 Core 统一编排**：源码解析 → 截图 AI 分析 → 预制底层样式，三条路只影响“图数据和风格 token 从哪来”，最终统一产出同一份 screen 代码并走同一个文件写入器。quick menu 入口同理：源码改写 → AI 改写（带校验）→ 快捷键入口 → 预制底层。适配器只报告各环节成功/失败，不各自实现回退逻辑。

**技术路线**：首期用 renpy_parser 或 renpy-graphviz 的 parser 将 `.rpy` 解析为图数据；UI 风格优先逆向目标游戏的 `screens.rpy` 和 `gui.rpy` 提取 style token，截图 AI 分析作为回退。Core 与 Ren'Py adapter 的“解析 + 代码生成”部分用纯 Python 和 `pathlib` 开发，避免硬编码路径，保证 Linux 跑通后 Windows 基本可用。

**命名与模块**：总项目名 `PaperGalFlow`，内部模块为 `pgf-core`、`pgf-adapter-renpy`、`pgf-style`。CLI 入口只依赖 Core，适配器通过注册机制挂载，以便后续扩展更多引擎。

---

目前仅提供Linux开发环境，先在Linux上跑通，我会想办法进行Windows原生测试。提供2个已安装的Ren'Py游戏用于测试，游戏文件位于"/home/rhopaper/.local/share/Steam/steamapps/common/永恒与星辰与日常"和"/home/rhopaper/.local/share/Steam/steamapps/common/小小的身影，重叠的内心"，游戏均原生支持Linux。
请使用git进行版本管理，遵循语义化版本号；完成开发工作后的第一个可用版本的版本号必须低于或等于0.1.0，取决于你认为的完成度。每完成一项功能/一个模块均提升一次版本号，方便后期追溯。不限制git提交次数，在任何你认为需要的时候作为“存档”/“备份”来使用。