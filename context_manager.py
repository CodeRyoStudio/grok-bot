class ContextManager:
    def __init__(self):
        # 初始化上下文字典，按頻道ID儲存
        self.contexts = {}

    def get_context(self, channel_id):
        # 獲取指定頻道的上下文，若不存在則創建新的
        if channel_id not in self.contexts:
            self.contexts[channel_id] = {
                'conversation_history': [],  # 對話歷史（系統提示、用戶輸入、AI回應）
                'reasoning_history': [],    # 推理過程（COT思維鏈）
                'search_results': [],       # 搜尋結果（含可信度分數）
                'call_count': 0,            # 函數調用次數
                'user_language': 'en',      # 用戶語言（預設英文）
                'last_summary': ''          # 上次總結
            }
        return self.contexts[channel_id]

    def save_context(self, channel_id, context):
        # 保存上下文到指定頻道
        self.contexts[channel_id] = context

    def clear_context(self, channel_id):
        # 清除指定頻道的上下文
        if channel_id in self.contexts:
            del self.contexts[channel_id]