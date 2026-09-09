实现 Phase 5：AI Quick Ask。

现在点击“解释”按钮：

把当前 selected_text 发送给 LLM。

默认 Prompt：

“请解释下面内容。目标用户是计算机专业硕士。
优先用直白的话说明：
1. 它是什么
2. 在当前语境下是什么意思
3. 为什么重要
4. 必要时给一个简单例子
不要无意义扩展。

内容：
{selection}
”

API 使用现有 LLMService。

请不要把 prompt 写死在 UI 代码中。

新增：

services/llm.py

class LLMService

以及独立 Prompt 定义。

结果展示可以复用 translation popup，
也可以提取通用 ResultPopup。

如果代码开始重复，再做小范围重构。

不要提前构建 Agent。
这只是一次普通 LLM 请求。