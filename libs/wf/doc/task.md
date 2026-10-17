
## 构建基于状态机的异步工作流引擎 (Workflow Engine)

**角色：** 你是一位资深的 Python 软件架构师，擅长异步编程（asyncio）和复杂业务流程的建模。

**任务目标：** 请根据以下详细设计规范，实现一套名为 `WorkflowEngine` 的类库。该类库由 `Workflow` 调度类和 `Node` 执行基类及其派生类组成。

### 1. 数据结构设计 (JSON Schema)
工作流由一个 JSON 配置驱动，请确保代码能解析并运行以下结构的配置：
* **Workflow 配置**: 包含 `name`, `ctime`, `desc`, `nodes` (一个字典，Key 为 NodeID，Value 为 Node 配置)。
* **Node 配置**: 包含 `type` (plc|sys|select|loop_begin|loop_end), `args` (参数字典), `next` (列表，存储后续 NodeID)。

### 2. 核心类实现规范

#### A. Node 基类与派生类
* **状态管理**: Node 具有 `idle`, `running`, `done`, `error`, `stopped` 状态。
* **核心方法**:
    * `async act()`: 抽象方法。目前统一用 `asyncio.sleep(n)` 模拟耗时操作。
    * `next()`: 返回下一个要执行的 NodeID。如果是 `select` 类型，需模拟用户选择逻辑；如果是普通类型，返回 `next` 列表中的唯一元素。
    * `log()`: 记录执行时间、状态和结果。
* **事件触发**: 在执行开始、成功、失败时触发对应的 Event 回调。

#### B. Workflow 调度器
* **状态管理**: 具有 `idle`, `running`, `done`, `error`, `stopped` 状态。
* **生命周期**:
    * `load(json_path)` / `save()`: 配置文件持久化。
    * `start()`: 从 `head` 节点开始执行。
    * `reset()`: 仅在非 running 状态下重置所有节点和工作流状态。
    * `stop()`: 强制中断当前运行的 Node 并停止工作流。
* **执行逻辑 (核心)**: 
    * 使用 `cur_node` 追踪当前进度。
    * 通过循环驱动：执行 `cur_node.act()` -> 获取 `cur_node.next()` -> 更新 `cur_node`。
    * 严格约束：必须从 `head` 开始，至 `end` 结束。

### 3. 逻辑控制节点详解
请特别实现以下节点的逻辑处理：
1.  **Select Node**: 拥有多个 `next` 指向。执行时需挂起并等待外部输入（或通过 Mock 模拟用户随机选择一个 ID 返回）。
2.  **Loop Nodes**: 
    * `loop_begin`: 标记循环起始，内部需维护循环计数或条件。
    * `loop_end`: 决定跳转回 `loop_begin` 还是流向下一个节点。

### 4. 技术要求
* **python环境**: 使用名为`qtt`的conda虚拟环境进行开发和测试.
* **并发模型**: 使用 `asyncio` 实现异步调度。
* **解耦**: 使用信号机制（如 `blinker` 库或简单的回调列表）处理 `evt_wf_xxx` 和 `evt_node_xxx` 事件。
* **健壮性**: 包含完整的 `try-except` 捕获，确保任何节点出错时，工作流能正确进入 `error` 状态并记录日志。
* **日志**: 实现 `dump_log()` 方法，能以表格或格式化 JSON 形式输出执行链条。
* **工作目录**:必须严格在**main\libs\workflow**中进行开发
* **生成**: 目标是生成一个`python库`,包含基本的库文件, 以及测试文件.
