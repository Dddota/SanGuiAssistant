# 三归小助手 (SanGuiAssistant)

面向手游《三国天下归心》的 MAA 类桌面自动化小助手，运行于 MuMu Player 12 模拟器。

## 功能

支持在左侧任务清单勾选多个任务，一键按顺序批量执行（同一时刻互斥只跑一个），进度实时输出到右侧共享日志，底部状态栏显示连接状态、当前任务与持续执行时间。

- **一键归心**：自动进入归心系统，逐个城池转盘抽奖，把所有归心次数用完。
- **自动司南**：自动使用所有可用的司南，领取对应奖励；连续 3 次使用司南未收货宝箱则判定任务失败并进入下一任务。
- **自动刷战功**：从情报城池战事列表识别战斗地点，优先攻打敌众我寡且距离近的城池，自动补兵出征；持续循环刷取直到粮食耗尽、无可攻打目标或累计攻打次数达到上限（默认 20，可配置），攻打失败的城市本会话内标记换城，保证收敛。
- **辅助交易**：自动扫描交易行中关注物品的上架与求购信息。
- **智能配将台**：本地武将库筛选 + 选择练度构建阵容并估算战力（第 1 层已实现；识别用户武将、模拟作战克制对比为后续规划）。
- **设置**：连接参数（ADB 路径 / 模拟器地址 / 资源目录）可编辑并持久化，ADB 支持一键自动检测（常见模拟器路径 + PATH 探测）。
- **调试**：选择模板对当前屏幕做模板匹配识别，验证识别效果。
- **全局状态栏**：底部实时显示连接状态、当前任务（含持续执行时间），并提供全局开始/停止。

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

首次启动会自动连接模拟器（未配置 ADB 路径时自动检测）；连接参数可在"设置"弹窗中调整并持久化。

## 打包发布（无需 Python 环境）

项目内置 PyInstaller 一键打包脚本，产物为免安装 zip 压缩包，目标机器无需安装 Python 与任何依赖：

```powershell
powershell -ExecutionPolicy Bypass -File build_release.ps1
```

脚本自动完成：清理残留进程 → PyInstaller 构建（onedir）→ 复制 `app/assets` 资源 → 打包 `dist/SanguiHelper-v0.1.zip`（内置 MaaFw 原生 DLL、OCR 模型与全部模板图，首次启动自动检测 ADB）。

## 目录结构

- `main.py`：程序入口
- `build.spec` / `build_release.ps1`：PyInstaller 打包配置与一键发布脚本
- `app/core/`：核心逻辑
  - `maa_controller.py`：封装 MAA 连接 / 截图 / 点击 / 滑动 / 任务执行 / 识别
  - `task_runner.py`：后台单线程任务运行器（连接 + 任务互斥执行）
  - `features.py`：任务注册表 + BatchRunner 顺序批处理
  - `guixin / sinan_engine / zhan_gong_engine / trade_engine / hero_scanner / battle_engine`：各功能引擎
  - `config.py`：全局配置与持久化（含 ADB 自动检测）
- `app/view/`：GUI 页面
  - `main_window.py`：主窗口（三栏式布局）与导航注册
  - `dashboard.py` / `settings_panel.py` / `log_panel.py` / `status_bar.py`：任务清单、参数面板、共享日志、全局状态栏
  - `guixin_tab.py` / `sinan_tab.py` / `zhan_gong_tab.py` / `trade_tab.py` / `peijiang_tab.py`：功能页
  - `settings_tab.py` / `debug_tab.py`：设置与调试（底部导航弹窗）
- `app/data/`：武将数据（图鉴 / 用户武将 / 游戏数据加载）
- `app/assets/pipeline/`：MAA 流程 JSON（`guixin.json` / `sinan.json` / `zhan_gong.json` / `trade.json`）
- `app/assets/image/`：模板图（识别所用）
- `app/assets/model/ocr/`：OCR 模型

详细架构见 `docs/architecture.md`。

## 开发计划

| 阶段 | 内容 | 状态 |
|---|---|---|
| 环境打通 + MaaFramework 跑通 | MAA 连接、截图、点击 | 已完成 |
| 一键归心自动化 | 城池转盘归心流程 | 已完成 |
| 自动司南 | 司南使用 + 未收货失败判定 | 已完成 |
| 自动刷战功 | 持续刷取直到粮尽/上限/无目标 | 已完成 |
| 辅助交易 | 交易行上架/求购信息扫描 | 已完成 |
| GUI 整合 | 三栏布局 + 任务清单 + 状态栏 + 设置 + 调试 | 已完成 |
| 打包发布 | PyInstaller 一键打包脚本 | 已完成 |
| 配将台第 1 层 | 本地武将筛选 + 战力估算 | 已完成 |
| 配将台第 2/3 层 | 识别用户武将 / 模拟作战克制对比 | 规划中 |

## 许可证

本项目基于 [GNU LGPL v3](LICENSE) 开源。项目动态链接依赖 [MaaFramework](https://github.com/MaaAssistantArknights/MaaFramework)（LGPL-3.0），采用相同许可证以保证兼容。
