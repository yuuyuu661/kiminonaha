# bot.py
# Discord anonymizer bot (role-based only) with channel-based targeting.
# - Messages in TARGET_CHANNEL_ID are reposted via webhook with gendered alias (男1/女1...) and fixed avatars.
# - Gender is determined ONLY by roles (MALE_ROLE_ID / FEMALE_ROLE_ID).
# - Avatars are loaded from ./image and uploaded once to ASSET_CHANNEL_ID to obtain CDN URLs.
# - Optional: a join panel can be posted to JOIN_PANEL_CHANNEL_ID to explain the rules.

import os
import json
import logging
from dataclasses import dataclass
from typing import Optional

import discord
from discord.ext import commands

# ===================== CONFIG (IDs you provided) =====================
TOKEN = os.getenv("DISCORD_TOKEN", "PASTE_YOUR_TOKEN")
# 即時同期したいギルドを固定（あなたのサーバー）：
GUILD_ID = int(os.getenv("GUILD_ID", "1398607685158440991"))

# --- Channels ---
ASSET_CHANNEL_ID = 1407976326199120053        # ロール別画像アップロード用
JOIN_PANEL_CHANNEL_ID = 1407986289990438912   # 参加ボタン設置用（情報表示）
TARGET_CHANNEL_ID = 1407976431056719945       # 匿名化チャット送信先

# --- Roles (role-based only) ---
MALE_ROLE_ID = 1399390214295785623
FEMALE_ROLE_ID = 1399390384756363264

# --- Local images ---
MALE_IMAGE_PATH = os.getenv("MALE_IMAGE_PATH", "image/male.png")
FEMALE_IMAGE_PATH = os.getenv("FEMALE_IMAGE_PATH", "image/female.png")

# --- Data file ---
DATA_FILE = os.getenv("DATA_FILE", "anonymize_data.json")

# ===================== LOGGING =====================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("anon-bot")

# ===================== DISCORD =====================
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

ZWSP = "\u200b"  # ゼロ幅スペース（空投稿対策・明示表記）

# ===================== SMALL HELPERS (testable) ===

def build_status_msg(target_id: int, male_next: int, female_next: int, male_url: str, female_url: str) -> str:
    """Compose the status message safely without f-strings.

    >>> s = build_status_msg(123, 5, 7, "m.png", "f.png")
    >>> s.splitlines()[0]
    '対象チャンネル: <#123>'
    >>> '次の男性別名: 男5 / 次の女性別名: 女7' in s
    True
    >>> '男性アイコン: m.png' in s and '女性アイコン: f.png' in s
    True
    """
    return "対象チャンネル: <#{}>\n次の男性別名: 男{} / 次の女性別名: 女{}\n男性アイコン: {}\n女性アイコン: {}".format(
        target_id, male_next, female_next, male_url, female_url
    )


def build_reply_quote(head: str, content: str) -> str:
    """Format quoted reply safely.

    >>> build_reply_quote('hello', 'world')
    '> **返信:** hello\nworld'
    >>> '\n' in build_reply_quote('h', 'w')
    True
    """
    return "> **返信:** {}\n{}".format(head, content)


def build_join_info_text(target_id: int) -> str:
    """Build the JOIN panel informational text safely.

    >>> t = build_join_info_text(999)
    >>> '対象チャンネル: <#999>' in t
    True
    """
    return (
        "このサーバーの匿名化は『ロール判定のみ』で動作します。\n"
        "・男ロールを持つ → 男1/男2…\n"
        "・女ロールを持つ → 女1/女2…\n"
        "対象チャンネル: <#{}>\n"
        "※ロールが無いユーザーの発言は匿名化されません。"
    ).format(target_id)

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
        return "女{}".format(n)
    else:
        n = store["male_next"]
        store["male_next"] = n + 1
        return "男{}".format(n)

async def ensure_avatar_urls(guild: discord.Guild):
    """Upload local images once to Discord to get CDN URLs, store them in `store['avatars']`."""
    # 既にURLがあるならスキップ
    if store["avatars"].get("male") and store["avatars"].get("female"):
        return

    need_male = os.path.exists(MALE_IMAGE_PATH)
    need_female = os.path.exists(FEMALE_IMAGE_PATH)
    if not need_male and not need_female:
        log.warning("No local avatar images found. Skipping avatar upload.")
        return

    # アップロード先チャンネルを決定（ASSET_CHANNEL_ID 優先）
    channel: Optional[discord.TextChannel] = None
    ch = guild.get_channel(ASSET_CHANNEL_ID)
    if isinstance(ch, discord.TextChannel):
        channel = ch
    if channel is None and guild.text_channels:
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
    male_url = store.get("avatars", {}).get("male", "(未設定)")
    female_url = store.get("avatars", {}).get("female", "(未設定)")
    msg = build_status_msg(
        TARGET_CHANNEL_ID,
        store.get('male_next', 1),
        store.get('female_next', 1),
        male_url,
        female_url,
    )
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="reload_avatars", description="ローカル画像を再アップロードしてWebhook用アイコンURLを更新")
async def reload_avatars(interaction: discord.Interaction):
    await ensure_avatar_urls(interaction.guild)
    await interaction.response.send_message("アバターURLを再取得しました。", ephemeral=True)

# 任意：JOINパネルを配置（情報表示用）
class JoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="参加方法を見る", style=discord.ButtonStyle.primary, custom_id="join_info")
    async def join_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        text = build_join_info_text(TARGET_CHANNEL_ID)
        await interaction.response.send_message(text, ephemeral=True)

@bot.tree.command(name="post_join_panel", description="JOINパネルを設置（情報表示のみ）")
async def post_join_panel(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    if channel is None:
        # 既定の JOIN_PANEL_CHANNEL_ID に投稿
        ch = interaction.guild.get_channel(JOIN_PANEL_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            channel = ch
        else:
            channel = interaction.channel
    view = JoinView()
    await channel.send("匿名化のルール：ボタンから確認できます。", view=view)
    await interaction.response.send_message("JOINパネルを設置しました。", ephemeral=True)

# ===================== MESSAGE RELAY ==============

@bot.event
async def on_message(message: discord.Message):
    # Bot/DM/システムは対象外
    if message.author.bot or not message.guild:
        return

    # 対象チャンネルのみ
    if message.channel.id != TARGET_CHANNEL_ID:
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
            head = (quoted.content or "(添付のみ)").replace("`", "\u200b`")
            head = head[:120] + ("…" if len(head) > 120 else "")
            content = build_reply_quote(head, content)

        await webhook.send(
            content or ZWSP,
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
    # ギルドコマンドの即時同期（あなたのギルドに固定同期）
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        log.info("Slash commands synced to guild %s", GUILD_ID)
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

    # 永続View登録（再起動後もJOINボタンを生かす）
    try:
        bot.add_view(JoinView())
    except Exception:
        pass

    log.info("Logged in as %s", bot.user)

# ===================== MAIN =======================
if __name__ == "__main__":
    if TOKEN == "PASTE_YOUR_TOKEN" or not TOKEN:
        print("Please set DISCORD_TOKEN")
    else:
        bot.run(TOKEN)
