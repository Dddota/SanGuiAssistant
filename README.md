# 三归小助手 (SanGuiAssistant)

面向手游《三国天下归心》的 MAA 类桌面自动化小助手，运行于 MuMu Player 12 模拟器。

## 功能

支持在左侧任务清单勾选多个任务，一键按顺序批量执行（同一时刻互斥只跑一个），进度实时输出到右侧共享日志，底部状态栏显示连接状态、当前任务与持续执行时间。

- **一键归心**：自动进入归心系统，逐个城池转盘抽奖，把所有归心次数用完。
- **自动司南**：自动使用所有可用的司南，领取对应奖励；连续 3 次使用司南未收货宝箱则判定任务失败并进入下一任务。
- **自动刷战功**：从情报城池战事列表识别战斗地点，优先攻打敌众我寡且距离近的城池，自动补兵出征；持续循环刷取直到粮食耗尽、无可攻打目标或累计攻打次数达到上限（默认 20，可配置），攻打失败的城市本会话内标记换城，保证收敛。
- **辅助交易**：自动扫描交易行中关注物品的上架与求购信息。
- **软件更新**：启动时自动检查 Gitee Release 是否有新版本，可在"设置"里手动检查并一键更新（下载 zip → 独立脚本覆盖替换 → 自动重启）。
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

脚本自动完成：清理残留进程 → PyInstaller 构建（onedir）→ 复制 `app/assets` 资源 → 打包 `dist/SanguiHelper-v<版本>.zip`（内置 MaaFw 原生 DLL、OCR 模型与全部模板图，首次启动自动检测 ADB）。版本号统一从 `app/__init__.py` 的 `__version__` 读取。

### 发版与自动更新

程序从 Gitee Release 读取最新版本（匿名，无需 token）。发一个可被自动更新的新版本，有**两种**方式：

**方式 A：全自动（推荐，GitHub Actions 白嫖构建机）**

利用 Gitee→GitHub 的同步勾子，推 tag 即可自动在 GitHub 免费构建机上完成打包并双发到 GitHub / Gitee Release：

1. 更新 `app/__init__.py` 的 `__version__`（如 `1.1.0`）。
2. 提交并推送（会经同步勾子镜像到 GitHub）：
   ```bash
   git add -A && git commit -m "v1.1.0"
   git push origin master
   ```
3. 打 tag 并推送，触发 Actions：
   ```bash
   git tag v1.1.0
   git push origin v1.1.0
   ```
4. 到 GitHub 仓库 Actions 页确认构建通过；完成后 GitHub 与 Gitee 的 Release 都会有 `SanguiHelper-v1.1.0.zip`。

需要一次的配置（见 `.github/workflows/release.yml`）：
- GitHub 仓库（`Dddota/SanGuiAssistant`）需**公开**，且能被同步勾子带上 tag。
- 在 GitHub 仓库 **Settings → Secrets and variables → Actions** 添加一个 secret `GITEE_TOKEN`，值为 Gitee 私人令牌（勾选 projects 权限），用于把产物上传到 Gitee Release。

客户端仍从 Gitee Release 读取更新，国内下载快。

**方式 B：纯本地手动发版**

1. 更新 `app/__init__.py` 的 `__version__`（如 `1.1.0`）。
2. 本地打包：`powershell -ExecutionPolicy Bypass -File build_release.ps1`（产物 `dist/SanguiHelper-v1.1.0.zip`）。
3. 上传到 Gitee Release（需 Gitee 私人令牌，勾选 projects 权限）：

   ```powershell
   python scripts/publish_release.py --token <私人令牌> [--body "发布说明"]
   ```

   脚本自动创建 tag `v<__version__>` 并上传 zip。

无论哪种方式，上传完成后，已安装的旧版程序下次启动（或点设置里的"检查更新"）即可发现并一键更新。

## 目录结构

- `main.py`：程序入口
- `build.spec` / `build_release.ps1`：PyInstaller 打包配置与一键发布脚本
- `scripts/publish_release.py`：上传发布 zip 到 Gitee Release（自动更新数据源）
- `app/core/`：核心逻辑
  - `maa_controller.py`：封装 MAA 连接 / 截图 / 点击 / 滑动 / 任务执行 / 识别
  - `task_runner.py`：后台单线程任务运行器（连接 + 任务互斥执行）
  - `features.py`：任务注册表 + BatchRunner 顺序批处理
  - `guixin / sinan_engine / zhan_gong_engine / trade_engine / hero_scanner / battle_engine`：各功能引擎
  - `updater.py` / `update_worker.py`：自动更新核心逻辑 + 后台 UI Worker
  - `config.py`：全局配置与持久化（含 ADB 自动检测）
- `app/view/`：GUI 页面
  - `main_window.py`：主窗口（三栏式布局）与导航注册
  - `dashboard.py` / `settings_panel.py` / `log_panel.py` / `status_bar.py`：任务清单、参数面板、共享日志、全局状态栏
  - `guixin_tab.py` / `sinan_tab.py` / `zhan_gong_tab.py` / `trade_tab.py`：功能页
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
| 自动更新 | 检查 Gitee Release + 一键下载替换重启 | 已完成 |

## 许可证

本项目基于 [GNU LGPL v3](LICENSE) 开源。项目动态链接依赖 [MaaFramework](https://github.com/MaaAssistantArknights/MaaFramework)（LGPL-3.0），采用相同许可证以保证兼容。
