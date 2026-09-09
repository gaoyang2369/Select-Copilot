现在实现 Phase 8：

鼠标划词完成后自动显示 FloatingToolbar。

当前用户必须：

选中文字
→ Ctrl+Alt+Space

希望升级为：

鼠标左键拖动选择文字
→ 松开
→ 如果确实存在 selected_text
→ 自动显示 toolbar

要求：

1. 监听 Windows 全局鼠标事件
2. 只关心：
   LButtonDown
   MouseMove
   LButtonUp

3. 只有发生明显拖动以后才尝试读取 selection
   避免普通 click 触发

4. 鼠标释放后等待一个非常短的时间，
   再读取 selected_text

5. 如果没有文字：
   什么都不做

6. 如果有文字：
   在鼠标附近显示 toolbar

特别注意不要影响正常鼠标行为。

Hook 回调绝对不能做耗时操作。

Selection 读取和 GUI 更新应异步/延后处理。

保留原 Ctrl+Alt+Space 快捷键作为 fallback。

需要说明 Windows Low Level Mouse Hook 的原理。