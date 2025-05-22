import asyncio

class ContextManager:
    def __init__(self):
        # 初始化上下文字典，按頻道ID儲存
        self.contexts = {}
        # 使用異步鎖確保並行訪問安全
        self.lock = asyncio.Lock()

    async def get_context(self, channel_id):
        """
        獲取指定頻道的上下文，若不存在則創建新的。

        參數:
            channel_id (str): Discord 頻道ID。

        返回:
            dict: 頻道上下文，包含對話歷史、推理歷史、搜尋結果等。
        """
        async with self.lock:
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

    async def save_context(self, channel_id, context):
        """
        保存上下文到指定頻道。

        參數:
            channel_id (str): Discord 頻道ID。
            context (dict): 要保存的上下文資料。
        """
        async with self.lock:
            self.contexts[channel_id] = context

    async def clear_context(self, channel_id):
        """
        清除指定頻道的上下文。

        參數:
            channel_id (str): Discord 頻道ID。
        """
        async with self.lock:
            if channel_id in self.contexts:
                del self.contexts[channel_id]