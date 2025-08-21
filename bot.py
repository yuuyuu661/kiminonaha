import os
import logging
import discord
from discord.ext import commands
from discord import app_commands

# ====== 環境変数 ======
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # 必須
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# ギルド即時反映（カンマ区切りで複数可）
GUILD_IDS = [int(x.strip()) for x in os.getenv("GUILD_IDS", "1398607685158440991").split(",") if x.strip().isdigit()]

# ====== ログ ======
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="(%(asctime)s) [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("jumpbot")

# ====== Intents / Bot ======
intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


# ====== 共通ユーティリティ ======
def channel_jump_url(guild_id: int, channel_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}"


async def pick_representative_text_channel_for_category(guild: discord.Guild, category_id: int) -> discord.TextChannel | None:
    category = discord.utils.get(guild.categories, id=category_id)
    if not category:
        return None
    text_channels = sorted(
        [ch for ch in category.channels if isinstance(ch, discord.TextChannel)],
        key=lambda c: c.position
    )
    return text_channels[0] if text_channels else None


# ====== ボタン作成コマンド ======
@tree.command(name="create_jump_button", description="指定したチャンネルへ飛べるボタンを作成します。")
@app_commands.describe(
    channel_id="ジャンプ先のチャンネルID（テキスト/ボイスどちらでも可）",
    label="ボタンの表示名（未指定時はチャンネル名）",
)
async def create_jump_button(interaction: discord.Interaction, channel_id: str, label: str | None = None):
    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message("ギルド内で実行してください。", ephemeral=True)

    try:
        target_id = int(channel_id)
    except ValueError:
        return await interaction.response.send_message("channel_id は数値IDで指定してください。", ephemeral=True)

    channel = guild.get_channel(target_id)
    if channel is None:
        return await interaction.response.send_message("指定チャンネルが見つかりません。権限/IDをご確認ください。", ephemeral=True)

    button_label = label or (channel.name if hasattr(channel, "name") else "Open Channel")
    url = channel_jump_url(guild.id, target_id)

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=button_label, url=url))

    embed = discord.Embed(
        title="チャンネルジャンプ",
        description=f"{channel.mention} へ移動するボタンです。",
        color=0x2ECC71
    )

    await interaction.response.send_message(embed=embed, view=view)
    log.info(f"Posted jump button to channel {interaction.channel_id} -> {url}")


@tree.command(name="create_category_button", description="カテゴリの代表テキストチャンネルへ飛べるボタンを作成します。")
@app_commands.describe(
    category_id="カテゴリID（カテゴリ自体に直リンク不可のため、最上段のテキストチャンネルに飛びます）",
    label="ボタンの表示名（未指定時はカテゴリ名）",
)
async def create_category_button(interaction: discord.Interaction, category_id: str, label: str | None = None):
    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message("ギルド内で実行してください。", ephemeral=True)

    try:
        cat_id = int(category_id)
    except ValueError:
        return await interaction.response.send_message("category_id は数値IDで指定してください。", ephemeral=True)

    category = discord.utils.get(guild.categories, id=cat_id)
    if category is None:
        return await interaction.response.send_message("指定カテゴリが見つかりません。権限/IDをご確認ください。", ephemeral=True)

    rep_ch = await pick_representative_text_channel_for_category(guild, cat_id)
    if rep_ch is None:
        return await interaction.response.send_message(
            "このカテゴリにテキストチャンネルがありません。リンク先を作れませんでした。",
            ephemeral=True
        )

    button_label = label or f"{category.name} を開く"
    url = channel_jump_url(guild.id, rep_ch.id)

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label=button_label, url=url))

    embed = discord.Embed(
        title="カテゴリジャンプ",
        description=f"カテゴリ **{category.name}** の代表チャンネル {rep_ch.mention} を開きます。",
        color=0x3498DB
    )

    await interaction.response.send_message(embed=embed, view=view)
    log.info(f"Posted category button to channel {interaction.channel_id} -> {url}")


@tree.command(name="create_category_menu", description="カテゴリ内の複数チャンネルへ飛べるボタンをまとめて作成します。")
@app_commands.describe(
    category_id="カテゴリID（内部のテキストチャンネルから最大5個ボタン化）",
    max_buttons="作成するボタン数（1〜5。既定5）",
    prefix_label="ボタン共通のプレフィックス（例：'開く：'）"
)
async def create_category_menu(interaction: discord.Interaction, category_id: str, max_buttons: int = 5, prefix_label: str | None = None):
    guild = interaction.guild
    if guild is None:
        return await interaction.response.send_message("ギルド内で実行してください。", ephemeral=True)

    try:
        cat_id = int(category_id)
    except ValueError:
        return await interaction.response.send_message("category_id は数値IDで指定してください。", ephemeral=True)

    if not (1 <= max_buttons <= 5):
        return await interaction.response.send_message("max_buttons は 1〜5 の範囲で指定してください。", ephemeral=True)

    category = discord.utils.get(guild.categories, id=cat_id)
    if category is None:
        return await interaction.response.send_message("指定カテゴリが見つかりません。", ephemeral=True)

    text_channels = sorted(
        [ch for ch in category.channels if isinstance(ch, discord.TextChannel)],
        key=lambda c: c.position
    )[:max_buttons]

    if not text_channels:
        return await interaction.response.send_message("このカテゴリにテキストチャンネルがありません。", ephemeral=True)

    view = discord.ui.View()
    for ch in text_channels:
        label = f"{prefix_label or ''}{ch.name}"
        view.add_item(discord.ui.Button(label=label, url=channel_jump_url(guild.id, ch.id)))

    embed = discord.Embed(
        title=f"カテゴリ：{category.name}",
        description="下のボタンから各チャンネルへジャンプできます。",
        color=0x9B59B6
    )
    await interaction.response.send_message(embed=embed, view=view)


# ====== 文章送信コマンド ======
@tree.command(name="say", description="Botとしてこのチャンネルへ任意の文章を投稿します。")
@app_commands.describe(
    content="投稿する本文（2000文字を超える場合は自動分割）",
    as_embed="埋め込みで送信する（長文時に見やすい）",
    suppress_mentions="メンションを抑制する（@everyone/@here/ロール/ユーザー）",
    reply_to_message_id="返信先メッセージのID（任意）"
)
async def say(
    interaction: discord.Interaction,
    content: str,
    as_embed: bool = False,
    suppress_mentions: bool = True,
    reply_to_message_id: str | None = None
):
    """指定テキストをボットとして送信。"""
    channel = interaction.channel
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
        return await interaction.response.send_message("テキストチャンネル内で実行してください。", ephemeral=True)

    # 返信先
    reference = None
    if reply_to_message_id:
        try:
            ref_id = int(reply_to_message_id)
            if hasattr(channel, "fetch_message"):
                msg = await channel.fetch_message(ref_id)
                reference = msg.to_reference()
        except Exception:
            # 取得失敗でも続行（単に返信しない）
            reference = None

    # メンション制御
    allowed = discord.AllowedMentions(everyone=not suppress_mentions,
                                      roles=not suppress_mentions,
                                      users=not suppress_mentions,
                                      replied_user=False)

    # 送信処理
    async def send_text(text: str):
        if as_embed:
            embed = discord.Embed(description=text, color=0x95A5A6)
            await channel.send(embed=embed, allowed_mentions=allowed, reference=reference)
        else:
            await channel.send(text, allowed_mentions=allowed, reference=reference)

    # 2000文字制限対応：分割（改行優先で切り出し、最悪ハードカット）
    MAX_LEN = 2000 if not as_embed else 4096  # Embed description上限
    if len(content) <= MAX_LEN:
        await send_text(content)
    else:
        buf = content
        while buf:
            if len(buf) <= MAX_LEN:
                chunk, buf = buf, ""
            else:
                # 余裕を持って切る
                cut = buf.rfind("\n", 0, MAX_LEN)
                if cut == -1:
                    cut = MAX_LEN
                chunk, buf = buf[:cut], buf[cut:].lstrip("\n")
            await send_text(chunk)

    await interaction.response.send_message("✅ 送信しました。", ephemeral=True)
    log.info(f"/say used by {interaction.user.id} in {interaction.channel_id}")

# ====== 起動・同期 ======
@bot.event
async def on_ready():
    try:
        if GUILD_IDS:
            for gid in GUILD_IDS:
                await tree.sync(guild=discord.Object(id=gid))
                log.info(f"Synced commands to guild {gid}")
        else:
            await tree.sync()
            log.info("Synced commands globally")
    except Exception as e:
        log.exception("Slash command sync failed: %s", e)

    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN を設定してください。")
    bot.run(DISCORD_TOKEN)
