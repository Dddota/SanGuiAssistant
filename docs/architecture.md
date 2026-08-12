# 架构设计

面向手游《三国天下归心》的 MAA 类桌面自动化小助手。

## 技术路线

MaaFramework（MAA 官方通用框架）+ Python + PyQt6 GUI。

MaaFramework 是游戏无关的通用自动化引擎，用 JSON 流程配置驱动，内置模板匹配、OCR、点击、等待重试等机制。

## 环境信息

- 游戏包名：`com.xy.txgx11`
- MuMu Player 12 ADB：`E:\GAME\MuMu Player 12\shell\adb.exe`
- ADB 地址：`127.0.0.1:16384`
- 分辨率：720x1280（竖屏）
- Python 3.12.3

## 项目结构

```
sangui-ass/
├── app/
│   ├── __init__.py
│   ├── core/                    # 核心逻辑层
│   │   ├── __init__.py
│   │   ├── maa_controller.py    # MAA 控制器封装（连接/截图/点击）
│   │   └── task_runner.py       # 任务执行器（运行 pipeline，回调日志）
│   ├── view/                    # GUI 视图层
│   │   ├── __init__.py
│   │   ├── main_window.py       # 主窗口（Tab 容器）
│   │   └── guixin_tab.py        # 归心 Tab
│   ├── utils/                   # 工具
│   │   ├── __init__.py
│   │   └── logger.py            # 日志工具
│   └── assets/                  # 运行时资源
│       ├── image/               # 模板图
│       ├── model/
│       │   └── ocr/             # PaddleOCR 模型
│       └── pipeline/            # JSON 流程定义
│           └── guixin.json
├── docs/
│   ├── architecture.md
│   └── guixin-flow.md           # 归心流程设计
├── requirements.txt
└── main.py                      # 入口
```

## 核心模块

### app/core/maa_controller.py

- `connect(adb_path, address)` → 连接模拟器
- `screencap()` → 返回 PIL Image
- `click(x, y)` / `swipe(...)` → 模拟操作
- `load_resource(resource_path)` → 加载 pipeline + 模板图
- `run_task(task_name, callback)` → 执行任务，回调进度

### app/core/task_runner.py

- 封装 MAA Tasker，提供 start/stop/status
- 信号回调：日志输出、进度更新、任务完成/失败
- 支持取消（MAA 的 stop 机制）

### app/view/main_window.py

- 左侧导航栏（归心 Tab、配将 Tab（占位）、设置 Tab）
- 右侧内容区
- 底部状态栏（连接状态/模拟器信息）

### app/view/guixin_tab.py

- 「开始归心」大按钮 + 「停止」按钮
- 进度条 / 统计（已完成城池数 / 总次数）
- 日志文本框（实时滚动）
- 预览区域（显示当前截图）

## 关键决策

- 配将最终目标是纯本地规则引擎，大模型仅作过渡手段。
- SLG 游戏有反作弊风险，纯图像识别 + 模拟点击相对安全，但需注意使用频率。
- 建议从阶段1+2 开始（归心），见效快且能验证技术栈。