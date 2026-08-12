# 三国天下归心 · 一键归心开发进展

**日期**: 2026-08-12
**状态**: 奖励弹窗关闭已修复，待验证

---

## 一、项目结构

```
sangui-ass/
├── main.py                    # 程序入口（GUI启动）
├── requirements.txt           # 依赖列表
├── test_connect.py            # 连接测试脚本
├── app/
│   ├── core/
│   │   ├── maa_controller.py  # MAA控制器封装（连接/截图/点击/任务执行）
│   │   └── task_runner.py     # 后台线程任务运行器
│   ├── view/
│   │   ├── main_window.py     # 主窗口（PyQt6 Fluent，2个Tab）
│   │   ├── guixin_tab.py      # 一键归心Tab
│   │   └── peijiang_tab.py    # 智能配将台Tab（占位）
│   ├── utils/
│   │   └── logger.py          # 日志工具
│   └── assets/
│       ├── image/             # 模板匹配图片
│       ├── pipeline/          # MAA pipeline JSON流程
│       │   └── guixin.json    # 归心流程
│       └── model/             # OCR模型（暂空，GitHub连不上）
├── screenshots/               # 调试截图（大量测试截图）
├── docs/
│   ├── architecture.md        # 架构设计
│   └── guixin-flow.md         # 归心流程设计
└── maa_user/                  # MAA运行时数据
```

---

## 二、已完成

### 1. 环境与基础架构 ✅
- MaaFramework 5.12.3 + PyQt6 + PyQt6-Fluent-Widgets 全部安装
- MAA控制器已实现并验证：连接MuMu、截图、点击都可用
- GUI框架已搭好（主窗口 + 归心Tab + 配将Tab占位）
- 后台任务运行器已实现（线程 + 回调）

### 2. 模板图采集 ✅（但需注意分辨率问题）
| 模板文件 | 用途 | 匹配状态 |
|---|---|---|
| `guixin_entry.png` | 归心入口（底部转盘按钮） | 1.0（但只能在当前分辨率/地图背景下用） |
| `guixin_go_btn.png` | "前往归心"按钮 | 0.99+（稳定） |
| `guixin_spin_btn.png` | 转盘"归心"按钮区域 | 0.9+（稳定） |
| `guixin_close_x.png` | 转盘右上角关闭X | 1.0（稳定） |

### 3. 已验证可工作的节点
- ✅ 点"前往归心" → 进入转盘界面
- ✅ 点转盘归心按钮 → 转动1次（剩余次数-1）
- ✅ 点右上角X → 关闭转盘

---

## 三、当前问题（待解决）

### 问题1：归心入口按钮模板不稳定 ❌
- **原因**：底部转盘按钮上的红色数字会变（16/17/15...），而且地图背景也会变（雪地/沙漠/草地）
- **现象**：换个场景模板匹配度就掉到 0.5 以下
- **方向**：需要更鲁棒的入口识别方式
  - 方案A：只取按钮内圈核心图案（不带数字、不带外圈），已尝试但点击坐标可能不准
  - 方案B：用固定相对坐标（底部从左数第2个按钮，占屏幕宽度比例）
  - 方案C：OCR识别"归心"文字入口

### 问题2：奖励弹窗关闭逻辑 ✅ 已修复
- **原问题**：点屏幕中间 (640, 360) 点在奖励图标上，没点到空白区域
- **修复方案**：
  - 点击坐标改为 (200, 600) — 左下角空白区域
  - 追加第二次点击 (200, 400) — 安全兜底
  - 删除冗余节点：`guixin_dismiss_extra_popup`、`guixin_dismiss_final_check`、`guixin_check_spin_btn_retry`
  - 新增 `guixin_dismiss_recover` 节点 — 处理关闭转盘后可能出现的"收复城池"弹窗
- **验证状态**：待测试

### 问题3：归心循环流程 ✅ 已简化
- 新流程：点归心 → 点击空白×2 → 检查归心按钮 → 继续/关闭
- 删除了多余的弹窗检查节点，逻辑更清晰

### 问题4：城池列表滑动翻页逻辑未验证
- pipeline里写了滑动逻辑但没测过
- 需要确认：城池列表滑动方向、每次滑动距离、最多有多少座城

---

## 四、Pipeline 流程设计（当前版本）

```
guixin_start
  └─ guixin_find_entry（找归心入口按钮，最多重试5次）
       └─ guixin_city_loop（找"前往归心"按钮）
            ├─ 找到 → 点击 → guixin_city_spin_loop
            └─ 找不到 → guixin_city_scroll（滑动翻页，最多8次）
                 └─ guixin_city_loop_check
                      ├─ 找到 → guixin_city_loop
                      └─ 找不到 → guixin_finished（结束）

guixin_city_spin_loop（归心循环）
  ├─ 找到归心按钮 → 点击 → guixin_dismiss_reward
  │    └─ 点击空白(200,600) → guixin_dismiss_reward_2
  │         └─ 点击空白(200,400) → guixin_check_spin_btn
  │              ├─ 找到归心按钮 → guixin_city_spin_loop（继续）
  │              └─ 找不到 → guixin_close_and_return（关闭返回）
  └─ 找不到归心按钮 → guixin_close_and_return（关闭转盘，回列表）

guixin_close_and_return（关闭转盘）
  ├─ 找到关闭X → 点击 → guixin_dismiss_recover
  └─ 找不到 → guixin_close_fallback（固定坐标点击X）→ guixin_dismiss_recover

guixin_dismiss_recover（处理"收复城池"弹窗）
  └─ 点击空白(200,600) → guixin_city_loop（回城池列表）
```

文件位置：`app/assets/pipeline/guixin.json`

---

## 五、环境信息

- **游戏包名**: `com.xy.txgx11`
- **MuMu ADB路径**: `E:\GAME\MuMu Player 12\shell\adb.exe`
- **ADB地址**: `127.0.0.1:16384`
- **截图分辨率**: 1280x720（横屏）
- **Python**: 3.12.3
- **MaaFramework**: 5.12.3

### 关键坐标参考（1280x720分辨率下）
| 元素 | 大致坐标 | 说明 |
|---|---|---|
| 底部归心入口按钮中心 | (398, 565) 附近 | 从左数第2个金色转盘，Y坐标需校准 |
| 城池列表"前往归心" | (870, 282) 附近 | 列表第一个，Y随位置变 |
| 转盘归心按钮中心 | (1000, 610) | 右下角剩余次数区域 |
| 转盘右上角关闭X | (1080, 60) | 稳定 |

### 注意
- 用户提到**窗口拉大了**，不是原始分辨率，所以ADB坐标和视觉坐标可能有映射关系问题
- 但模板匹配是基于截图像素的，只要模板从当前截图裁的，匹配位置就准确
- 之前点"前往归心"和"归心按钮"都成功了，说明模板匹配→点击的链路是通的
- 但点屏幕中间位置(640,360)关弹窗失败，原因待查

---

## 六、下一步优先级

1. **验证奖励弹窗关闭** —— 启动GUI跑一次归心，确认(200,600)能关掉"恭喜获得"弹窗
2. **验证完整单城流程** —— 从城池列表 → 进转盘 → 归心3次 → 关所有弹窗 → 返回列表
3. **验证多城循环 + 滑动翻页** —— 连续处理多座城
4. **入口按钮鲁棒性** —— 解决归心入口识别不稳定的问题
5. **GUI联调完善** —— 进度条、日志实时更新

---

## 七、快速恢复命令

### 测试连接和截图
```bash
python test_connect.py
```

### 测试MAA pipeline任务
```python
from app.core.maa_controller import MaaController
ctrl = MaaController()
ctrl.init()
ctrl.connect(adb_path=r'E:\GAME\MuMu Player 12\shell\adb.exe', address='127.0.0.1:16384')
ctrl.load_resource('app/assets')
result = ctrl.run_task('任务节点名', print)
```

### 启动GUI
```bash
python main.py
```
