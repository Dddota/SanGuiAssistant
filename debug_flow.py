"""
归心全流程逐步调试脚本
每一步都截图，清晰看到卡在哪
"""

import time
from app.core.maa_controller import MaaController


class DebugFlow:
    def __init__(self):
        self.step = 0
        self.c = MaaController()
        self.c.init()
        self.c.connect(
            adb_path=r'E:\GAME\MuMu Player 12\shell\adb.exe',
            address='127.0.0.1:16384'
        )
        self.c.load_resource('app/assets')

    def _shot(self, name):
        self.step += 1
        path = f'screenshots/flow_{self.step:02d}_{name}.png'
        self.c.screencap().save(path)
        print(f"  [步骤{self.step}] {name} → {path}")

    def run_node(self, node_name, label=""):
        """执行单个节点，前后各截一张图"""
        print(f"\n▶ 执行节点: {node_name} {label}")
        self._shot(f"{node_name}_before")
        start = time.time()
        result = self.c.run_task(node_name, lambda m: None)
        elapsed = time.time() - start
        self._shot(f"{node_name}_after")
        status = "✅成功" if result else "❌失败"
        print(f"  结果: {status}, 耗时: {elapsed:.1f}s")
        return result

    def full_flow(self):
        """完整流程逐步执行"""
        print("=" * 60)
        print("归心全流程逐步调试")
        print("=" * 60)

        # 第1步：点入口开列表
        r = self.run_node("guixin_find_entry", "点入口")
        if not r:
            print("❌ 入口都打不开，结束")
            return

        # 循环处理每座城
        city_count = 0
        max_cities = 15  # 最多处理15座城防止死循环

        while city_count < max_cities:
            city_count += 1
            print(f"\n{'='*40}")
            print(f"🏙️  第 {city_count} 座城")
            print(f"{'='*40}")

            # 找前往归心按钮
            r = self.run_node("guixin_city_loop", "找前往归心")
            if not r:
                print(f"  找不到前往归心了，所有城处理完了？")
                # 试一次滑动
                r2 = self.run_node("guixin_city_scroll", "滑动翻页")
                r3 = self.run_node("guixin_city_loop_check", "再找一次")
                if not r3:
                    print("  滑完也找不到，结束")
                    break
                continue

            # 归心循环（一次处理一座城的所有次数）
            print(f"  开始归心循环...")
            spin_count = 0
            while spin_count < 10:  # 单城最多10次防止死循环
                spin_count += 1
                r = self.run_node("guixin_city_spin_loop", f"第{spin_count}次归心")
                if not r:
                    print(f"  归心按钮找不到了，这座城归完了")
                    break

            # 关收复城池弹窗
            print(f"  关收复城池弹窗...")
            self.run_node("guixin_dismiss_recover", "关收复城池")

            # 重新点入口开列表
            print(f"  重新打开归心列表...")
            r = self.run_node("guixin_find_entry", "重新点入口")
            if not r:
                print("❌ 重新打开列表失败，结束")
                break

        print(f"\n{'='*60}")
        print(f"共处理了 {city_count - 1} 座城")
        print(f"{'='*60}")


if __name__ == '__main__':
    flow = DebugFlow()
    flow.full_flow()
