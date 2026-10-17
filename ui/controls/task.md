# 任务描述
编写**具有固定样式风格的可复用的通用控件,用于操控`本项目的plc点位`**

### 工作目录说明
工作目录: `src\ui\controls`
已有文件(均为空文件,需要完成):
+ ptLED: 用于**将Bool类型的plc点位状态显示为LED效果**, 灰色=False, 红色=True, 包含`labe+led`, 可配置为上下/左右排列; 
+ ptSlider: 用于**将整数写入Int类型的plc点位**, 效果为`滑动条`, min/max/step可以配置; 失去焦点时触发写入动作;
+ ptToggle: 用于**显示Bool类型且io为输出的plc点位状态,并且可以进行写入操作**, 灰色=False, 红色=True; 切换时即触发写入操作; 写入后**再次读取该点位并更新控件状态**

### 最终效果
+ 要求可以被其他view方便的导入和使用;
+ 要求具有一致的主题风格(尺寸严格设定, 根据宿主页面情况而定)
+ 要求**创建时必须指定pt_name`,在内部完成所有私有过程,最大程度解耦**

### 使用伪代码
```
from ui.controls import PtLed, PtSlider, PtToggle
_led = PtLed(pt_name="手动", layout=上下/左右)
_slider = PtSlider(pt_name="目标温度", min=10,max=100,step=5)
_toggle = PtToggle(pt_name="开关", update=True/False)
...
然后

### 编写说明
+ 分别在各自的文件中编写控件, 不要交叉耦合;
+ 数据更新: 控件暴露方法`update()`用于**宿主页面统一更新控件**,自己负责处理外观改变;
+ 数据操作: 如果控件可以操作(toggle/slide), 则**尽量将处理逻辑完全放在控件内部, 尽可能不暴露信号和方法** 
+ plc控制: 每个控件内部直接导入`runtime的plc`, 以便可以直接访问, 不需要传入参数;
+ 风格: 每个控件的风格尽量复用`runtime的themes`指定的`qss文件`, **尽量不要内部重复编写qss**
