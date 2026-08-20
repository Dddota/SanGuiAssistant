# 配将 / 武将功能链：Git 移除归档记录

> **状态**:从 Git 仓库移除，本地文件保留作档案
> **日期**:2026-08-20
> **决策**:C 方案（配将功能链整体从 Git 移除，本地保留）

## 背景

项目早期为《三国天下归心》实现了"配将 / 武将图鉴"相关功能。该功能依赖读取游戏配置生成的武将底表数据（`heroes.json` 等），属于游戏著作权敏感资源。

经代码核查，**该功能链整体是一个未被接入主程序的孤岛**：`PeijiangTab` 未在 `main_window.py` 注册，`task_runner` 中的扫描入口（`scan_user_heroes`）无任何 UI 调用，`team_builder` / `battle_engine` 无外部引用。因此它不随程序启动加载，删除后不影响当前任何已接入功能。

## 决定

为遵守本项目合规整改（`COMPLIANCE_REVIEW.md`）精神，将整条配将/武将功能链**从 Git 版本控制中移除**，**本地源码文件保留**（供后续若需恢复/重构使用），并用 `.gitignore` 防止再次入库。

## 从 Git 移除的文件

### 代码（view / core / data / tools）

| 路径 | 说明 |
|---|---|
| `app/view/peijiang_tab.py` | 配将 Tab（依赖 `hero_lib` / `battle_engine`） |
| `app/core/battle_engine.py` | 对战模拟（读 `hero_lib` 练度） |
| `app/core/team_builder.py` | 配将生成（读 `hero_lib`） |
| `app/core/hero_scanner.py` | 武将详情扫描（读 `user_hero` / `hero_lib`） |
| `app/data/` | 整目录：`hero_data.py` / `hero_lib.py` / `sgtx_loader.py` / `user_hero.py` / `__init__.py` |
| `tools/export_hero_data.py` | 从游戏 byte 导出武将底表的脚本 |

### 数据（app/assets/data/）

| 路径 | 说明 |
|---|---|
| `heroes.json` | 武将数值底表（武力/智力/…），游戏数据，著作权敏感 |
| `hero_candidates.json` | 候选导出中间产物 |
| `heroes_unsolved.json` | 未解析武将数据 |
| `UNIDENTIFIED.md` | 未识别名字清单 |

> 注意：`app/assets/data/*.json` 与 `uniunidentified.md` 已在更早的"角色/模板图著作权整改"中从 Git 移除（`git rm --cached`），本地保留，与本次属同一归档目的。

## .gitignore 新增规则

```gitignore
# 配将/武将功能链（从 Git 移除，本地档案保留；著作权敏感，禁止入库）
app/view/peijiang_tab.py
app/core/battle_engine.py
app/core/team_builder.py
app/core/hero_scanner.py
app/data/
tools/export_hero_data.py
```

配合已有规则：

```gitignore
app/assets/image/*.png
app/assets/data/*.json
app/assets/data/UNIDENTIFIED.md
```

## 调用链与移除安全性说明

```
peijiang_tab.py ──> battle_engine.py / hero_scanner.py / hero_lib / user_hero
                           │                     │
task_runner 扫描入口(无 UI 调用)  team_builder(无引用)
```

- `hero_lib.load()` 在数据文件缺失时仅返回空库、**不会抛错**，故移除数据不破坏程序。
- 全部文件为**孤岛**（无主流程引用），从 Git 移除用于避免著作权资源传播；本地保留供可能的功能恢复/重构参考。

## 后续

- 若将来要恢复配将功能，直接基于本地 `app/data/` 与相关模块重新接入即可，但需再次评估游戏数据的使用合规性。
- 若确需彻底清除，可另行删除本地文件（本记录不含删除本地文件）。