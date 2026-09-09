实现 Phase 6：Chat。

点击 Chat 后：

打开一个独立的小型 ChatWindow。

顶部显示当前 Selection：

Quoted context:
"..."

然后提供：

- AI 消息区域
- 用户输入框
- Send
- 多轮 conversation

第一条 system/context message 应包含：

用户当前选中的内容。

例如：

The user selected the following content:

<selection>
...
</selection>

Please answer questions primarily around this context.

之后用户可以输入：

“这里为什么要用 async？”
“和 create_task 有什么区别？”

继续多轮聊天。

聊天状态只需要保存在当前窗口内存中。

关闭窗口即可丢弃。

暂时不要：

SQLite
聊天历史
Agent
Tool calling
RAG

实现清晰的：

ChatSession

例如：

class ChatSession:
    messages: list[dict]

    async def send(self, user_message: str) -> str

确保 LLM 请求不阻塞 UI。