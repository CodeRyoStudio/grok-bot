import discord
from discord import app_commands
from context_manager import ContextManager
from grok_api import GrokAPI
from functions import Functions
from jinja2 import Environment, FileSystemLoader
import os
import json
from datetime import datetime
import asyncio

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
        context = self.context_manager.get_context(channel_id)
        
        # 初始化上下文
        if not context.get('conversation_history'):
            context['conversation_history'] = []
            context['reasoning_history'] = []
            context['search_results'] = []
            context['call_count'] = 0
            context['user_language'] = 'en'
            context['last_summary'] = ''

        # 檢測語言
        language_response = await self.grok_api.call_api([
            {"role": "system", "content": "Detect the language of the following text and return only the language code (e.g., 'en', 'zh-TW')."},
            {"role": "user", "content": user_input}
        ])
        context['user_language'] = language_response.get('choices', [{}])[0].get('message', {}).get('content', 'en')
        
        # 翻譯輸入
        translated_input = user_input
        if context['user_language'] != 'en':
            translate_response = await self.functions.translate_text(user_input, 'en')
            translated_input = translate_response

        # 初始化推理過程訊息
        thinking_messages = []

        async def send_thinking_message(content, index):
            # 分段處理，確保每段 ≤2000 字
            max_length = 2000
            if len(content) > max_length:
                parts = [content[i:i+max_length-100] for i in range(0, len(content), max_length-100)]  # 留100字安全餘量
                for i, part in enumerate(parts, 1):
                    msg = await interaction.followup.send(f"思考過程 #{index}.{i}:\n{part}", ephemeral=False)
                    thinking_messages.append(msg)
            else:
                msg = await interaction.followup.send(f"思考過程 #{index}:\n{content}", ephemeral=False)
                thinking_messages.append(msg)

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
                reasoning_history=context['reasoning_history'][-10:],  # 僅保留最後10條
                search_results=context['search_results'][-20:],  # 僅保留最後20條
                conversation_history=context['conversation_history'][-50:],  # 僅保留最後50條
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
                try:
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
                                await msg.delete()
                            await interaction.followup.send(final_content)
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
                await send_thinking_message(f"錯誤: {str(e)}", iteration)
                break

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
                await msg.delete()
            await interaction.followup.send(final_content)
            context['last_summary'] = final_content

        self.context_manager.save_context(channel_id, context)

    async def view_reasoning_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        channel_id = str(interaction.channel_id)
        context = self.context_manager.get_context(channel_id)
        reasoning = context.get('reasoning_history', [])
        summary = context.get('last_summary', '無可用總結。')

        if reasoning:
            content = "\n".join(reasoning)
            max_length = 2000
            if len(content) > max_length:
                parts = [content[i:i+max_length-100] for i in range(0, len(content), max_length-100)]
                for i, part in enumerate(parts, 1):
                    await interaction.followup.send(f"最新思考過程（分段 {i}/{len(parts)}）:\n{part}")
            else:
                await interaction.followup.send(f"最新思考過程:\n{content}")
        else:
            await interaction.followup.send(f"無最新思考過程。最後總結:\n{summary}")

    async def clear_context_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        channel_id = str(interaction.channel_id)
        self.context_manager.clear_context(channel_id)
        await interaction.followup.send("頻道上下文已清除。")