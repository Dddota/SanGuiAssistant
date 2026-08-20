"""数据模型：战斗地点条目。"""


class BattleLocation:
    """一个战斗地点条目。"""

    def __init__(self, name: str = "", x: int = 0, y: int = 0):
        self.name = name
        self.x = x
        self.y = y
        # 兵力（OCR 可能读不到，用 0 表示未知）
        self.my_troops: int = 0
        self.enemy_troops: int = 0
        # 攻城耗时（s），点击攻城后从右侧红色时间读到；0 表示未判断
        self.cost_time: int = 0
        # 攻击按钮坐标（点击攻城按钮的位置，可选）
        self.attack_btn: tuple[int, int] | None = None
        # 是否可攻打（无法直接攻打时为 False）
        self.attackable: bool = True
        self.skip_reason: str = ""
        # 是否南蛮入侵敌方（敌方列显示为"南蛮"而非 吴/蜀/魏）。
        # 注意：南蛮通常出现在"敌方"国家列，而不是城市名列，
        # 所以不能只靠 name 判定，需在解析行时记录敌方内容。
        self.is_nanman: bool = False
        # 评分（高=优先）
        self.score: float = 0.0

    def __repr__(self):
        return (f"<BattleLocation {self.name} 我:{self.my_troops} "
                f"敌:{self.enemy_troops} 耗时:{self.cost_time}s "
                f"可攻:{self.attackable} 分:{self.score:.1f}>")