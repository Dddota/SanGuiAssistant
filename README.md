# 三归小助手 (SanGuiAssistant)

面向手游《三国天下归心》的 MAA 类桌面自动化小助手，运行于 MuMu Player 12 模拟器。

## 功能

- **一键归心**：自动进入归心系统，逐个城池转盘抽奖，把所有归心次数用完。
- **自动司南**：自动使用所有可用的司南，领取对应奖励。
- **自动刷战功**：从情报城池战事列表识别战斗地点，优先攻打敌众我寡且距离近的城池，自动补兵出征。
- **智能配将台**（规划中）：自动截图识别武将数据，基于本地规则引擎推荐最优阵容。
- **设置**：连接参数（ADB 路径 / 模拟器地址 / 资源目录）可编辑并持久化。
- **调试**：选择模板对当前屏幕做模板匹配识别，验证识别效果。
- **全局状态栏**：底部实时显示连接状态、当前任务，并提供全局开始/停止。

## 技术栈

- [MaaFramework](https://github.com/MaaAssistantArknights/MaaFramework)（通用自动化引擎，JSON 流程驱动）
- Python 3.12 + PyQt6 + PyQt6-Fluent-Widgets（GUI）
- MAA 内置 PaddleOCR（中文 OCR）

## 环境要求

- Windows
- MuMu Player 12 模拟器（竖屏 720x1280）
- Python 3.12+

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

首次启动会自动连接模拟器；连接参数可在"设置"页调整并持久化。

## 目录结构

- `main.py`：程序入口
- `app/core/`：核心逻辑
  - `maa_controller.py`：封装 MAA 连接 / 截图 / 点击 / 滑动 / 任务执行 / 识别
  - `task_runner.py`：后台单线程任务运行器（连接 + 任务互斥执行）
  - `config.py`：全局配置与持久化
- `app/view/`：GUI 页面
  - `main_window.py`：主窗口与导航注册
  - `guixin_tab.py` / `sinan_tab.py` / `peijiang_tab.py`：功能页
  - `settings_tab.py`：连接参数设置
  - `debug_tab.py`：识别调试
  - `status_bar.py`：全局底部状态栏
- `app/assets/pipeline/`：MAA 流程 JSON（如 `guixin.json`）
- `app/assets/image/`：模板图（识别所用）

详细架构见 `docs/architecture.md`。

## 开发计划

| 阶段 | 内容 | 状态 |
|---|---|---|
| 环境打通 + MaaFramework 跑通 | MAA 连接、截图、点击 | 已完成 |
| 一键归心自动化 | 城池转盘归心流程 | 已完成 |
| 自动司南 | 司南使用流程 | 已完成 |
| GUI 整合 | 功能页 + 状态栏 + 设置 + 调试 | 已完成 |
| 武将数据采集（OCR + 翻页） | 配将台数据源 | 规划中 |
| 配将规则引擎 | 智能配将台 | 规划中 |

## 许可证

本项目基于 [GNU LGPL v3](LICENSE) 开源。项目动态链接依赖 [MaaFramework](https://github.com/MaaAssistantArknights/MaaFramework)（LGPL-3.0），采用相同许可证以保证兼容。