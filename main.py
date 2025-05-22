import os
import discord
from discord.ext import commands
from bot import Bot
from dotenv import load_dotenv
import asyncio

# 加載環境變數
load_dotenv()

# 初始化 Discord 客戶端
intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix='/', intents=intents)

# 創建機器人實例
bot = Bot(client)

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    try:
        synced = await client.tree.sync()
        print(f'Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'Failed to sync commands: {e}')

# 啟動機器人
async def main():
    await client.start(os.getenv('DISCORD_BOT_TOKEN'))

if __name__ == '__main__':
    asyncio.run(main())