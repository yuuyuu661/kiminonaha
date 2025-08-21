import os
import logging
import discord
from discord.ext import commands
from discord import app_commands

# ====== 環境変数 ======
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # 必須
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# 即時反映したいサーバーIDをカンマ区切りで（例: "1398607685158440991,123..."）
GUILD_IDS = [int(x.strip()) for x in os.getenv("GUILD_IDS", "1398607685158440991").split(",") if x.strip().isdigit()]

# ====== 制限ロール ======
ALLOWED_ROLE_ID = 1398724601256874014  # ← このロール所持者のみ実行可

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


# ====== 権限チェック ======
def has_required_role(interaction: discord.Interaction) -> bool:
    """指定ロールを持っているか確認"""
    if not interaction.user or not isinstance(interaction.user, discord.Member):
        return False
    return any(r.id == ALLOWED_ROLE_ID for r in interaction.user.roles)

def role_check():
    return app_commands.check(lambda i: has_required_role(i))

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # 権限不足の文言を分かりやすく出す
    if isinstance(error, app_commands.CheckFailure):
        try:
            if interaction.response.is_done():
                await interaction.followup.send("このコマンドを使う権限がありません。", ephemeral=True)
            else:
                await interaction.response.send_message("このコマンドを使う権限がありません。", ephemeral=True)
        except Exception:
            pass
        return
    # その他はログのみ
    log.exception("App command error: %s", error)


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
@role_check()
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

    button_label = label or (getattr(channel, "name", None) or "Open Channel")
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
@role_check()
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
@role_check()
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
@role_check()
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
            reference = None  # 取得失敗でも続行

    # メンション制御
    allowed = discord.AllowedMentions(
        everyone=not suppress_mentions,
        roles=not suppress_mentions,
        users=not suppress_mentions,
        replied_user=False
    )

    async def send_text(text: str):
        if as_embed:
            embed = discord.Embed(description=text, color=0x95A5A6)
            await channel.send(embed=embed, allowed_mentions=allowed, reference=reference)
        else:
            await channel.send(text, allowed_mentions=allowed, reference=reference)

    # 文字数制限対応（Embed: 4096 / 通常: 2000）
    MAX_LEN = 4096 if as_embed else 2000
    if len(content) <= MAX_LEN:
        await send_text(content)
    else:
        buf = content
        while buf:
            if len(buf) <= MAX_LEN:
                chunk, buf = buf, ""
            else:
                cut = buf.rfind("\n", 0, MAX_LEN)
                if cut == -1:
                    cut = MAX_LEN
                chunk, buf = buf[:cut], buf[cut:].lstrip("\n")
            await send_text(chunk)

    await interaction.response.send_message("✅ 送信しました。", ephemeral=True)
    log.info(f"/say used by {interaction.user.id} in {interaction.channel_id}")


# ====== 登録確認 & 強制再同期 ======
@tree.command(name="list_commands", description="このサーバーに登録済みのスラッシュコマンド一覧を表示します。")
@role_check()
async def list_commands(interaction: discord.Interaction):
    cmds = [f"/{c.name} — {c.description or ''}" for c in tree.get_commands(guild=interaction.guild)]
    if not cmds:
        cmds = ["(none)"]
    await interaction.response.send_message("登録コマンド：\n" + "\n".join(cmds), ephemeral=True)

@tree.command(name="resync_commands", description="古いスラッシュコマンドを全削除し、現在の定義で再同期します。")
@role_check()
async def resync_commands(interaction: discord.Interaction):
    await interaction.response.send_message("⏳ コマンドを再同期中…", ephemeral=True)
    try:
        # グローバルをクリア → 同期（ここでは現定義を反映）
        tree.clear_commands(guild=None)
        await tree.sync()

        # 参加中のギルドだけに再同期
        joined_ids = {g.id for g in bot.guilds}
        target_ids = [gid for gid in GUILD_IDS if gid in joined_ids] if GUILD_IDS else list(joined_ids)

        for gid in target_ids:
            guild_obj = discord.Object(id=gid)
            tree.clear_commands(guild=guild_obj)
            await tree.sync(guild=guild_obj)

        await interaction.followup.send("✅ 再同期が完了しました。Discordを再読込すると反映が早いです。", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ Missing Access。招待スコープ `applications.commands` と権限を確認してください。", ephemeral=True)
    except Exception as e:
        log.exception("Resync failed: %s", e)
        await interaction.followup.send(f"❌ 予期せぬエラー: {e}", ephemeral=True)


# ====== 起動・同期（堅牢版） ======
@bot.event
async def on_ready():
    try:
        if GUILD_IDS:
            joined_ids = {g.id for g in bot.guilds}
            target_ids = [gid for gid in GUILD_IDS if gid in joined_ids]
            missing = [gid for gid in GUILD_IDS if gid not in joined_ids]
            if missing:
                log.warning(f"Bot is not in these guilds (skip sync): {missing}")

            for gid in target_ids:
                try:
                    await tree.sync(guild=discord.Object(id=gid))  # 即時ギルド同期
                    log.info(f"Synced commands to guild {gid}")
                except discord.Forbidden:
                    log.error(f"Missing access to sync guild {gid}. Check invite scope 'applications.commands' and permissions.")
                except Exception as e:
                    log.exception(f"Sync failed for guild {gid}: {e}")
        else:
            await tree.sync()  # グローバル同期（反映遅め）
            log.info("Synced commands globally")
    except Exception as e:
        log.exception("Slash command sync failed: %s", e)

    # 同期結果の可視化（デバッグ）
    for g in bot.guilds:
        names = [c.name for c in tree.get_commands(guild=g)]
        log.info(f"Guild {g.id}: {len(names)} commands -> {names}")

    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")



if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN を設定してください。")
    bot.run(DISCORD_TOKEN)

