"""分段标定设置弹窗。

为每个 VSP 点位设置分段线性标定参数：
- segs：标定点列表，格式 "采集值@计算值"，换算为分段线性函数
  （单点按比例换算，多点按分段线性插值）
- add：标定后的整体偏移，叠加在 segs 换算结果上

真值 = segs(采集值) + add。保存后写回 vsp.json 并即时更新运行中的
点位对象；"标零"按钮读取当前真值并预填可将其清零的 add（需点保存生效）。
"""

from .launcher import FitLauncher
from .view import Window

__all__ = ["FitLauncher", "Window"]
