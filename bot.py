# bot.py
# Discord anonymizer bot (role-based only). Participants are inferred by gender roles,
# and messages in the target category are reposted via webhook with fixed avatars and aliases.
# Images are loaded from local ./image folder at startup, uploaded once to Discord to obtain CDN URLs,
# and then reused for webhook avatars.

import os
import json
import logging
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# ===================== CONFIG =====================
TOKEN = os.getenv("DISCORD_TOKEN", "PASTE_YOUR_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))  # 即時同期したいギルドID（任意）

# 固定カテゴリID（このカテゴリ配下が匿名化対象）
TARGET_CATEGORY_ID = 1407976096821018766

# 男女ロールID（ロール判定のみを使用）
MALE_ROLE_ID = 1399390214295785623
FEMALE_ROLE_ID = 1399390384756363264

# 画像アップロード用のチャンネル（任意）。指定しない場合は対象カテゴリ内の最初のテキストチャンネルを使用
ASSET_CHANNEL_ID = int(os.getenv("ASSET_CHANNEL_ID", "0"))

# ローカル画像パス（Railway ではリポジトリ内に同梱しておく）
MALE_IMAGE_PATH = os.getenv("MALE_IMAGE_PATH", "image/male.png")
FEMALE_IMAGE_PATH = os.getenv("FEMALE_IMAGE_PATH", "image/female.png")

# データ保存
DATA_FILE = os.getenv("DATA_FILE", "anonymize_data.json")

# ===================== LOGGING ====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("anon-bot")

# ===================== DISCORD ====================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ===================== DATA MODELS =================
@dataclass
class UserRec:
    gender: str  # "male" | "female"
    alias: str   # 例: 男1 / 女1

# store structure:
# {
#   "male_next": int,
#   "female_next": int,
#   "users": { user_id(str): {"gender": str, "alias": str} },
#   "avatars": {"male": url(str), "female": url(str)}
# }
store = {"male_next": 1, "female_next": 1, "users": {}, "avatars": {}}

# ===================== PERSIST ====================

def save_store():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

def load_store():
    global store
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            store = json.load(f)
    store.setdefault("male_next", 1)
    store.setdefault("female_next", 1)
    store.setdefault("users", {})
    store.setdefault("avatars", {})

# ===================== HELPERS ====================

async def get_or_create_webhook(channel: discord.TextChannel) -> discord.Webhook:
    hooks = await channel.webhooks()
    for h in hooks:
        if h.name == "anonymizer":
            return h
    return await channel.create_webhook(name="anonymizer")

async def decide_gender_by_role(member: discord.Member) -> Optional[str]:
    if MALE_ROLE_ID and discord.utils.get(member.roles, id=MALE_ROLE_ID):
        return "male"
    if FEMALE_ROLE_ID and discord.utils.get(member.roles, id=FEMALE_ROLE_ID):
        return "female"
    return None

def next_alias(gender: str) -> str:
    if gender == "female":
        n = store["female_next"]
        store["female_next"] = n + 1
        return f"女{n}"
    else:
        n = store["male_next"]
        store["male_next"] = n + 1
        return f"男{n}"

async def ensure_avatar_urls(guild: discord.Guild):
    """Upload local images once to Discord to get CDN URLs, store them in `store['avatars']`."""
    # 既にURLがあるならスキップ
    if store["avatars"].get("male") and store["avatars"].get("female"):
        return

    # 画像がなければスキップ（その場合はWebhookのデフォルトアイコンになる）
    need_male = os.path.exists(MALE_IMAGE_PATH)
    need_female = os.path.exists(FEMALE_IMAGE_PATH)
    if not need_male and not need_female:
        log.warning("No local avatar images found. Skipping avatar upload.")
        return

    # アップロード先チャンネルを決定
    channel: Optional[discord.TextChannel] = None
    if ASSET_CHANNEL_ID:
        ch = guild.get_channel(ASSET_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            channel = ch
    if channel is None:
        # 対象カテゴリ内の最初のテキストチャンネル
        for ch in guild.text_channels:
            if ch.category and ch.category.id == TARGET_CATEGORY_ID:
                channel = ch
                break
    if channel is None:
        # どこでも良いので最初のテキストチャンネル
        if guild.text_channels:
            channel = guild.text_channels[0]
    if channel is None:
        log.error("No text channel available to upload avatar images.")
        return

    # 画像をアップロード → 添付のCDN URLを取得
    if need_male and not store["avatars"].get("male"):
        try:
            msg = await channel.send(file=discord.File(MALE_IMAGE_PATH, filename="male.png"))
            if msg.attachments:
                store["avatars"]["male"] = msg.attachments[0].url
                log.info("Male avatar uploaded: %s", store["avatars"]["male"])
        except Exception:
            log.exception("Failed to upload male avatar")

    if need_female and not store["avatars"].get("female"):
        try:
            msg = await channel.send(file=discord.File(FEMALE_IMAGE_PATH, filename="female.png"))
            if msg.attachments:
                store["avatars"]["female"] = msg.attachments[0].url
                log.info("Female avatar uploaded: %s", store["avatars"]["female"])
        except Exception:
            log.exception("Failed to upload female avatar")

    save_store()

# ===================== COMMANDS ===================

@bot.tree.command(name="status_anon", description="匿名化の状況を表示")
async def status_anon(interaction: discord.Interaction):
    male_url = store["avatars"].get("male", "(未設定)")
    female_url = store["avatars"].get("female", "(未設定)")
    await interaction.response.send_message(
        f"対象カテゴリ: <#{TARGET_CATEGORY_ID}>
"
        f"次の男性別名: 男{store['male_next']} / 次の女性別名: 女{store['female_next']}
"
        f"男性アイコン: {male_url}
女性アイコン: {female_url}",
        ephemeral=True,
    )

@bot.tree.command(name="reload_avatars", description="ローカル画像を再アップロードしてWebhook用アイコンURLを更新")
async def reload_avatars(interaction: discord.Interaction):
    await ensure_avatar_urls(interaction.guild)
    await interaction.response.send_message("アバターURLを再取得しました。", ephemeral=True)

# ===================== MESSAGE RELAY ==============

@bot.event
async def on_message(message: discord.Message):
    # Bot/DM/システムは対象外
    if message.author.bot or not message.guild:
        return

    # 対象カテゴリでなければスルー
    if not message.channel.category or message.channel.category.id != TARGET_CATEGORY_ID:
        return

    # ロールで性別判定（なければスルー）
    gender = await decide_gender_by_role(message.author)
    if gender is None:
        return

    # 初回なら別名を採番
    uid = str(message.author.id)
    rec = store["users"].get(uid)
    if not rec:
        alias = next_alias(gender)
        store["users"][uid] = {"gender": gender, "alias": alias}
        save_store()
    else:
        alias = rec["alias"]
        # ロールが変わっていたら性別を更新（別名は維持）
        if rec.get("gender") != gender:
            rec["gender"] = gender
            save_store()

    # アバターURLを確保
    await ensure_avatar_urls(message.guild)
    avatar_url = store["avatars"].get("male") if gender == "male" else store["avatars"].get("female")

    # Webhookで再投稿
    try:
        webhook = await get_or_create_webhook(message.channel)

        content = message.content
        files = []
        if message.attachments:
            for att in message.attachments:
                files.append(await att.to_file())

        # 返信は引用に変換（Webhookでの message reference 代替）
        if message.reference and isinstance(message.reference.resolved, discord.Message):
            quoted = message.reference.resolved
            head = (quoted.content or "(添付のみ)").replace("`", "​`")
            head = head[:120] + ("…" if len(head) > 120 else "")
            content = f"> **返信:** {head}
{content}"

        await webhook.send(
            content or "​",
            username=store["users"][uid]["alias"],
            avatar_url=avatar_url,
            files=files if files else None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await message.delete()
    except Exception as e:
        log.exception("relay failed: %s", e)

# ===================== READY ======================

@bot.event
async def on_ready():
    load_store()
    # ギルドコマンドの即時同期
    try:
        if GUILD_ID:
            await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
            log.info("Slash commands synced to guild %s", GUILD_ID)
        else:
            await bot.tree.sync()
            log.info("Slash commands globally synced")
    except Exception:
        log.exception("Slash command sync failed")

    # アバターURLの用意
    try:
        for guild in bot.guilds:
            if GUILD_ID and guild.id != GUILD_ID:
                continue
            await ensure_avatar_urls(guild)
    except Exception:
        log.exception("Avatar ensure failed")

    log.info("Logged in as %s", bot.user)

# ===================== MAIN =======================
if __name__ == "__main__":
    if TOKEN == "PASTE_YOUR_TOKEN" or not TOKEN:
        print("Please set DISCORD_TOKEN")
    else:
        bot.run(TOKEN)
