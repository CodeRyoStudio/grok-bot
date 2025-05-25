import os
import discord
from discord import app_commands
import aiohttp
import json
import logging
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv

# 設置日誌
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv()

# Discord Bot 配置
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# xAI API 配置
XAI_API_URL = "https://api.x.ai/v1/chat/completions"
XAI_API_KEY = os.getenv("XAI_API_KEY")

# Jinja2 環境
env = Environment(loader=FileSystemLoader("templates"))

# 進度條生成
def generate_progress_bar(percentage, length=10):
    filled = int(length * percentage // 100)
    bar = "█" * filled + "□" * (length - filled)
    return f"[{bar}] {percentage}%"

# 分段訊息
def split_message(content, max_length=1000):
    parts = []
    while len(content) > max_length:
        split_point = content[:max_length].rfind("\n") or max_length
        parts.append(content[:split_point])
        content = content[split_point:].lstrip()
    if content:
        parts.append(content)
    return parts

async def call_xai_api(prompt, model="grok-3-mini", search_params=None, reasoning_effort="high"):
    async with aiohttp.ClientSession() as session:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {XAI_API_KEY}"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        if search_params:
            payload["search_parameters"] = search_params
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        
        logger.debug(f"Sending API request: {json.dumps(payload, indent=2)}")
        try:
            async with session.post(XAI_API_URL, headers=headers, json=payload) as response:
                response_json = await response.json()
                logger.debug(f"API response: {json.dumps(response_json, indent=2)}")
                if response.status == 200 and "choices" in response_json:
                    return response_json
                else:
                    logger.error(f"API request failed: status={response.status}, response={response_json}")
                    return {"error": f"API request failed with status {response.status}: {response_json.get('error', 'Unknown error')}"}
        except Exception as e:
            logger.error(f"API request error: {str(e)}")
            return {"error": str(e)}

async def thinking_function(query, effort, previous_results=None):
    template = env.get_template("thinking.jinja")
    prompt = template.render(query=query, previous_results=previous_results)
    response = await call_xai_api(prompt, reasoning_effort=effort)
    if "error" in response:
        logger.error(f"Thinking function error: {response['error']}")
        return {
            "results": {"intent": "unknown", "new_query": query, "status": "continue"},
            "next_step": "middleware",
            "parameters": {"response": "Error in thinking function"}
        }
    try:
        return json.loads(response["choices"][0]["message"]["content"])
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Thinking function JSON parse error: {str(e)}, response: {response}")
        return {
            "results": {"intent": "unknown", "new_query": query, "status": "continue"},
            "next_step": "middleware",
            "parameters": {"response": "Error parsing response"}
        }

async def search_function(query, sources, max_results):
    search_params = {
        "mode": "on",
        "sources": [
            {"type": "news", "country": "US"},
            {"type": "x", "max_search_results": 10}
        ],
        "return_citations": True
    }
    template = env.get_template("search.jinja")
    prompt = template.render(query=query, sources=sources, max_results=max_results)
    response = await call_xai_api(prompt, search_params=search_params)
    
    if "error" in response:
        logger.error(f"Search function error: {response['error']}")
        return {
            "results": {"summary": "Error retrieving search results", "data": []},
            "citations": [],
            "next_step": "middleware",
            "parameters": {"response": "Error in search function"}
        }
    
    try:
        content = response["choices"][0]["message"]["content"]
        logger.debug(f"Search function response content: {content}")
        return json.loads(content)
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Search function parse error: {str(e)}, response: {response}")
        return {
            "results": {"summary": "Error retrieving search results", "data": []},
            "citations": [],
            "next_step": "middleware",
            "parameters": {"response": "Error parsing search results"}
        }

async def summary_function(query, history, insufficient_data=False,language="en"):
    template = env.get_template("summary.jinja")
    prompt = template.render(query=query, history=history, insufficient_data=insufficient_data,language=language)
    response = await call_xai_api(prompt)
    if "error" in response:
        logger.error(f"Summary function error: {response['error']}")
        return {"response": "Error generating summary", "citations": []}
    
    try:
        content = response["choices"][0]["message"]["content"]
        logger.debug(f"Summary function response content: {content}")
        return {"response": content, "citations": []}  # Citations included in Markdown
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Summary function parse error: {str(e)}, response: {response}")
        return {"response": "Error generating summary", "citations": []}

async def middleware_layer(user_query, previous_response=None, search_history=None, search_attempts=0):
    if search_history is None:
        search_history = {"user_query": user_query, "iterations": []}
    
    max_search_attempts = 3
    insufficient_data = False
    
    template = env.get_template("middleware.jinja")
    prompt = template.render(
        current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        user_query=user_query,
        previous_response=previous_response,
        search_history=search_history
    )
    response = await call_xai_api(prompt)
    if "error" in response:
        logger.error(f"Middleware error: {response['error']}")
        return {
            "function_name": "thinking_function",
            "parameters": {"query": user_query, "effort": "high"},
            "reasoning": "Error in middleware, defaulting to thinking"
        }, search_history, search_attempts, insufficient_data
    
    try:
        decision = json.loads(response["choices"][0]["message"]["content"])
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Middleware JSON parse error: {str(e)}, response: {response}")
        decision = {
            "function_name": "thinking_function",
            "parameters": {"query": user_query, "effort": "high"},
            "reasoning": "Error parsing middleware response, defaulting to thinking"
        }
    
    if decision["function_name"] == "search_function":
        search_attempts += 1
    elif decision["function_name"] == "summary_function":
        news_count = sum(1 for iteration in search_history["iterations"]
                         if iteration["function"] == "search_function" and
                         "news" in iteration["parameters"]["sources"])
        x_count = sum(len(iteration["results"].get("data", [])) for iteration in search_history["iterations"]
                      if iteration["function"] == "search_function" and
                      "x" in iteration["parameters"]["sources"])
        logger.debug(f"News count: {news_count}, X count: {x_count}, Search attempts: {search_attempts}")
        if news_count < 3 or x_count < 10:
            if search_attempts >= max_search_attempts:
                insufficient_data = True
                decision["function_name"] = "summary_function"
                decision["parameters"] = {
                    "query": user_query,
                    "history": search_history
                }
                decision["reasoning"] = "Reached max search attempts with insufficient results. Forcing summary."
            else:
                decision["function_name"] = "search_function"
                decision["parameters"] = {
                    "query": user_query,
                    "sources": ["news", "x"],
                    "max_results": 20
                }
                decision["reasoning"] = "Insufficient news sources or X posts. Performing additional search."
    
    return decision, search_history, search_attempts, insufficient_data

@tree.command(name="ask", description="Ask a question with search and reasoning")
@app_commands.describe(query="Your question or request")
async def ask(interaction: discord.Interaction, query: str,language: str = "en"):
    await interaction.response.defer(ephemeral=True)
    
    search_history = None
    previous_response = None
    user_query = query
    temp_messages = []
    max_iterations = 5
    current_iteration = 0
    search_attempts = 0
    insufficient_data = False
    
    # 發送初始進度訊息（私有）
    try:
        progress_msg = await interaction.followup.send(
            content=f"{generate_progress_bar(0)} 開始處理...",
            ephemeral=True
        )
    except discord.errors.HTTPException as e:
        logger.error(f"Initial progress message failed: {str(e)}")
        progress_msg = await interaction.channel.send(
            content=f"{generate_progress_bar(0)} 開始處理（因交互延遲，使用頻道訊息）..."
        )
    temp_messages.append(progress_msg)
    
    while True:
        current_iteration += 1
        progress_percentage = min((current_iteration / max_iterations) * 100, 100)
        
        decision, search_history, search_attempts, insufficient_data = await middleware_layer(
            user_query, previous_response, search_history, search_attempts
        )
        function_name = decision["function_name"]
        parameters = decision["parameters"]
        
        # 準備指令訊息並分段，限制參數長度
        command_content = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 調用 {function_name}:\n" + \
                          "\n".join([f"- {key}: {str(value)[:50]}" for key, value in parameters.items()])
        logger.debug(f"Command content length: {len(command_content)}")
        command_parts = split_message(command_content, max_length=1000)
        
        # 發送指令訊息（私有，分段）
        for i, part in enumerate(command_parts):
            logger.debug(f"Command message part {i+1} length: {len(part)}")
            try:
                command_msg = await interaction.followup.send(
                    content=f"{'Part ' + str(i+1) + ': ' if len(command_parts) > 1 else ''}{part}",
                    ephemeral=True
                )
            except discord.errors.HTTPException as e:
                logger.error(f"Command message failed: {str(e)}")
                command_msg = await interaction.channel.send(
                    content=f"{'Part ' + str(i+1) + ': ' if len(command_parts) > 1 else ''}{part}（因交互延遲，使用頻道訊息）"
                )
            temp_messages.append(command_msg)
        
        # 更新進度訊息
        progress_content = f"{generate_progress_bar(progress_percentage)} 正在處理 {function_name}"
        if function_name == "search_function":
            progress_content += f"（搜尋第 {search_attempts}/3 次）..."
        elif insufficient_data:
            progress_content = f"{generate_progress_bar(100)} 搜尋結果不足，正在生成總結..."
        try:
            await progress_msg.edit(content=progress_content)
        except:
            try:
                progress_msg = await interaction.followup.send(content=progress_content, ephemeral=True)
            except discord.errors.HTTPException as e:
                logger.error(f"Progress update failed: {str(e)}")
                progress_msg = await interaction.channel.send(content=progress_content)
            temp_messages.append(progress_msg)
        
        if function_name == "thinking_function":
            result = await thinking_function(
                parameters["query"],
                parameters["effort"],
                previous_results=previous_response
            )
            search_history["iterations"].append({
                "function": function_name,
                "parameters": parameters,
                "results": result["results"],
                "reasoning": result.get("reasoning", "")
            })
            previous_response = result["parameters"]["response"]
        
        elif function_name == "search_function":
            result = await search_function(
                parameters["query"],
                parameters["sources"],
                parameters["max_results"]
            )
            search_history["iterations"].append({
                "function": function_name,
                "parameters": parameters,
                "results": result["results"],
                "citations": result["citations"],
                "reasoning": result.get("reasoning", "")
            })
            previous_response = result["parameters"]["response"]
        
        elif function_name == "summary_function":
            result = await summary_function(
                parameters["query"],
                parameters["history"],
                insufficient_data=insufficient_data,
                language=language
            )
            response_text = result["response"]
            if insufficient_data:
                response_text = ("很抱歉，對於您的問題，我們找到的資訊非常有限，可能無法完全回答問題。\n"
                                f"以下是基於現有資料的總結：\n{response_text}")
            
            # 分段最終回答
            embed_parts = split_message(response_text, max_length=1000)
            embeds = []
            for i, part in enumerate(embed_parts):
                embed = discord.Embed(
                    title="回答" if i == 0 else f"回答（第 {i+1} 部分）",
                    description=part,
                    color=discord.Color.red() if insufficient_data else discord.Color.blue()
                )
                embeds.append(embed)
            
            # 發送最終回答
            try:
                for embed in embeds:
                    await interaction.followup.send(embed=embed, ephemeral=True)
            except discord.errors.HTTPException as e:
                logger.error(f"Final followup send failed: {str(e)}")
                await interaction.channel.send(
                    content="由於處理時間過長，回答已公開發送到頻道。",
                    embeds=embeds
                )
            
            # 刪除臨時訊息
            for msg in temp_messages:
                try:
                    await msg.delete()
                except:
                    pass
            break

@client.event
async def on_ready():
    print(f"已登入為 {client.user}")
    await tree.sync()

client.run(os.getenv("DISCORD_BOT_TOKEN"))