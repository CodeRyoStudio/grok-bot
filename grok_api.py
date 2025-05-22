import os
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv()

class GrokAPI:
    def __init__(self):
        self.url = "https://api.x.ai/v1/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('XAI_API_KEY')}"
        }

    async def call_api(self, messages, search_parameters=None):
        """
        非同步調用 Grok API，支援聊天完成和 Live Search。

        參數:
            messages (list): 對話訊息列表，包含 role (system/user/assistant) 和 content。
            search_parameters (dict, optional): Live Search 參數，支援 mode、sources、from_date、
                                              to_date、max_search_results、return_citations 等。

        返回:
            dict: API 的 JSON 回應，包含聊天完成和可能的搜尋結果（例如 citations）。
            若失敗，返回錯誤資訊。
        """
        payload = {
            "messages": messages,
            "model": "grok-3-mini"  
        }
        if search_parameters:
            valid_parameters = {
                "mode": search_parameters.get("mode", "auto"),
                "sources": search_parameters.get("sources", [{"type": "web"}, {"type": "x"}]),
                "from_date": search_parameters.get("from_date"),
                "to_date": search_parameters.get("to_date"),
                "max_search_results": search_parameters.get("max_search_results", 20),
                "return_citations": search_parameters.get("return_citations", False)
            }
            payload["search_parameters"] = {k: v for k, v in valid_parameters.items() if v is not None}

        async with aiohttp.ClientSession() as session:
            for attempt in range(3):
                try:
                    async with session.post(self.url, headers=self.headers, json=payload) as response:
                        response.raise_for_status()
                        data = await response.json()
                        print("Grok API Response:", json.dumps(data, indent=2))
                        return data
                except aiohttp.ClientError as e:
                    if attempt == 2:
                        error_msg = f"API request failed after 3 attempts: {str(e)}"
                        print(error_msg)
                        return {"error": error_msg}
                    continue