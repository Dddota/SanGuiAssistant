# 三归小助手 (SanGuiAssistant)

面向手游《三国天下归心》的 MAA 类桌面自动化小助手，运行于 MuMu Player 12 模拟器。

> ## ⚠️ 免责声明
>
> - 本工具**仅供学习交流使用**，用于探索桌面自动化与计算机视觉技术，**不用于任何商业代练、打金、账号交易等盈利性活动**。
> - 使用本工具可能违反游戏运营商服务条款，导致**账号封禁、游戏数据损失**等后果，**由用户自行承担一切风险，开发者不对任何损失负责**。
> - 本工具与《三国天下归心》开发商**恺英网络及其关联单位无任何关联**，不对任何相关事务负责或背书。
> - 本工具仅为实现界面识别而随发布包内置部分游戏画面模板图（用于模板匹配），**各模板图的著作权归权利人（恺英网络）所有**；本工具不包含任何游戏客户端素材数据资源。模板图位于 `app/assets/image/`，用户可自行替换或补充。
> - "三国天下归心"为恺英网络的游戏名称/商标，本项目不使用该名称进行任何商业活动。完整条款见 [TERMS_OF_SERVICE.md](TERMS_OF_SERVICE.md)。
>
> 开始使用即表示您已满 18 周岁并同意 [用户协议](TERMS_OF_SERVICE.md) 全部条款。

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

程序同时从 GitHub Release 与 Gitee Release 读取最新版本（均匿名，无需 token），取版本更高者；同版本优先走 Gitee。发一个可被自动更新的新版本，完整流程如下：

**GitHub 侧由 Actions 自动打包，Gitee 侧本地分卷上传**

GitHub 海外节点直传 Gitee 会被跨境链路阻断（大 zip 上传必超时），且 Gitee 单附件有 100M 大小上限，故拆成两步：

1. 更新 `app/__init__.py` 的 `__version__`（如 `1.0.1`）。
2. 提交并推送，再打 tag 推送到 Gitee（经同步勾子镜像到 GitHub）：
   ```bash
   git add -A && git commit -m "v1.0.1"
   git push origin master
   git tag v1.0.1
   git push origin v1.0.1
   ```
   Gitee→GitHub 同步勾子会把代码与 tag 带到 GitHub，push tag 触发反馈同步到 GitHub。GitHub Actions 在 windows runner 上打包，产出 GitHub Release 附件的 `SanguiHelper-v1.0.1.zip`（GitHub 无大小上限）。不依赖 `GITEE_TOKEN`，GitHub 侧无需配置 secret（`verify-token.yml` 属历史验证，可删）。
3. 本地把同一 zip 上传到 Gitee Release（分卷，绕开 100M 单附件上限；需 Gitee 私人令牌，勾选 projects 权限）：
   ```powershell
   python scripts/publish_release.py --token <私人令牌> [--body "发布说明"]
   ```
   脚本幂等：自动创建 tag `v<__version__>`，再把 zip 切成 80MB 分片（`SanguiHelper-v1.0.1.zip.001/.002/...`）逐个上传。客户端自动更新会下载全部分片、按序拼回完整包再解压。

无论哪种源，上传完成后，已安装的旧版程序下次启动（或点设置里的"检查更新"）即可发现并一键更新。

## 目录结构

- `main.py`：程序入口
- `build.spec` / `build_release.ps1`：PyInstaller 打包配置与一键发布脚本
- `scripts/publish_release.py`：上传发布 zip 到 Gitee Release，自动分卷绕开 100M 单附件上限（本地手动发版用）
- `scripts/gitee_relay.py`：国内 Linux 服务器中继脚本（已被本地方卷上传取代，保留备查）
- `app/core/`：核心逻辑
  - `maa_controller.py`：封装 MAA 连接 / 截图 / 点击 / 滑动 / 任务执行 / 识别
  - `task_runner.py`：后台单线程任务运行器（连接 + 任务互斥执行）
  - `features.py`：任务注册表 + BatchRunner 顺序批处理
  - `guixin / sinan_engine / zhan_gong_engine / trade_engine`：各功能引擎
  - `updater.py` / `update_worker.py`：自动更新核心逻辑 + 后台 UI Worker
  - `config.py`：全局配置与持久化（含 ADB 自动检测）
- `app/view/`：GUI 页面
  - `main_window.py`：主窗口（三栏式布局）与导航注册
  - `dashboard.py` / `settings_panel.py` / `log_panel.py` / `status_bar.py`：任务清单、参数面板、共享日志、全局状态栏
  - `guixin_tab.py` / `sinan_tab.py` / `trade_tab.py`：功能页
  - `settings_tab.py` / `debug_tab.py`：设置与调试（底部导航弹窗）
- `app/assets/pipeline/`：MAA 流程 JSON（`guixin.json` / `sinan.json` / `trade.json`；战功已重构为核心代码实现，不依赖 pipeline JSON）
- `app/assets/image/`：模板图（识别所用）。**为保护游戏著作权，模板图与游戏数据不出现在 Git 仓库中**，请用户自行截图放入（详见 `app/assets/image/README.md`）
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
