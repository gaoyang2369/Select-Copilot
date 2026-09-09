# 回复速度优化

本次优化不改变快捷键、选区捕获和退出方式。翻译、解释及 Chat 支持边生成边显示；DeepSeek 官方 V4 模型默认显式关闭思考，复杂问题可通过配置重新开启；成功的翻译保存在有上限的内存缓存中。

## 文件及作用

| 文件 | 作用 |
| --- | --- |
| `services/completion.py` | 翻译和 LLM 共用的请求函数；解析 SSE、识别不完整响应、处理 JSON 回退、记录请求耗时、仅对匹配的 DeepSeek 主机及模型发送 thinking 参数。 |
| `services/llm.py` | 保留 ask/chat 接口，增加可选 on_delta 回调，读取流式与思考配置。 |
| `services/translator.py` | 共用请求层；增加按原文和目标语言区分的 LRU 内存缓存。每个 Translator 实例最多 128 项，单项原文、目标语言及结果合计不超过 16384 字符。模型和接口配置固定在实例内。 |
| `services/chat.py` | 把增量正文转给界面；完整成功后才记入 assistant 历史；失败、取消时回滚本轮用户消息。 |
| `ui/workers.py` | 增加 progress 信号，首段立即发送，后续约 30ms 合并刷新；保留取消及完整结果信号；记录 UI 首次显示耗时。 |
| `ui/toolbar.py` | 显示流式内容，以请求对象区分当前结果；忽略旧选区和被其他动作替换的请求，避免结果混杂或重新弹出。 |
| `ui/translation_popup.py` | 流式更新只追加纯文本，不逐段重新定位、弹出窗口。 |
| `ui/chat_window.py` | Chat 流式追加正文；完成时校正本轮答案，避免重复显示；失败时明确标记本轮失败。 |
| `tests/test_completion.py` | 分片 UTF-8/SSE、心跳、思考与正文分离、首段早于结束、DeepSeek 参数隔离、非流式兼容、失败不缓存、缓存上限、取消与历史回滚。 |
| `tests/test_streaming_ui.py` | 使用本地模拟 HTTP 流测试真实 Qt 工具栏及 Chat，覆盖提前显示、旧结果隔离、隐藏及关闭取消。 |
| `tests/test_workers.py` | 新增服务端暂时无数据时，已缓存小片段仍按时刷新到界面的测试。 |
| `tests/test_toolbar.py`、`tests/test_chat.py` | 更新测试服务的回调参数，保留此前全部行为回归测试。 |
| `.env.example` | 提供不含真实密钥的配置示例。 |
| `docs/Performance.md` | 本说明、运行方式及验收方法。 |

## 调用链

```text
点击译/解释/Send
  -> AsyncTextWorker
  -> Translator / LLMService / ChatSession
  -> complete -> HTTP SSE
  -> on_delta（仅正文）
  -> worker.progress（Qt 跨线程信号）
  -> 工具栏/Chat 追加文字
  -> 接口完整结束 -> completed -> 校正完整结果 / 记录聊天历史

再次翻译相同原文及目标语言 -> 内存缓存 -> 显示结果，不发起网络请求
```

`stream=true` 减少看到正文前的等待，不保证模型完成全部生成的时间缩短。DeepSeek 默认开启 high 思考，本次显式关闭以减少日常翻译和快速问答中不必要的推理；复杂问题的质量可能因此改变，可重新开启。参数依据 [DeepSeek 官方文档](https://api-docs.deepseek.com/guides/thinking_mode/)。

## 运行与配置

不需要新增依赖，也没有改写已有 `.env` 或密钥。重启即可使用新默认值：

```powershell
conda activate copilot
python app.py
```

以下项目可按需添加到现有 `.env`，修改后重启：

```dotenv
LLM_STREAM=true
DEEPSEEK_TRANSLATION_THINKING=disabled
DEEPSEEK_THINKING=disabled
```

- `DEEPSEEK_TRANSLATION_THINKING` 只控制翻译；`DEEPSEEK_THINKING` 控制解释和 Chat。
- 两者允许 `disabled`、`enabled`、`default`；`default` 表示不发送 thinking 参数，使用服务商默认行为。
- thinking 参数仅发送到主机名恰为 `api.deepseek.com` 且模型名以 `deepseek-v4-` 开头的接口，其他服务商保持通用请求格式。
- 接口不支持 SSE 时设 `LLM_STREAM=false`。如果接口直接返回正常的 JSON，代码也能读取。没有失败后自动重发，以免重复计费或把两次答案混在一起。
- 无 on_delta 回调的直接 Python 调用仍按非流式方式返回完整字符串。

## 日志解读

终端在现有 INFO 日志级别输出：

| 字段 | 含义 |
| --- | --- |
| `API <id> ... started` | 一个请求开始，相同 id 的记录属于同一次请求。 |
| `headers_s` | 从请求函数开始到收到响应头，包含本地客户端初始化、连接和服务端等待等。 |
| `first_reasoning_s` | 流式接口第一次返回非空思考内容；不开启思考通常没有此项。 |
| `first_text_s` | 第一次收到非空正文，非流式模式下接近完整响应时间。 |
| `total_s`、`status` | 请求结束耗时及 ok/failed/cancelled 状态。 |
| `UI first_visible_s` | 从点击后创建 worker 到 Qt 插入首段正文的耗时，包含后台启动、请求和界面排队；这不是屏幕实际完成绘制的测量。 |
| `Translation cache hit` | 翻译命中内存缓存，不发送 API 请求。 |

日志不记录密钥、原文、回答或思考内容。headers_s 不能单独拆出网络与服务端排队时间；先比较 first_text_s 和 total_s，再决定是否需要更细的网络测量。并发多个窗口时 API 请求用 id 区分，UI 首显日志为各窗口独立事件。

## 测试

```powershell
python -m unittest discover -s tests -v
python -m compileall -q app.py core ui services tests
```

新增测试使用 MockTransport 和受控延迟流，不连接真实 API、不消耗账户额度。它们验证首段正文在响应完成前可见，不能作为 DeepSeek 实际提速倍数的测量。

手动验收：

1. 选中一段英文并点译，正文应逐段出现，终端有 first_text_s、total_s 和 UI 首显日志。
2. 对完全相同的文本再点译，应出现 cache hit，且没有新的 API started 日志。
3. 分别测试解释和 Chat；Chat 流式结束后答案不重复，多轮内容正常保留。
4. 正在翻译时点解释，旧翻译不应覆盖解释；重新选择相同或不同文本后，旧请求不应重新弹出结果窗。
5. 结果生成中按 Esc 隐藏，后续片段不应重新打开窗口；Chat 生成中关闭窗口，程序不应卡住或崩溃。
6. 如需比较思考开关，使用同样的几条测试问题，分别设置 enabled/disabled 并重启，比较首段正文及总耗时，避免把一次服务端波动当作稳定结论。重启也会清空翻译缓存。

## 已知限制及下一步

- 本次没有实测真实 DeepSeek API，因此不声称具体提速比例。网络、服务端负载和回答长度仍影响延迟。
- 当前每个请求仍在独立 QThread/asyncio loop 中创建客户端，没有跨请求复用连接。不能直接在这些循环之间共享一个全局 AsyncClient；若日志证明连接开销明显，再引入一个长期运行的网络事件循环。参见 [HTTPX 文档](https://www.python-httpx.org/async/)。
- 隐藏工具栏会忽略后续内容，但原请求继续到完成或退出取消，以便缓存成功翻译；关闭 Chat 会立即请求取消。结果窗内存缓存随进程退出清空。
- HTTPX 45 秒设置是连接/读写等阶段的超时；持续返回心跳的接口可能运行更久，退出时可取消网络任务。
- 扫描 PDF、剪贴板格式保存、TTS 退出等待等既有限制与本次无关，仍见之前的修复说明。
- 最自然的下一步是 Phase 7：托盘与设置界面，把模型、流式和思考开关放到可见设置中，再用真实使用日志决定是否调整连接复用。

建议阅读 `complete`（从网络分片到正文与耗时）、`AsyncTextWorker._on_delta`（跨线程和合并刷新）、`Translator.translate`（缓存命中、成功写入及失败不缓存）三个函数。
