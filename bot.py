import os
import sys
import json
import re
import asyncio
import logging
import datetime

import discord
from discord.ext import commands
from discord import app_commands

# ========= 環境変数 =========
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # 必須（Railway Variables で設定）
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# ギルド即時反映用：複数サーバならカンマ区切りで指定可。未設定なら例のIDを既定値に。
GUILD_IDS = [int(x.strip()) for x in os.getenv("GUILD_IDS", "1398607685158440991").split(",") if x.strip().isdigit()]
PRIMARY_GUILD_ID = GUILD_IDS[0] if GUILD_IDS else 1398607685158440991

# ========= ログ =========
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="(%(asctime)s) [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# ========= 簡易KV(JSON) =========
DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

# ========= Bot 本体 =========
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ========= ユーティリティ =========
def build_status_msg(target_id: int, male_next: int, female_next: int, male_url: str, female_url: str) -> str:
    """状態を表示するメッセージを組み立て"""
    return (
        "対象チャンネル: <#{}>\n"
        "次の男性別名: 男{} / 次の女性別名: 女{}\n"
        "男性アイコン: {}\n"
        "女性アイコン: {}"
    ).format(target_id, male_next, female_next, male_url, female_url)


def build_reply_msg(reply: str, target: str) -> str:
    """返信メッセージを整形"""
    return "> **返信:** {}\n> **対象:** {}".format(reply, target)


# ========= イベント =========
@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync(guild=discord.Object(id=PRIMARY_GUILD_ID))
        log.info(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        log.exception("Failed to sync commands")


# ========= コマンド =========
@tree.command(name="status", description="現在の状態を表示します", guild=discord.Object(id=PRIMARY_GUILD_ID))
async def status_cmd(interaction: discord.Interaction):
    male_next = data.get("male_next", 1)
    female_next = data.get("female_next", 1)
    male_url = data.get("male_url", "未設定")
    female_url = data.get("female_url", "未設定")
    target_id = data.get("target_channel", 0)

    msg = build_status_msg(target_id, male_next, female_next, male_url, female_url)
    await interaction.response.send_message(msg, ephemeral=True)


@tree.command(name="reply", description="返信メッセージを表示します", guild=discord.Object(id=PRIMARY_GUILD_ID))
@app_commands.describe(reply="返信内容", target="対象ユーザーやメッセージ")
async def reply_cmd(interaction: discord.Interaction, reply: str, target: str):
    msg = build_reply_msg(reply, target)
    await interaction.response.send_message(msg)


# ========= 起動 =========
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        log.error("DISCORD_TOKEN が設定されていません")
        sys.exit(1)
    bot.run(DISCORD_TOKEN)
