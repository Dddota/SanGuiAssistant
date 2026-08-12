"""阶段1测试：验证 MAA 连接 + 截图。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.maa_controller import MaaController
from app.utils.logger import setup_logger

ADB_PATH = r"E:\GAME\MuMu Player 12\shell\adb.exe"
ADDRESS = "127.0.0.1:16384"


def main():
    setup_logger()
    ctl = MaaController()
    ctl.init()
    ok = ctl.connect(ADB_PATH, ADDRESS)
    print(f"connected: {ok}")
    img = ctl.screencap()
    print(f"screencap size: {img.size}")
    out = Path(__file__).resolve().parent / "screenshots"
    out.mkdir(exist_ok=True)
    img.save(out / "test.png")
    print(f"saved to {out / 'test.png'}")
    ctl.disconnect()


if __name__ == "__main__":
    main()