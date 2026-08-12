# AGENTS.md

## 开发规则

### 模板图不要自己截
- 新增功能时，只需建好代码框架和 pipeline 节点结构。
- 需要的模板图（按钮、入口、弹窗等）列出来，由用户自己截图放到 `app/assets/image/` 下。
- 禁止用代码去调用截图、操作模拟器采集模板。

### 功能添加规范
- 每个新功能对应一个 pipeline JSON（`app/assets/pipeline/<name>.json`）。
- 每个新功能对应一个 Tab（`app/view/<name>_tab.py`）。
- 在 `app/view/main_window.py` 里注册导航。
- 遵循归心（guixin）的实现模式：MaaController + TaskRunner + Tab UI。
