# PaperGalFlow

为 Galgame 提供「柚子社式流程图」的模块化工具。首个目标引擎是 Ren'Py，采用**纯文件修补**方式：把剧情图、布局、节点状态逻辑全部固化成 `pgf_*.rpy` 文件写进游戏目录，游戏运行时不再动态解析脚本，删除文件即回滚。

> 当前状态：开发中（v0.0.1，核心模型与布局引擎）。完整的安装/生成流程会在到达 0.1.0 前补齐。

## 模块

| 模块 | Python 包 | 职责 |
| --- | --- | --- |
| `pgf-core` | `pgf_core` | 引擎无关的剧情图模型、节点状态机、布局算法、持久化接口、降级链调度、CLI |
| `pgf-adapter-renpy` | `pgf_adapter_renpy` | Ren'Py 适配器：脚本解析（`.rpy` / `.rpyc` / `.rpa`）、UI 风格提取、screen 代码生成、入口注入与写文件 |
| `pgf-style` | `pgf_style` | 风格 token 模型、从目标游戏提取/回退、翻译为 Ren'Py 样式定义 |

CLI 只依赖 `pgf_core`；适配器通过 `pgf.adapters` entry point 注册后挂载。

## 开发

```bash
# 建议在虚拟环境中
python3 -m venv .venv
. .venv/bin/activate
pip install -e .

# 跑测试（不依赖游戏文件的部分）
python -m unittest discover -s tests -t . -v

# CLI
pgf --help
```

不安装时也可以从源码运行：

```bash
PYTHONPATH=src python -m pgf_core --help
```

## 设计边界

- 流程图在**生成时**固化，运行时不再解析脚本；玩家安装新剧情 Mod 后需要重新生成。
- 回滚 = 删除生成文件；不修改游戏原始文件。
- 第一次可用版本目标为 `v0.1.0`，每完成一个模块/功能递增一个版本号。

详细设计见 [`docs/`](docs/)（随开发补齐）。
