import discord
from discord.ext import commands
import os
import tempfile
import sys
import time
import io
import asyncio
from collections import deque

# ─────────────────────────────────────────────────────────────
#  Importa os módulos do deobfuscator
# ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

try:
    from decryptor_main import Deobfuscator
    from pattern_scanner import PatternScanner
    from execution_engine import ExecutionEngine
except ImportError as e:
    print(f"[ERRO] Módulo não encontrado: {e}")
    exit(1)

# ─────────────────────────────────────────────────────────────
#  Configuração
# ─────────────────────────────────────────────────────────────
TOKEN    = os.environ.get("TOKEN")
PREFIX   = "."
MAX_SIZE = 500_000

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

RISK_COLOR = {"High": 0xFF4444, "Medium": 0xFF8C00, "Low": 0xFFD700, "Minimal": 0x00C851}
RISK_EMOJI = {"High": "🔴", "Medium": "🟠", "Low": "🟡", "Minimal": "🟢"}

# ─────────────────────────────────────────────────────────────
#  Estado da música por servidor
# ─────────────────────────────────────────────────────────────
filas = {}       # guild_id -> deque de dicts {title, url, duration, thumbnail, requester}
tocando = {}     # guild_id -> dict da música atual

def get_fila(guild_id):
    if guild_id not in filas:
        filas[guild_id] = deque()
    return filas[guild_id]

# ─────────────────────────────────────────────────────────────
#  Evento: bot online
# ─────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=".deobf | .play"
        )
    )
    print(f"✅  Bot online como {bot.user} | Prefixo: {PREFIX}")

# ─────────────────────────────────────────────────────────────
#  Helper: salvar anexo
# ─────────────────────────────────────────────────────────────
async def salvar_anexo(attachment):
    if attachment.size > MAX_SIZE:
        return None
    data = await attachment.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".lua", mode="wb")
    tmp.write(data)
    tmp.close()
    return tmp.name

# ─────────────────────────────────────────────────────────────
#  Helper: tocar próxima da fila
# ─────────────────────────────────────────────────────────────
async def tocar_proximo(ctx):
    guild_id = ctx.guild.id
    fila = get_fila(guild_id)

    if not fila:
        tocando.pop(guild_id, None)
        embed = discord.Embed(
            title="✅  Fila encerrada",
            description="Todas as músicas foram tocadas!",
            color=0x5865F2
        )
        await ctx.send(embed=embed)
        return

    musica = fila.popleft()
    tocando[guild_id] = musica

    try:
        import yt_dlp
    except ImportError:
        await ctx.send(embed=discord.Embed(
            title="❌  yt-dlp não instalado",
            description="Adicione `yt-dlp` ao `requirements.txt`.",
            color=0xFF4444
        ))
        return

    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'source_address': '0.0.0.0',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(musica['url'], download=False)
            if 'entries' in info:
                info = info['entries'][0]
            audio_url = info['url']
            musica['title'] = info.get('title', musica.get('title', 'Desconhecido'))
            musica['duration'] = info.get('duration', 0)
            musica['thumbnail'] = info.get('thumbnail', None)
    except Exception as e:
        await ctx.send(embed=discord.Embed(
            title="❌  Erro ao carregar música",
            description=f"```{str(e)[:300]}```",
            color=0xFF4444
        ))
        await tocar_proximo(ctx)
        return

    ffmpeg_opts = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn'
    }

    source = discord.FFmpegPCMAudio(audio_url, **ffmpeg_opts)
    source = discord.PCMVolumeTransformer(source, volume=0.5)

    def after_play(error):
        if error:
            print(f"Erro na reprodução: {error}")
        asyncio.run_coroutine_threadsafe(tocar_proximo(ctx), bot.loop)

    ctx.voice_client.play(source, after=after_play)

    duracao = musica.get('duration', 0)
    mins, secs = divmod(duracao, 60)

    embed = discord.Embed(
        title="🎵  Tocando Agora",
        description=f"**[{musica['title']}]({musica['url']})**",
        color=0x1DB954
    )
    embed.add_field(name="⏱️ Duração", value=f"`{mins:02d}:{secs:02d}`", inline=True)
    embed.add_field(name="👤 Pedido por", value=musica.get('requester', 'Desconhecido'), inline=True)
    embed.add_field(name="📋 Na fila", value=f"{len(get_fila(guild_id))} música(s)", inline=True)
    if musica.get('thumbnail'):
        embed.set_thumbnail(url=musica['thumbnail'])
    embed.set_footer(text="WeAreDevs Bot  •  Música")
    await ctx.send(embed=embed)

# ─────────────────────────────────────────────────────────────
#  Comando: .play
# ─────────────────────────────────────────────────────────────
@bot.command(name="play", aliases=["p"])
async def play(ctx: commands.Context, *, busca: str = None):
    """Toca uma música do YouTube."""

    if not busca:
        return await ctx.reply(embed=discord.Embed(
            title="❌  Sem busca",
            description="Use `.play <nome ou link>`",
            color=0xFF4444
        ))

    if not ctx.author.voice:
        return await ctx.reply(embed=discord.Embed(
            title="❌  Entre em um canal de voz primeiro!",
            color=0xFF4444
        ))

    canal = ctx.author.voice.channel

    if ctx.voice_client is None:
        await canal.connect()
    elif ctx.voice_client.channel != canal:
        await ctx.voice_client.move_to(canal)

    # Busca info da música
    loading = await ctx.reply(embed=discord.Embed(
        title="🔍  Buscando música...",
        description=f"`{busca}`",
        color=0x5865F2
    ))

    try:
        import yt_dlp
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch1',
            'source_address': '0.0.0.0',
            'extract_flat': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(busca if busca.startswith("http") else f"ytsearch1:{busca}", download=False)
            if 'entries' in info:
                info = info['entries'][0]

        musica = {
            'title': info.get('title', busca),
            'url': info.get('webpage_url') or info.get('url') or busca,
            'duration': info.get('duration', 0),
            'thumbnail': info.get('thumbnail', None),
            'requester': ctx.author.display_name
        }

    except Exception as e:
        await loading.edit(embed=discord.Embed(
            title="❌  Erro ao buscar música",
            description=f"```{str(e)[:300]}```",
            color=0xFF4444
        ))
        return

    fila = get_fila(ctx.guild.id)

    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        fila.append(musica)
        duracao = musica.get('duration', 0)
        mins, secs = divmod(duracao, 60)
        embed = discord.Embed(
            title="📋  Adicionado à fila",
            description=f"**{musica['title']}**",
            color=0x5865F2
        )
        embed.add_field(name="⏱️ Duração", value=f"`{mins:02d}:{secs:02d}`", inline=True)
        embed.add_field(name="📍 Posição", value=f"`#{len(fila)}`", inline=True)
        if musica.get('thumbnail'):
            embed.set_thumbnail(url=musica['thumbnail'])
        await loading.edit(embed=embed)
    else:
        fila.appendleft(musica)
        await loading.delete()
        await tocar_proximo(ctx)

# ─────────────────────────────────────────────────────────────
#  Comando: .skip
# ─────────────────────────────────────────────────────────────
@bot.command(name="skip", aliases=["sk"])
async def skip(ctx: commands.Context):
    if not ctx.voice_client or not ctx.voice_client.is_playing():
        return await ctx.reply(embed=discord.Embed(
            title="❌  Nenhuma música tocando",
            color=0xFF4444
        ))
    ctx.voice_client.stop()
    await ctx.reply(embed=discord.Embed(
        title="⏭️  Pulado!",
        color=0x5865F2
    ))

# ─────────────────────────────────────────────────────────────
#  Comando: .stop
# ─────────────────────────────────────────────────────────────
@bot.command(name="stop")
async def stop(ctx: commands.Context):
    if not ctx.voice_client:
        return await ctx.reply(embed=discord.Embed(
            title="❌  Bot não está em nenhum canal",
            color=0xFF4444
        ))
    get_fila(ctx.guild.id).clear()
    tocando.pop(ctx.guild.id, None)
    await ctx.voice_client.disconnect()
    await ctx.reply(embed=discord.Embed(
        title="⏹️  Parado e saí do canal!",
        color=0x5865F2
    ))

# ─────────────────────────────────────────────────────────────
#  Comando: .pause
# ─────────────────────────────────────────────────────────────
@bot.command(name="pause")
async def pause(ctx: commands.Context):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.reply(embed=discord.Embed(title="⏸️  Pausado!", color=0x5865F2))
    else:
        await ctx.reply(embed=discord.Embed(title="❌  Nada tocando", color=0xFF4444))

# ─────────────────────────────────────────────────────────────
#  Comando: .resume
# ─────────────────────────────────────────────────────────────
@bot.command(name="resume", aliases=["r"])
async def resume(ctx: commands.Context):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.reply(embed=discord.Embed(title="▶️  Retomado!", color=0x1DB954))
    else:
        await ctx.reply(embed=discord.Embed(title="❌  Nada pausado", color=0xFF4444))

# ─────────────────────────────────────────────────────────────
#  Comando: .queue
# ─────────────────────────────────────────────────────────────
@bot.command(name="queue", aliases=["q", "fila"])
async def queue(ctx: commands.Context):
    fila = get_fila(ctx.guild.id)
    atual = tocando.get(ctx.guild.id)

    embed = discord.Embed(title="📋  Fila de Músicas", color=0x5865F2)

    if atual:
        embed.add_field(
            name="🎵 Tocando agora",
            value=f"**{atual['title']}** — pedido por {atual.get('requester', '?')}",
            inline=False
        )

    if fila:
        lista = []
        for i, m in enumerate(list(fila)[:10]):
            duracao = m.get('duration', 0)
            mins, secs = divmod(duracao, 60)
            lista.append(f"`{i+1}.` **{m['title']}** `{mins:02d}:{secs:02d}`")
        if len(fila) > 10:
            lista.append(f"*...e mais {len(fila) - 10} músicas*")
        embed.add_field(name="📝 Próximas", value="\n".join(lista), inline=False)
    elif not atual:
        embed.description = "A fila está vazia! Use `.play` para adicionar músicas."

    embed.set_footer(text=f"Total na fila: {len(fila)} música(s)")
    await ctx.reply(embed=embed)

# ─────────────────────────────────────────────────────────────
#  Comando: .volume
# ─────────────────────────────────────────────────────────────
@bot.command(name="volume", aliases=["vol"])
async def volume(ctx: commands.Context, vol: int = None):
    if vol is None:
        atual = int(ctx.voice_client.source.volume * 100) if ctx.voice_client and ctx.voice_client.source else 50
        return await ctx.reply(embed=discord.Embed(
            title=f"🔊  Volume atual: {atual}%",
            color=0x5865F2
        ))
    if not 0 <= vol <= 100:
        return await ctx.reply(embed=discord.Embed(
            title="❌  Volume entre 0 e 100",
            color=0xFF4444
        ))
    if ctx.voice_client and ctx.voice_client.source:
        ctx.voice_client.source.volume = vol / 100
    await ctx.reply(embed=discord.Embed(
        title=f"🔊  Volume ajustado para {vol}%",
        color=0x1DB954
    ))

# ─────────────────────────────────────────────────────────────
#  ══════════════════════════════════════════════════════════
#  COMANDOS DE DEOBFUSCATOR (mantidos do bot original)
#  ══════════════════════════════════════════════════════════
# ─────────────────────────────────────────────────────────────

@bot.command(name="deobf")
async def deobf(ctx: commands.Context):
    if not ctx.message.attachments:
        return await ctx.reply(embed=discord.Embed(
            title="❌  Nenhum arquivo encontrado",
            description="Envie um arquivo `.lua` junto com o comando `.deobf`.",
            color=0xFF4444
        ))

    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith(".lua"):
        return await ctx.reply(embed=discord.Embed(
            title="❌  Formato inválido",
            description="Apenas arquivos **`.lua`** são aceitos.",
            color=0xFF4444
        ))

    loading = await ctx.reply(embed=discord.Embed(
        title="⏳  Analisando script...",
        description="Aguarde enquanto processamos seu arquivo.",
        color=0x5865F2
    ))

    tmp_path = await salvar_anexo(attachment)
    if tmp_path is None:
        return await loading.edit(embed=discord.Embed(
            title="❌  Arquivo muito grande",
            description="O arquivo excede o limite de **500 KB**.",
            color=0xFF4444
        ))

    inicio = time.time()

    try:
        deobfuscator  = Deobfuscator()
        string_result = deobfuscator.analyze_script(tmp_path)
        strings_found = [s for s in string_result.get("decrypted_strings", []) if s and s.strip()]

        scanner        = PatternScanner()
        pattern_result = scanner.analyze_target_file(tmp_path)
        score      = pattern_result.get("total_score_value", 0)
        risco      = pattern_result.get("risk_assessment", "Minimal")
        deteccoes  = pattern_result.get("detection_data", {})

        engine      = ExecutionEngine(max_time=10)
        exec_result = engine.process_script_file(tmp_path)
        exec_det    = exec_result.get("execution_details", {})
        duracao     = time.time() - inicio

    except Exception as e:
        await loading.edit(embed=discord.Embed(
            title="💥  Erro interno",
            description=f"```\n{str(e)[:500]}\n```",
            color=0xFF4444
        ))
        return
    finally:
        try:
            os.remove(tmp_path)
        except:
            pass

    cor   = RISK_COLOR.get(risco, 0x5865F2)
    emoji = RISK_EMOJI.get(risco, "⚪")

    embed = discord.Embed(
        title="🔍  Desobfuscação Concluída",
        description=f"**Arquivo:** `{attachment.filename}`",
        color=cor
    )
    embed.add_field(
        name="📊  Resultado Geral",
        value=(
            f"{emoji} **Nível de risco:** {risco}\n"
            f"🎯 **Score de detecção:** {score}\n"
            f"📦 **Tabelas de dados:** {string_result.get('data_tables_found', 0)}\n"
            f"🔑 **Entradas no mapa cifrado:** {string_result.get('cipher_mapping_size', 0)}\n"
            f"⚙️  **Funções de criptografia:** {string_result.get('encryption_functions', 0)}"
        ),
        inline=False
    )

    if deteccoes:
        linhas = []
        for nome, info in list(deteccoes.items())[:6]:
            nome_fmt = nome.replace("_", " ").title()
            linhas.append(f"• **{nome_fmt}** — {info['match_count']}x  *(score: {info['total_score']})*")
        embed.add_field(name="🔎  Padrões Detectados", value="\n".join(linhas), inline=False)

    sucesso   = exec_det.get("successful", False)
    timed_out = exec_det.get("timed_out", False)
    exec_dur  = exec_det.get("duration", 0)
    output_text = exec_det.get("output_text", "").strip()
    error_text  = exec_det.get("error_text", "").strip()

    if timed_out:
        exec_status = "⏰ Timeout atingido"
    elif sucesso:
        exec_status = "✅ Executado com sucesso"
    else:
        exec_status = "❌ Falhou na execução"

    exec_info = f"{exec_status} em `{exec_dur:.3f}s`"
    if output_text:
        exec_info += f"\n```\n{output_text[:300]}{'...' if len(output_text) > 300 else ''}\n```"
    elif error_text:
        exec_info += f"\n```\n{error_text[:200]}{'...' if len(error_text) > 200 else ''}\n```"
    embed.add_field(name="🖥️  Execução Sandbox", value=exec_info, inline=False)

    if strings_found:
        amostra = strings_found[:8]
        linhas_str = [f"• `{s.replace('`', chr(39))[:60]}{'...' if len(s) > 60 else ''}`" for s in amostra]
        total_str = len(strings_found)
        embed.add_field(
            name=f"📝  Strings Extraídas ({total_str})",
            value="\n".join(linhas_str) + (f"\n*...e mais {total_str - 8} strings*" if total_str > 8 else ""),
            inline=False
        )
    else:
        embed.add_field(name="📝  Strings Extraídas", value="*Nenhuma string encontrada*", inline=False)

    embed.set_footer(text=f"WeAreDevs Deobfuscator  •  Análise concluída em {duracao:.2f}s")

    # Gera arquivo desobfuscado
    nome_saida = attachment.filename.replace(".lua", "_deobf.lua")
    linhas_out = [
        "-- ══════════════════════════════════════════",
        f"-- Desobfuscado por Deobf Bot",
        f"-- Arquivo original: {attachment.filename}",
        f"-- Nível de risco: {risco} | Score: {score}",
        "-- ══════════════════════════════════════════",
        ""
    ]
    if strings_found:
        linhas_out.append("-- ── Strings Extraídas ──────────────────────")
        for i, s in enumerate(strings_found):
            linhas_out.append(f"-- [{i+1}] {s.replace(chr(10), chr(92)+'n').replace(chr(13), '')}")
        linhas_out.append("")
    if output_text:
        linhas_out.append("-- ── Output da Execução Sandbox ─────────────")
        for linha in output_text.splitlines():
            linhas_out.append(f"-- {linha}")
        linhas_out.append("")
    linhas_out.append("-- ── Padrões Detectados ─────────────────────")
    for nome_p, info in deteccoes.items():
        linhas_out.append(f"-- {nome_p.replace('_', ' ').title()}: {info['match_count']}x")

    arquivo_saida = discord.File(
        fp=io.BytesIO("\n".join(linhas_out).encode("utf-8")),
        filename=nome_saida
    )

    await loading.edit(embed=embed)
    await ctx.send(content=f"📄 **Arquivo desobfuscado:** `{nome_saida}`", file=arquivo_saida)


@bot.command(name="s")
async def scan(ctx: commands.Context):
    if not ctx.message.attachments:
        return await ctx.reply(embed=discord.Embed(
            title="❌  Nenhum arquivo encontrado",
            description="Envie um arquivo `.lua` junto com o comando `.s`.",
            color=0xFF4444
        ))

    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith(".lua"):
        return await ctx.reply(embed=discord.Embed(title="❌  Formato inválido", description="Apenas **`.lua`** aceitos.", color=0xFF4444))

    loading = await ctx.reply(embed=discord.Embed(title="🔎  Escaneando padrões...", color=0x5865F2))

    tmp_path = await salvar_anexo(attachment)
    if tmp_path is None:
        return await loading.edit(embed=discord.Embed(title="❌  Arquivo muito grande", color=0xFF4444))

    inicio = time.time()
    try:
        scanner        = PatternScanner()
        pattern_result = scanner.analyze_target_file(tmp_path)
        score     = pattern_result.get("total_score_value", 0)
        risco     = pattern_result.get("risk_assessment", "Minimal")
        deteccoes = pattern_result.get("detection_data", {})
        tamanho   = pattern_result.get("content_size", 0)
        duracao   = time.time() - inicio
    except Exception as e:
        return await loading.edit(embed=discord.Embed(title="💥  Erro", description=f"```{str(e)[:300]}```", color=0xFF4444))
    finally:
        try: os.remove(tmp_path)
        except: pass

    cor   = RISK_COLOR.get(risco, 0x5865F2)
    emoji = RISK_EMOJI.get(risco, "⚪")
    embed = discord.Embed(title="🛡️  Scan de Padrões", description=f"**Arquivo:** `{attachment.filename}`", color=cor)
    embed.add_field(name="📊  Resumo", value=f"{emoji} **Risco:** {risco}\n🎯 **Score:** {score}\n📏 **Tamanho:** {tamanho:,} chars", inline=False)

    if deteccoes:
        linhas = []
        for nome, info in deteccoes.items():
            barra = "█" * min(info['match_count'], 10) + "░" * (10 - min(info['match_count'], 10))
            linhas.append(f"`{barra}` **{nome.replace('_', ' ').title()}** — {info['match_count']}x")
        embed.add_field(name="🔎  Detecções", value="\n".join(linhas[:10]), inline=False)
    else:
        embed.add_field(name="🔎  Detecções", value="✅ Nenhum padrão suspeito.", inline=False)

    embed.set_footer(text=f"WeAreDevs Deobfuscator  •  Scan concluído em {duracao:.2f}s")
    await loading.edit(embed=embed)


@bot.command(name="ajuda")
async def ajuda(ctx: commands.Context):
    embed = discord.Embed(title="📖  Comandos Disponíveis", color=0x5865F2)
    embed.add_field(name="🔍  Desobfuscator", value=(
        "`.deobf` + arquivo.lua — Análise completa\n"
        "`.s` + arquivo.lua — Scan rápido de padrões"
    ), inline=False)
    embed.add_field(name="🎵  Música", value=(
        "`.play <nome/link>` — Toca música do YouTube\n"
        "`.skip` — Pula a música atual\n"
        "`.stop` — Para e sai do canal\n"
        "`.pause` / `.resume` — Pausa/retoma\n"
        "`.queue` — Mostra a fila\n"
        "`.volume <0-100>` — Ajusta o volume"
    ), inline=False)
    embed.add_field(name="ℹ️  Geral", value="`.ajuda` — Mostra esta mensagem", inline=False)
    embed.set_footer(text="WeAreDevs Bot")
    await ctx.reply(embed=embed)


bot.run(TOKEN)
