from credibility import CredibilityScorer
from datetime import datetime, timedelta
import json
import asyncio

class Functions:
    def __init__(self, grok_api, context_manager):
        self.grok_api = grok_api
        self.context_manager = context_manager
        self.credibility_scorer = CredibilityScorer()
        self.loop = asyncio.get_event_loop()

    async def get_current_time(self, timezone: str) -> str:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(timezone)).strftime('%Y-%m-%d %H:%M:%S')

    async def call_grok_api(self, messages: list, search_parameters: dict = None) -> dict:
        response = await self.grok_api.call_api(messages, search_parameters)
        if search_parameters and 'choices' in response and response['choices']:
            citations = response.get('citations', [])
            search_results = [
                {
                    "source": "unknown",
                    "content": response['choices'][0]['message']['content'][:1000],  # 限制內容長度
                    "url": citation,
                    "score": 0
                } for citation in citations
            ]
            for result in search_results:
                result['score'] = self.credibility_scorer.score(result, search_results)
            response['search_results'] = search_results
        return response

    async def translate_text(self, text: str, target_language: str) -> str:
        response = await self.grok_api.call_api([
            {"role": "system", "content": f"Translate the following text to {target_language}."},
            {"role": "user", "content": text}
        ])
        return response['choices'][0]['message']['content']

    async def finalize_response(self, content: str, citations: list = None) -> str:
        content = content[:1000]  # 限制長度
        if citations:
            citation_text = "\n來源:\n" + "\n".join([f"[{url}]({url})" for url in citations])
            return f"{content}{citation_text}"
        return content

    async def summarize_context(self, channel_id: str) -> str:
        context = await self.context_manager.get_context(channel_id)
        search_results = context.get('search_results', [])
        reliable_results = [r for r in search_results if r['score'] >= 60]
        
        if len(search_results) < 3 or len(reliable_results) < 3:
            scores = [r['score'] for r in search_results]
            content = (f"無法提供可靠資訊。僅有{len(search_results)}個來源（分數: {', '.join(map(str, scores))}），"
                       f"數量不足三個或可靠來源（分數≥60）不足三個。")
            if search_results:
                content += "\n現有資料:\n" + "\n".join([f"- {r['content']} (分數: {r['score']})" for r in search_results])
            else:
                content += "\n無可用資料。"
        else:
            content = "根據以下可靠來源:\n" + "\n".join([f"- {r['content']} (分數: {r['score']})" for r in reliable_results])
        
        return content[:1000]  # 限制長度

    async def execute_function(self, function_name: str, parameters: dict):
        if function_name == 'get_current_time':
            return await self.get_current_time(parameters.get('timezone', 'UTC'))
        elif function_name == 'call_grok_api':
            return await self.call_grok_api(parameters.get('messages', []), parameters.get('search_parameters'))
        elif function_name == 'translate_text':
            return await self.translate_text(parameters.get('text', ''), parameters.get('target_language', 'en'))
        elif function_name == 'finalize_response':
            return await self.finalize_response(parameters.get('content', ''), parameters.get('citations', []))
        else:
            raise ValueError(f"Unknown function: {function_name}")