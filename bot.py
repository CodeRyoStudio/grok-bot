import discord
from discord import app_commands
from context_manager import ContextManager
from grok_api import GrokAPI
from functions import Functions
from jinja2 import Environment, FileSystemLoader
import os
import json
import asyncio
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Bot:
    def __init__(self, client):
        self.client = client
        self.context_manager = ContextManager()
        self.grok_api = GrokAPI()
        self.functions = Functions(self.grok_api, self.context_manager)
        self.env = Environment(loader=FileSystemLoader('templates'))
        self.max_function_calls = int(os.getenv('MAX_FUNCTION_CALLS', 20))
        self.register_commands()

    def register_commands(self):
        @self.client.tree.command(name="ask", description="Ask a general question")
        @app_commands.describe(question="Your question")
        async def ask(interaction: discord.Interaction, question: str):
            await self.process_command(interaction, question)

        @self.client.tree.command(name="search", description="Perform a search query")
        @app_commands.describe(query="Search query", source="Optional source (web, x, news)")
        async def search(interaction: discord.Interaction, query: str, source: str = None):
            await self.process_command(interaction, query, source=source)

        @self.client.tree.command(name="time", description="Get current time")
        @app_commands.describe(timezone="Timezone (e.g., Asia/Taipei)")
        async def time(interaction: discord.Interaction, timezone: str = "UTC"):
            await self.process_command(interaction, f"Get current time in {timezone}")

        @self.client.tree.command(name="view_reasoning", description="View latest reasoning or summary")
        async def view_reasoning(interaction: discord.Interaction):
            await self.view_reasoning_command(interaction)

        @self.client.tree.command(name="clear_context", description="Clear channel context")
        async def clear_context(interaction: discord.Interaction):
            await self.clear_context_command(interaction)

    async def process_command(self, interaction: discord.Interaction, user_input: str, source: str = None):
        await interaction.response.defer()
        channel_id = str(interaction.channel_id)
        context = await self.context_manager.get_context(channel_id)
        
        # 初始化上下文
        if not context.get('conversation_history'):
            context['conversation_history'] = []
            context['reasoning_history'] = []
            context['search_results'] = []
            context['call_count'] = 0
            context['user_language'] = 'en'
            context['last_summary'] = ''
            await self.context_manager.save_context(channel_id, context)

        # 檢測語言
        language_response = await self.grok_api.call_api([
            {"role": "system", "content": "Detect the language of the following text and return only the language code (e.g., 'en', 'zh-TW')."},
            {"role": "user", "content": user_input}
        ])
        context['user_language'] = language_response.get('choices', [{}])[0].get('message', {}).get('content', 'en')
        
        # 翻譯輸入
        translated_input = user_input
        if context['user_language'] != 'en':
            translated_input = await self.functions.translate_text(user_input, 'en')
        
        # 初始化推理過程訊息
        thinking_messages = []

        async def send_thinking_message(content, index):
            try:
                # 確保內容不為空
                if not content.strip():
                    return
                # 分段處理，確保每段 ≤2000 字
                max_length = 2000
                parts = [content[i:i+max_length-100] for i in range(0, len(content), max_length-100)]  # 留100字餘量
                for i, part in enumerate(parts, 1):
                    msg_content = f"思考過程 #{index}.{i}:\n{part}"
                    if len(msg_content) > max_length:
                        logger.warning(f"Message part #{index}.{i} still exceeds {max_length} characters")
                        continue
                    try:
                        msg = await interaction.followup.send(msg_content, ephemeral=False)
                        thinking_messages.append(msg)
                    except discord.errors.HTTPException as e:
                        logger.error(f"Failed to send thinking message #{index}.{i}: {str(e)}")
                        # 繼續執行，不中斷邏輯
            except Exception as e:
                logger.error(f"Error in send_thinking_message: {str(e)}")
                # 不拋出異常，確保邏輯繼續

        # 主處理循環
        current_input = user_input
        iteration = 0
        while context['call_count'] < self.max_function_calls:
            iteration += 1
            # 渲染提示詞
            template = self.env.get_template('prompt.jinja')
            prompt = template.render(
                user_input=current_input,
                user_language=context['user_language'],
                user_input_translated=translated_input,
                current_date=datetime.now().strftime('%Y-%m-%d'),
                call_count=context['call_count'],
                max_call_count=self.max_function_calls,
                reasoning_history=context['reasoning_history'][-10:],
                search_results=context['search_results'][-20:],
                conversation_history=context['conversation_history'][-50:],
                last_summary=context['last_summary']
            )

            # 調用Grok API
            response = await self.grok_api.call_api([
                {"role": "system", "content": prompt},
                {"role": "user", "content": translated_input}
            ])

            # 解析回應
            try:
                response_content = response['choices'][0]['message']['content']
                # 限制回應長度，避免過長
                if len(response_content) > 1000:
                    response_content = response_content[:1000] + "... [truncated]"
                try:
                    # 直接解析 JSON（json.loads 很快，無需執行器）
                    action = json.loads(response_content)
                    if isinstance(action, dict) and 'function' in action:
                        # 記錄推理過程
                        reasoning = f"調用函數: {action['function']} with parameters {action['parameters']}"
                        context['reasoning_history'].append(f"思考過程 #{iteration}: {reasoning}")
                        await send_thinking_message(reasoning, iteration)

                        # 執行函數
                        result = await self.functions.execute_function(action['function'], action['parameters'])
                        context['call_count'] += 1

                        if action['function'] == 'finalize_response':
                            # 翻譯最終回應
                            final_content = result
                            if context['user_language'] != 'en':
                                final_content = await self.functions.translate_text(result, context['user_language'])
                            # 刪除思考過程訊息
                            for msg in thinking_messages:
                                try:
                                    await msg.delete()
                                except discord.errors.HTTPException:
                                    pass
                            # 分段發送最終回應
                            max_length = 2000
                            parts = [final_content[i:i+max_length-100] for i in range(0, len(final_content), max_length-100)]
                            for i, part in enumerate(parts, 1):
                                await interaction.followup.send(part)
                            context['last_summary'] = final_content
                            break

                        # 將函數結果加入上下文
                        if action['function'] == 'call_grok_api' and 'search_results' in result:
                            context['search_results'].extend(result['search_results'])
                        context['conversation_history'].append({"role": "assistant", "content": str(result)})
                    else:
                        # 記錄自然語言推理
                        context['reasoning_history'].append(f"思考過程 #{iteration}: {response_content}")
                        await send_thinking_message(response_content, iteration)
                        context['conversation_history'].append({"role": "assistant", "content": response_content})
                except json.JSONDecodeError:
                    # 記錄自然語言推理
                    context['reasoning_history'].append(f"思考過程 #{iteration}: {response_content}")
                    await send_thinking_message(response_content, iteration)
                    context['conversation_history'].append({"role": "assistant", "content": response_content})
            except Exception as e:
                error_msg = f"錯誤: {str(e)}"
                context['reasoning_history'].append(f"思考過程 #{iteration}: {error_msg}")
                await send_thinking_message(error_msg, iteration)
                continue  # 繼續迴圈，不中斷

            await self.context_manager.save_context(channel_id, context)

        # 強制總結（若超限）
        if context['call_count'] >= self.max_function_calls:
            reasoning = "已達最大調用次數，強制總結。"
            context['reasoning_history'].append(f"思考過程 #{iteration}: {reasoning}")
            await send_thinking_message(reasoning, iteration)
            summary = await self.functions.summarize_context(channel_id)
            final_content = summary
            if context['user_language'] != 'en':
                final_content = await self.functions.translate_text(summary, context['user_language'])
            for msg in thinking_messages:
                try:
                    await msg.delete()
                except discord.errors.HTTPException:
                    pass
            # 分段發送最終回應
            max_length = 2000
            parts = [final_content[i:i+max_length-100] for i in range(0, len(final_content), max_length-100)]
            for i, part in enumerate(parts, 1):
                await interaction.followup.send(part)
            context['last_summary'] = final_content

        await self.context_manager.save_context(channel_id, context)

    async def view_reasoning_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        channel_id = str(interaction.channel_id)
        context = await self.context_manager.get_context(channel_id)
        reasoning = context.get('reasoning_history', [])
        summary = context.get('last_summary', '無可用總結。')

        if reasoning:
            content = "\n".join(reasoning)
            max_length = 2000
            parts = [content[i:i+max_length-100] for i in range(0, len(content), max_length-100)]
            for i, part in enumerate(parts, 1):
                await interaction.followup.send(f"最新思考過程（分段 {i}/{len(parts)}）:\n{part}")
        else:
            await interaction.followup.send(f"無最新思考過程。最後總結:\n{summary}")

    async def clear_context_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        channel_id = str(interaction.channel_id)
        await self.context_manager.clear_context(channel_id)
        await interaction.followup.send("頻道上下文已清除。")