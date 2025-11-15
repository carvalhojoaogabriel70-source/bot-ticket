import os
import json
import discord
from discord.ext import commands
from discord.ui import Button, View
from datetime import datetime

# ===== Load configuration (defaults for painel) =====
CONFIG_PATH = "config.json"
default_config = {
    "default_image": "",
    "default_description": "Clique no botão para abrir um ticket"
}

if os.path.exists(CONFIG_PATH):
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = default_config
else:
    cfg = default_config
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

# ===== Environment variables (set these in Railway) =====
TOKEN = os.getenv("DISCORD_TOKEN")
SUPORTE_ROLE_ID = int(os.getenv("SUPORTE_ROLE_ID", "0"))  # role id allowed to assume tickets
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))    # channel id for logs (optional)
CATEGORIA_TICKETS = os.getenv("CATEGORIA_TICKETS", "Tickets")

if not TOKEN:
    raise SystemExit("ERROR: DISCORD_TOKEN environment variable not set.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# In-memory storage for painel message location (will not persist across restarts)
# We also store painel info in config.json so you can change defaults.
if "painel" not in cfg:
    cfg["painel"] = {"channel_id": None, "message_id": None}

@bot.event
async def on_ready():
    print(f"{bot.user} está online! ({bot.user.id})")

# ===== Comando para criar painel (ou recriar) =====
@bot.command()
@commands.has_permissions(manage_guild=True)
async def painel(ctx, imagem_url: str = None, *, descricao: str = None):
    """
    Cria um painel de ticket. Exemplo:
    !painel https://i.imgur.com/foto.png Aqui vai a descrição
    Se você quiser usar os padrões, chame !painel sem argumentos.
    """
    descricao = descricao if descricao is not None else cfg.get("default_description", "")
    imagem = imagem_url if imagem_url is not None else cfg.get("default_image", "")

    embed = discord.Embed(
        title="TICKET",
        description=descricao,
        color=discord.Color.purple()
    )
    if imagem:
        embed.set_image(url=imagem)
    embed.set_footer(text="ANTI SOCIAL SOCIAL CLUB ©")

    abrir_button = Button(label="ABRIR TICKET", style=discord.ButtonStyle.primary, emoji="🎫")

    async def abrir_callback(interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        category = discord.utils.get(guild.categories, name=CATEGORIA_TICKETS)
        if not category:
            category = await guild.create_category(CATEGORIA_TICKETS)

        safe_name = user.name.lower().replace(" ", "-")
        channel_name = f"ticket-{safe_name}"
        existing_channel = discord.utils.get(guild.channels, name=channel_name)
        if existing_channel:
            await interaction.followup.send(f"{user.mention}, você já tem um ticket: {existing_channel.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        channel = await guild.create_text_channel(channel_name, overwrites=overwrites, category=category)
        await channel.send(f"Olá {user.mention}, seu ticket foi criado! Nossa equipe irá te atender em breve.")

        view = View(timeout=None)

        assumir_button = Button(label="ASSUMIR TICKET", style=discord.ButtonStyle.blurple, emoji="🛠️")
        fechar_button = Button(label="FECHAR TICKET", style=discord.ButtonStyle.red, emoji="❌")

        async def assumir_callback(interaction_assumir: discord.Interaction):
            member = interaction_assumir.user
            role = guild.get_role(SUPORTE_ROLE_ID)
            if SUPPORT_ROLE_CHECK := (role is not None):
                if role not in member.roles:
                    await interaction_assumir.response.send_message("Você não pode assumir este ticket.", ephemeral=True)
                    return
            else:
                # If no role set, require manage_messages perm as fallback
                if not member.guild_permissions.manage_messages:
                    await interaction_assumir.response.send_message("Você não pode assumir este ticket (sem cargo configurado).", ephemeral=True)
                    return
            await channel.set_permissions(member, read_messages=True, send_messages=True)
            await channel.send(f"{member.mention} assumiu o ticket!")
            log_channel = guild.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
            if log_channel:
                await log_channel.send(f"{member.mention} assumiu o ticket {channel.mention}.")
            await interaction_assumir.response.send_message("Você assumiu este ticket.", ephemeral=True)

        async def fechar_callback(interaction_fechar: discord.Interaction):
            log_channel = guild.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
            messages = []
            async for msg in channel.history(limit=None, oldest_first=True):
                # avoid huge transcripts if channel is very large
                messages.append(msg)
            transcript_lines = []
            for msg in messages:
                ts = msg.created_at.strftime("%d/%m/%Y %H:%M")
                content = msg.content or ""
                transcript_lines.append(f"[{ts}] {msg.author}: {content}")
            transcript = "\n".join(transcript_lines)
            now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"transcript-{channel.name}-{now}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(transcript)
            if log_channel:
                try:
                    await log_channel.send(f"Ticket {channel.name} fechado por {interaction_fechar.user.mention}", file=discord.File(filename))
                except Exception:
                    await log_channel.send(f"Ticket {channel.name} fechado por {interaction_fechar.user.mention} (não foi possível enviar o arquivo).")
            await interaction_fechar.response.send_message("Fechando ticket...", ephemeral=True)
            await channel.delete()

        assumir_button.callback = assumir_callback
        fechar_button.callback = fechar_callback

        view.add_item(assumir_button)
        view.add_item(fechar_button)

        await channel.send("Gerencie este ticket com os botões abaixo:", view=view)

        log_channel = guild.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
        if log_channel:
            await log_channel.send(f"{user.mention} abriu o ticket {channel.mention}.")

        await interaction.followup.send(f"{user.mention}, seu ticket foi criado: {channel.mention}", ephemeral=True)

    abrir_button.callback = abrir_callback
    view = View(timeout=None)
    view.add_item(abrir_button)

    mensagem = await ctx.send(embed=embed, view=view)

    # save painel location to config file for future edits
    cfg["painel"] = {"channel_id": mensagem.channel.id, "message_id": mensagem.id}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

    await ctx.send("Painel criado e salvo para edição futura.")

# ===== Comando para editar painel existente =====
@bot.command()
@commands.has_permissions(manage_guild=True)
async def editarpainel(ctx, imagem_url: str = None, *, descricao: str = None):
    """
    Edita o painel salvo. Use apenas a imagem ou apenas a descrição se quiser.
    Exemplos:
    !editarpainel https://i.imgur.com/nova.png Nova descrição
    !editarpainel None Nova descrição
    """
    painel = cfg.get("painel", {})
    if not painel.get("channel_id") or not painel.get("message_id"):
        await ctx.send("Nenhum painel salvo para editar. Use !painel para criar um painel primeiro.")
        return

    channel = bot.get_channel(painel["channel_id"])
    if not channel:
        await ctx.send("Canal do painel não encontrado (talvez o bot foi reiniciado).")
        return
    try:
        message = await channel.fetch_message(painel["message_id"])
    except Exception:
        await ctx.send("Mensagem do painel não encontrada.")
        return

    # get existing embed or create a new one
    embed = message.embeds[0] if message.embeds else discord.Embed(title="TICKET", color=discord.Color.purple())
    if descricao:
        embed.description = descricao
        cfg["default_description"] = descricao
    if imagem_url and imagem_url.lower() != "none":
        embed.set_image(url=imagem_url)
        cfg["default_image"] = imagem_url

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

    await message.edit(embed=embed)
    await ctx.send("Painel atualizado com sucesso!")

# ===== Comando para mostrar configuração atual =====
@bot.command()
async def painelinfo(ctx):
    info = cfg.get("painel", {})
    desc = cfg.get("default_description", "")
    img = cfg.get("default_image", "")
    await ctx.send(f"Painel salvo: {info}\\nDescrição padrão: {desc}\\nImagem padrão: {img}")

# ===== Error handlers =====
@painel.error
@editarpainel.error
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Você precisa de permissão de **Gerenciar servidor** para usar esse comando.")
    else:
        await ctx.send(f"Ocorreu um erro: {error}")

# ===== Run =====
if __name__ == "__main__":
    bot.run(TOKEN)
