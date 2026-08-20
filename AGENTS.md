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

### 发版流程
版本号唯一来源：`app/__init__.py` 里的 `__version__`。改版本号只改这一处。

**标准发版步骤：**
1. 确认 `app/__init__.py` 中 `__version__` 是目标版本（如 `1.1.0`）。
2. git add/commit 所有改动，推送到 `dev1.1`（或对应分支）。
3. 打 tag：`git tag v1.1`（annotated 或 lightweight 均可），推送到 origin：`git push origin v1.1`。
4. tag 推送后，**GitHub** 上 `.github/workflows/release.yml` 会自动触发 Build & Release，把 zip 挂到 Release 页面（文件名 `SanguiHelper-v1.1.0.zip`，含模板图）。
5. **Gitee** 不会自动发版，需本地跑脚本上传：
   ```
   python scripts/publish_release.py --token <Gitee私人令牌>
   ```
   - 脚本从 `app/__init__.py` 读版本号，从 `dist/SanguiHelper-<ver>.zip` 找包。
   - 本地包需先用 `build_release.ps1` 打好（见下）。
   - 按 80MB 分片上传，绕开 Gitee 单附件 100MB 上限；幂等可重跑。
   - 令牌在 https://gitee.com/dashboard/personal_access_tokens 生成，勾选 `projects` 权限。
6. **打本地包**（验证或给 Gitee 上传用）：
   ```
   powershell -ExecutionPolicy Bypass -File build_release.ps1
   ```
   输出：`dist/SanguiHelper-v<版本>.zip`。脚本内第 3 步 Copy 后会自动剔除 `app/assets/data/`（敏感数据），发布包不含 heroes.json 等数据文件。
7. 发布前核查清单（合规）：
   - zip 中 `app/assets/data/` 应为空（0 条目）
   - zip 中模板图应在 `app/assets/image/` 下，约 21 张小按钮图
   - zip 根目录应有 `TERMS_OF_SERVICE.md`

**注意事项：**
- `build.yml` 已删除，现仅保留 `release.yml` 负责 GitHub 自动发版，避免重复发版。
- Gitee→GitHub 自动同步：推送到 gitee 的分支/tag 会自动镜像到 GitHub，通常无需手动推 GitHub；force push 或 tag 强移动时建议直推 GitHub 确保触发。
- 令牌属敏感凭证，由用户保管，agent 不代存。
