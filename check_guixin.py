"""
归心功能分步调试脚本（增强日志版）
=====================
使用方法：
  1. 确保模拟器已打开游戏，停在对应界面
  2. 取消注释对应测试函数，运行脚本
  3. 按顺序调试：check_1_connection → check_2_entry → check_3_go_btn → ...
"""

import json
import time
from app.core.maa_controller import MaaController


def get_controller():
    c = MaaController()
    c.init()
    c.connect(
        adb_path=r'E:\GAME\MuMu Player 12\shell\adb.exe',
        address='127.0.0.1:16384'
    )
    c.load_resource('app/assets')
    return c


def _parse_details(raw):
    """尝试解析 MAA 日志详情，提取有用信息"""
    try:
        # raw 可能是 dict 也可能是字符串
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.startswith("{"):
            return json.loads(raw)
    except:
        pass
    return {"raw": str(raw)}


def make_logger(label=""):
    """创建精简日志回调，只打关键信息"""
    start = time.time()

    def _log(msg):
        # 只处理 Tasker 相关事件
        if not isinstance(msg, str):
            return

        # 提取事件名和详情
        if not msg.startswith("["):
            return

        end = msg.find("]")
        if end < 0:
            return

        event = msg[1:end]
        detail_str = msg[end+1:].strip()

        # 跳过不重要的事件
        skip_events = [
            "Resource.Loading", "Node.NextList.Starting", "Node.NextList.Succeeded",
            "Node.NextList.Failed", "Node.Action.Starting", "Node.Recognition.Starting",
            "Node.PipelineNode.Starting"
        ]
        for s in skip_events:
            if event.endswith(s) or event.startswith(s):
                return

        # 解析详情
        try:
            details = json.loads(detail_str) if detail_str.startswith("{") else {}
        except:
            details = {}

        if not isinstance(details, dict):
            return

        name = details.get("name", "")
        elapsed = time.time() - start

        # 识别结果
        if "Recognition.Succeeded" in event or "Recognition.Failed" in event:
            reco = details.get("reco_details", {})
            algo = reco.get("algorithm", "")
            if algo == "TemplateMatch":
                detail = reco.get("detail", {})
                best = detail.get("best", {})
                score = best.get("score", 0) if best else 0
                box = reco.get("box", None)
                status = "✅" if "Succeeded" in event else "❌"
                print(f"[{elapsed:5.1f}s] {status} 识别 {name}: score={score:.3f}, box={box}")
            return

        # 动作结果
        if "Action.Succeeded" in event:
            action = details.get("action_details", {})
            act = action.get("action", "")
            detail = action.get("detail", {})
            point = detail.get("point", "")
            print(f"[{elapsed:5.1f}s] 👆 点击 {name}: {act} at {point}")
            return

        # 节点完成
        if "PipelineNode.Succeeded" in event:
            print(f"[{elapsed:5.1f}s] ✅ 节点完成: {name}")
            return

        if "PipelineNode.Failed" in event:
            print(f"[{elapsed:5.1f}s] ❌ 节点失败: {name}")
            return

        # 任务开始/结束
        if "Task.Starting" in event:
            print(f"[{elapsed:5.1f}s] 🚀 任务开始: {details.get('entry','')}")
            return

        if "Task.Failed" in event or "Task.Succeeded" in event:
            status = "✅成功" if "Succeeded" in event else "❌失败"
            print(f"[{elapsed:5.1f}s] 🏁 任务{status}: {details.get('entry','')}")
            return

    return _log


def check_1_connection():
    """测试1：连接 + 截图（验证基础链路通不通）"""
    print("=" * 60)
    print("测试1：连接 + 截图")
    c = get_controller()
    img = c.screencap()
    img.save('screenshots/check_1_screencap.png')
    print(f"  截图尺寸: {img.size}")
    print("  截图已保存到 screenshots/check_1_screencap.png")
    print("  ✅ 连接正常")
    print("=" * 60)


def check_2_entry():
    """测试2：归心入口按钮"""
    print("=" * 60)
    print("测试2：归心入口按钮")
    c = get_controller()
    log = make_logger("入口")
    result = c.run_task('guixin_find_entry', log)
    print(f"  结果: {'✅ 成功' if result else '❌ 失败'}")
    c.screencap().save('screenshots/check_2_after_entry.png')
    print("  截图已保存到 screenshots/check_2_after_entry.png")
    print("=" * 60)
    return result


def check_3_go_btn():
    """测试3：前往归心按钮"""
    print("=" * 60)
    print("测试3：前往归心按钮")
    c = get_controller()
    log = make_logger("前往")
    result = c.run_task('guixin_city_loop', log)
    print(f"  结果: {'✅ 成功' if result else '❌ 失败'}")
    c.screencap().save('screenshots/check_3_after_go.png')
    print("  截图已保存到 screenshots/check_3_after_go.png")
    print("=" * 60)
    return result


def check_4_spin_once():
    """测试4：归心一次 + 关奖励"""
    print("=" * 60)
    print("测试4：归心一次 + 关奖励")
    c = get_controller()
    log = make_logger("归心")
    result = c.run_task('guixin_city_spin_loop', log)
    print(f"  结果: {'✅ 成功' if result else '❌ 失败'}")
    c.screencap().save('screenshots/check_4_after_spin.png')
    print("  截图已保存到 screenshots/check_4_after_spin.png")
    print("=" * 60)
    return result


def check_5_close_spin():
    """测试5：关闭转盘返回列表"""
    print("=" * 60)
    print("测试5：关闭转盘返回列表")
    c = get_controller()
    log = make_logger("关闭")
    result = c.run_task('guixin_close_and_return', log)
    print(f"  结果: {'✅ 成功' if result else '❌ 失败'}")
    c.screencap().save('screenshots/check_5_after_close.png')
    print("  截图已保存到 screenshots/check_5_after_close.png")
    print("=" * 60)
    return result


def check_6_full():
    """测试6：完整归心流程（全部城池）"""
    print("=" * 60)
    print("测试6：完整归心流程")
    c = get_controller()
    log = make_logger("全流程")
    result = c.run_task('guixin_start', log)
    print(f"  结果: {'✅ 成功' if result else '❌ 失败'}")
    c.screencap().save('screenshots/check_6_full_done.png')
    print("  截图已保存到 screenshots/check_6_full_done.png")
    print("=" * 60)
    return result


def check_click(x, y, label="点击测试"):
    """工具：点击指定坐标并截图（调试用）"""
    print(f"点击测试: {label} ({x}, {y})")
    c = get_controller()
    c.click(x, y)
    time.sleep(1.5)
    c.screencap().save(f'screenshots/click_{x}_{y}.png')
    print(f"  截图已保存到 screenshots/click_{x}_{y}.png")


if __name__ == '__main__':
    # ====== 取消注释你要测的项 ======

    # check_1_connection()
   #check_2_entry()
    # check_3_go_btn()
    # check_4_spin_once()
    # check_5_close_spin()
    check_6_full()

    # 调试坐标用：
    # check_click(640, 680, "底部中间空白")

    print("\n提示：编辑 check_guixin.py，取消注释对应测试项后运行")
