import os
import logging
import discord
from discord.ext import commands
from discord import app_commands

# ====== 環境変数 ======
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # 必須
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# GUILD_IDS: 空なら “参加中すべてのギルド” へ同期。カンマ区切りで複数可。
_GUILD_IDS_ENV = os.getenv("GUILD_IDS", "").strip()
GUILD_IDS = [int(x.strip()) for x in _GUILD_IDS_ENV.split(",") if x.strip().isdigit()]

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
    if not interaction.user or not isinstance(interaction.user, discord.Member):
        return False
    return any(r.id == ALLOWED_ROLE_ID for r in interaction.user.roles)

def role_check():
    return app_commands.check(lambda i: has_required_role(i))

@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        try:
            if interaction.response.is_done():
                await interaction.followup.send("このコマンドを使う権限がありません。", ephemeral=True)
            else:
                await interaction.response.send_message("このコマンドを使う権限がありません。", ephemeral=True)
        except Exception:
            pass
        return
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
        return await interaction.response.send_message("このカテゴリにテキストチャンネルがありません。リンク先を作れませんでした。", ephemeral=True)

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

    reference = None
    if reply_to_message_id:
        try:
            ref_id = int(reply_to_message_id)
            if hasattr(channel, "fetch_message"):
                msg = await channel.fetch_message(ref_id)
                reference = msg.to_reference()
        except Exception:
            reference = None

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


# ====== 診断 / 確認 / 再同期 / 招待リンク / 手動登録 ======
@tree.command(name="diag_here", description="このチャンネルでコマンドを使えるか診断します（あなた基準）。")
@role_check()
async def diag_here(interaction: discord.Interaction):
    m = interaction.user if isinstance(interaction.user, discord.Member) else None
    ch = interaction.channel
    if not m or not hasattr(ch, "permissions_for"):
        return await interaction.response.send_message("ギルドのテキストチャンネルで実行してください。", ephemeral=True)
    perms = ch.permissions_for(m)
    role_ids = [r.id for r in m.roles]
    has_role = any(rid == ALLOWED_ROLE_ID for rid in role_ids)
    await interaction.response.send_message(
        "\n".join([
            f"Guild: {interaction.guild.id}",
            f"Channel: {ch.id}",
            f"あなたのロールIDs: {role_ids}",
            f"必須ロール保持: {has_role}",
            f"Use Application Commands: {perms.use_application_commands}",
            f"Send Messages: {perms.send_messages}",
            f"Embed Links: {perms.embed_links}",
            f"Read Message History: {perms.read_message_history}",
        ]),
        ephemeral=True
    )

@tree.command(name="list_commands", description="このサーバーに登録済みのスラッシュコマンド一覧を表示します。")
@role_check()
async def list_commands(interaction: discord.Interaction):
    names = [f"/{c.name} — {c.description or ''}" for c in tree.get_commands(guild=interaction.guild)]
    if not names:
        names = ["(none)"]
    await interaction.response.send_message("登録コマンド：\n" + "\n".join(names), ephemeral=True)

@tree.command(name="resync_commands", description="古いコマンドを全削除し、グローバル→ギルドの順で再登録します。")
@role_check()
async def resync_commands(interaction: discord.Interaction):
    await interaction.response.send_message("⏳ コマンドを再同期中…", ephemeral=True)
    try:
        # ① グローバルをクリアして最新に同期
        tree.clear_commands(guild=None)
        await tree.sync()  # 統合画面対策として必ずグローバルへ登録

        # ② 参加ギルドへ “グローバル定義をコピー → 同期”
        joined_ids = {g.id for g in bot.guilds}
        target_ids = [gid for gid in GUILD_IDS if gid in joined_ids] or list(joined_ids)
        for gid in target_ids:
            gobj = discord.Object(id=gid)
            tree.clear_commands(guild=gobj)
            tree.copy_global_to(guild=gobj)
            await tree.sync(guild=gobj)

        await interaction.followup.send("✅ 再同期完了。Discordを再読込してからお試しください。", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ Missing Access。招待URLの scope=bot+applications.commands と権限を確認してください。", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 予期せぬエラー: {e}", ephemeral=True)

@tree.command(name="invite_link", description="このBotの正しい招待URLを表示します。")
@role_check()
async def invite_link(interaction: discord.Interaction, permissions: int = 84992):
    cid = interaction.client.user.id
    url = f"https://discord.com/oauth2/authorize?client_id={cid}&permissions={permissions}&scope=bot+applications.commands"
    await interaction.response.send_message(f"招待URL：\n{url}", ephemeral=True)

@tree.command(name="force_register", description="グローバル定義をこのサーバーにコピーして即同期します。")
@role_check()
async def force_register(interaction: discord.Interaction):
    await interaction.response.send_message("⏳ 登録反映中…", ephemeral=True)
    try:
        gobj = discord.Object(id=interaction.guild.id)
        tree.clear_commands(guild=gobj)
        tree.copy_global_to(guild=gobj)
        await tree.sync(guild=gobj)
        names = [c.name for c in tree.get_commands(guild=gobj)]
        await interaction.followup.send(f"✅ 同期完了：{names}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ エラー: {e}", ephemeral=True)


# ====== 起動・同期（グローバル→ギルドの順で確実に反映） ======
@bot.event
async def on_ready():
    try:
        joined_ids = [g.id for g in bot.guilds]
        log.info(f"Joined guilds: {joined_ids}")

        # ① まずグローバルへ現在の定義を同期（統合画面で「コマンドなし」を防ぐ）
        try:
            await tree.sync()
            log.info("Synced commands globally")
        except Exception as e:
            log.exception(f"Global sync failed: {e}")

        # ② そのグローバル定義を各ギルドにコピーして即同期
        target_ids = [gid for gid in GUILD_IDS if gid in joined_ids] or joined_ids
        if _GUILD_IDS_ENV and not any(gid in joined_ids for gid in GUILD_IDS):
            log.warning("GUILD_IDS に参加していないIDが指定されています。全参加ギルドへフォールバック同期します。")

        for gid in target_ids:
            gobj = discord.Object(id=gid)
            try:
                tree.clear_commands(guild=gobj)
                tree.copy_global_to(guild=gobj)
                await tree.sync(guild=gobj)
                names = [c.name for c in tree.get_commands(guild=gobj)]
                log.info(f"Synced to guild {gid}: {len(names)} commands -> {names}")
            except discord.Forbidden:
                log.error(f"Missing access to sync guild {gid}. scope と権限を確認してください。")
            except Exception as e:
                log.exception(f"Guild sync failed for {gid}: {e}")
    except Exception as e:
        log.exception("Slash command sync failed: %s", e)

    log.info(f"Logged in as {bot.user} (ID: {bot.user.id})")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("環境変数 DISCORD_TOKEN を設定してください。")
    bot.run(DISCORD_TOKEN)
