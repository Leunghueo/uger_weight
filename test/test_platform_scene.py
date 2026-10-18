"""称重台俯视示意图无头测试。

运行：QT_QPA_PLATFORM=offscreen python test/test_platform_scene.py
（脚本内已默认设置 offscreen，可直接用 python 运行）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "libs")):
    if p not in sys.path:
        sys.path.insert(0, p)

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.view_measure.platform_cards_legacy import PlatformWidget  # noqa: E402
from ui.view_measure.platform_scene import (  # noqa: E402
    PlatformSceneView,
    PlatformTile,
    alerts_from_results,
)


def _fake_results() -> dict:
    """模拟 measure.calculate() 返回（含各类问题）。"""
    return {
        "imbalance": [
            {"type": "轮重超范围", "detail": "称重台5轮重250.0kN超出[100,200]kN"},
            {"type": "轮重差偏大", "detail": "轴1-2轮重差15.0kN（预警10kN）"},
            {"type": "轮重差超限", "detail": "轴3-4轮重差25.0kN（超限20kN）"},
            {"type": "采集异常", "detail": "称重台9无数据"},
            {"type": "车重超范围", "detail": "整车重5000.0kN超出[200,400]kN"},
        ],
    }


def main() -> None:
    app = QApplication([])

    # 1. 创建视图：18 个台体
    view = PlatformSceneView()
    assert len(view._tiles) == 18, f"台体数量应为18，实际{len(view._tiles)}"
    assert set(view._tiles) == set(range(1, 19))
    print("PASS 1: 视图创建，18 个台体")

    # 2. 灌模拟数据刷新（含离线）
    values = {p: round(100.0 + p, 1) for p in range(1, 19)}
    values[7] = None   # 离线
    values[9] = None   # 离线（与 _fake_results 中台9采集异常一致）
    values[18] = None  # 离线
    view.set_values(values)
    assert view._tiles[7]._state == "offline", "台7应为离线态"
    assert view._tiles[18]._state == "offline", "台18应为离线态"
    assert view._tiles[1]._state == "normal", "台1应为正常态"
    print("PASS 2: 数值刷新，离线台正确显示灰色")

    # 3. 车型高亮切换：18台 -> 12台
    view.set_highlight(list(range(1, 19)))  # CRH380AL
    assert view._tiles[1]._state == "highlight"
    assert view._tiles[7]._state == "offline", "离线优先于高亮"
    view.set_highlight([1, 2, 5, 6, 9, 10, 11, 12, 13, 14, 17, 18])  # CRH2B
    assert view._tiles[3]._state == "normal", "台3不在CRH2B内，应回落为正常"
    assert view._tiles[5]._state == "highlight", "台5应在CRH2B内高亮"
    print("PASS 3: 车型高亮切换（18台/12台）")

    # 4. alerts 映射：warn / over
    alerts = alerts_from_results(_fake_results())
    assert alerts.get(5) == "over", f"台5轮重超范围应为over，实际{alerts.get(5)}"
    assert alerts.get(1) == "warn" and alerts.get(2) == "warn", "轴1-2轮重差偏大应映射台1/2为warn"
    assert alerts.get(3) == "over" and alerts.get(4) == "over", "轴3-4轮重差超限应映射台3/4为over"
    assert alerts.get(9) == "over", "台9采集异常应为over"
    assert "车重超范围" not in str(alerts), "整车级问题不应映射到单台"
    view.set_alerts(alerts)
    assert view._tiles[5]._state == "over"
    assert view._tiles[1]._state == "warn"
    assert view._tiles[9]._state == "offline", "台9无值，离线优先于采集异常告警"
    print("PASS 4: 预警/超限映射与着色")

    # 5. 告警清除后回落
    view.set_alerts({})
    assert view._tiles[5]._state == "highlight", "清除告警后台5应回落为高亮"
    print("PASS 5: 告警清除状态回落")

    # 6. 渲染不崩：grab + 缩放
    view.resize(1200, 400)
    view.show()
    app.processEvents()
    img = view.grab()
    assert not img.isNull() and img.width() > 0
    view.resize(600, 200)  # 触发 fitInView 自适应
    app.processEvents()
    img2 = view.grab()
    assert not img2.isNull()
    # 台体错位检查：所有台体中心应在场景矩形内
    rect = view._scene.sceneRect()
    for p, tile in view._tiles.items():
        pos = tile.pos()
        assert rect.contains(pos), f"台{p}中心超出场景：{pos}"
    print("PASS 6: 渲染 + 缩放自适应，台体无错位")

    # 7. 旧卡片实现可正常导入实例化（回退路径可用）
    w = PlatformWidget(1)
    w.set_value(123.4)
    w.set_highlight(True)
    assert w.value_label.text() == "123.4"
    print("PASS 7: 旧卡片备份模块可用")

    # 8. 空值/边界：全部 None、全空 alerts
    view.set_values({})
    assert all(t._state == "offline" for t in view._tiles.values())
    view.set_values(values)
    view.set_highlight([])
    view.set_alerts({"99": "over", "1": "bogus"})  # 非法台号/非法等级应被忽略
    assert view._tiles[1]._state == "normal"
    print("PASS 8: 边界输入鲁棒")

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
