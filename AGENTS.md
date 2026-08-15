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

### vision 子代理职责边界
- vision 子代理的唯一职责是"描述看到的内容"（布局、文本、颜色、元素位置等所见即所得）。
- **禁止**把坐标推断、修复方案、实现思路交给 vision 子代理；这些统由主 agent 完成。
- 给 vision 的 prompt 只要求"描述所见"，不要要求它给方案或预研坐标。
- **优先主 agent**：当主 agent 自己能直接看图完成任务时，优先主 agent 自己完成，不调用 vision；仅当主 agent 无法看图时才委派 vision。
