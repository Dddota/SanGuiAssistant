"""
归心功能分步调试脚本（每步截图版）
=====================
每个节点执行前后都自动截图，方便排查问题
"""

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


def debug_step(node_name, step_num=0):
    """执行单个节点，前后各截一张图"""
    print(f"\n{'='*60}")
    print(f"步骤 {step_num}: 执行节点 [{node_name}]")
    print(f"{'='*60}")

    c = get_controller()

    # 执行前截图
    before = c.screencap()
    before.save(f'screenshots/debug_{step_num:02d}_{node_name}_before.png')
    print(f"  [执行前] 已截图: debug_{step_num:02d}_{node_name}_before.png")

    # 执行
    start = time.time()
    result = c.run_task(node_name, lambda m: print(f"  MAA: {str(m)[:150]}"))
    elapsed = time.time() - start

    # 执行后截图
    after = c.screencap()
    after.save(f'screenshots/debug_{step_num:02d}_{node_name}_after.png')
    print(f"  [执行后] 已截图: debug_{step_num:02d}_{node_name}_after.png")
    print(f"  耗时: {elapsed:.2f}s, 结果: {'✅ 成功' if result else '❌ 失败'}")

    return result


if __name__ == '__main__':
    # ====== 选择要调试的节点和步骤号 ======
    # 用法：debug_step("节点名", 步骤号)

    # debug_step("guixin_find_entry", 1)       # 入口按钮
    # debug_step("guixin_city_loop", 2)         # 前往归心
    # debug_step("guixin_city_spin_loop", 3)    # 归心一次
    # debug_step("guixin_dismiss_reward", 4)    # 关奖励
    # debug_step("guixin_close_and_return", 5)  # 关转盘
    # debug_step("guixin_dismiss_recover", 6)   # 关收复城池
    #debug_step("guixin_city_loop", 1)
    print("\n提示：编辑 debug_step.py，取消注释对应 debug_step 行后运行")
