import discord
from discord.ext import commands
import os
import tempfile
import sys
import time

# ─────────────────────────────────────────────────────────────
#  Importa os módulos do deobfuscator
#  (coloque todos os arquivos na mesma pasta que este bot.py)
# ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

try:
    from decryptor_main import Deobfuscator
    from pattern_scanner import PatternScanner
    from execution_engine import ExecutionEngine
except ImportError as e:
    print(f"[ERRO] Módulo não encontrado: {e}")
    print("Certifique-se que decryptor_main.py, pattern_scanner.py e execution_engine.py estão na mesma pasta.")
    exit(1)

# ─────────────────────────────────────────────────────────────
#  Configuração do bot
# ─────────────────────────────────────────────────────────────
TOKEN       = os.environ.get("TOKEN")
PREFIX      = "."
MAX_SIZE    = 500_000   # 500 KB

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ─────────────────────────────────────────────────────────────
#  Cores dos embeds por nível de risco
# ─────────────────────────────────────────────────────────────
RISK_COLOR = {
    "High":    0xFF4444,
    "Medium":  0xFF8C00,
    "Low":     0xFFD700,
    "Minimal": 0x00C851,
}

RISK_EMOJI = {
    "High":    "🔴",
    "Medium":  "🟠",
    "Low":     "🟡",
    "Minimal": "🟢",
}

# ─────────────────────────────────────────────────────────────
#  Evento: bot online
# ─────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=".deobf | .s"
        )
    )
    print(f"✅  Bot online como {bot.user} | Prefixo: {PREFIX}")


# ─────────────────────────────────────────────────────────────
#  Helper: salvar anexo em arquivo temporário
# ─────────────────────────────────────────────────────────────
async def salvar_anexo(attachment) -> str | None:
    """Baixa o anexo e salva num arquivo .lua temporário. Retorna o caminho."""
    if attachment.size > MAX_SIZE:
        return None
    data = await attachment.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".lua", mode="wb")
    tmp.write(data)
    tmp.close()
    return tmp.name


# ─────────────────────────────────────────────────────────────
#  Comando: .deobf
#  Faz a análise completa: strings + padrões + execução
# ─────────────────────────────────────────────────────────────
@bot.command(name="deobf")
async def deobf(ctx: commands.Context):
    """Desobfusca um script Lua enviado como anexo."""

    # ── Verificações básicas ────────────────────────────────
    if not ctx.message.attachments:
        embed = discord.Embed(
            title="❌  Nenhum arquivo encontrado",
            description="Envie um arquivo `.lua` junto com o comando `.deobf`.",
            color=0xFF4444
        )
        embed.set_footer(text="Exemplo: .deobf  +  arquivo.lua")
        return await ctx.reply(embed=embed)

    attachment = ctx.message.attachments[0]

    if not attachment.filename.endswith(".lua"):
        embed = discord.Embed(
            title="❌  Formato inválido",
            description="Apenas arquivos **`.lua`** são aceitos.",
            color=0xFF4444
        )
        return await ctx.reply(embed=embed)

    # ── Loading ─────────────────────────────────────────────
    loading = await ctx.reply(
        embed=discord.Embed(
            title="⏳  Analisando script...",
            description="Aguarde enquanto processamos seu arquivo.",
            color=0x5865F2
        )
    )

    tmp_path = await salvar_anexo(attachment)
    if tmp_path is None:
        await loading.edit(embed=discord.Embed(
            title="❌  Arquivo muito grande",
            description=f"O arquivo excede o limite de **500 KB**.",
            color=0xFF4444
        ))
        return

    inicio = time.time()

    try:
        # ── 1. Strings ───────────────────────────────────────
        deobfuscator  = Deobfuscator()
        string_result = deobfuscator.analyze_script(tmp_path)

        strings_found = string_result.get("decrypted_strings", [])
        strings_found = [s for s in strings_found if s and s.strip()]

        # ── 2. Padrões ───────────────────────────────────────
        scanner        = PatternScanner()
        pattern_result = scanner.analyze_target_file(tmp_path)

        score      = pattern_result.get("total_score_value", 0)
        risco      = pattern_result.get("risk_assessment", "Minimal")
        deteccoes  = pattern_result.get("detection_data", {})

        # ── 3. Execução ──────────────────────────────────────
        engine     = ExecutionEngine(max_time=10)
        exec_result = engine.process_script_file(tmp_path)
        exec_det   = exec_result.get("execution_details", {})

        duracao = time.time() - inicio

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

    # ── Monta o embed principal ─────────────────────────────
    cor   = RISK_COLOR.get(risco, 0x5865F2)
    emoji = RISK_EMOJI.get(risco, "⚪")

    embed = discord.Embed(
        title=f"🔍  Desobfuscação Concluída",
        description=f"**Arquivo:** `{attachment.filename}`",
        color=cor
    )

    # Cabeçalho de risco
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

    # Padrões detectados
    if deteccoes:
        linhas = []
        for nome, info in list(deteccoes.items())[:6]:
            nome_fmt = nome.replace("_", " ").title()
            linhas.append(f"• **{nome_fmt}** — {info['match_count']}x  *(score: {info['total_score']})*")
        embed.add_field(
            name="🔎  Padrões Detectados",
            value="\n".join(linhas) or "*Nenhum*",
            inline=False
        )

    # Execução
    sucesso    = exec_det.get("successful", False)
    timed_out  = exec_det.get("timed_out", False)
    exec_dur   = exec_det.get("duration", 0)

    if timed_out:
        exec_status = "⏰ Timeout atingido"
    elif sucesso:
        exec_status = "✅ Executado com sucesso"
    else:
        exec_status = "❌ Falhou na execução"

    output_text = exec_det.get("output_text", "").strip()
    error_text  = exec_det.get("error_text", "").strip()

    exec_info = f"{exec_status} em `{exec_dur:.3f}s`"
    if output_text:
        preview = output_text[:300] + ("..." if len(output_text) > 300 else "")
        exec_info += f"\n```\n{preview}\n```"
    elif error_text:
        preview = error_text[:200] + ("..." if len(error_text) > 200 else "")
        exec_info += f"\n```\n{preview}\n```"

    embed.add_field(name="🖥️  Execução Sandbox", value=exec_info, inline=False)

    # Strings descriptografadas
    if strings_found:
        amostra = strings_found[:8]
        linhas_str = []
        for s in amostra:
            s_clean = s.replace("`", "'")
            preview = s_clean[:60] + ("..." if len(s_clean) > 60 else "")
            linhas_str.append(f"• `{preview}`")

        total_str = len(strings_found)
        footer_str = f"\n*...e mais {total_str - 8} strings*" if total_str > 8 else ""

        embed.add_field(
            name=f"📝  Strings Extraídas ({total_str})",
            value="\n".join(linhas_str) + footer_str,
            inline=False
        )
    else:
        embed.add_field(
            name="📝  Strings Extraídas",
            value="*Nenhuma string encontrada*",
            inline=False
        )

    embed.set_footer(text=f"WeAreDevs Deobfuscator  •  Análise concluída em {duracao:.2f}s")

    await loading.edit(embed=embed)


# ─────────────────────────────────────────────────────────────
#  Comando: .s
#  Apenas scan de padrões (rápido, sem execução)
# ─────────────────────────────────────────────────────────────
@bot.command(name="s")
async def scan(ctx: commands.Context):
    """Escaneia padrões suspeitos em um script Lua."""

    if not ctx.message.attachments:
        embed = discord.Embed(
            title="❌  Nenhum arquivo encontrado",
            description="Envie um arquivo `.lua` junto com o comando `.s`.",
            color=0xFF4444
        )
        embed.set_footer(text="Exemplo: .s  +  arquivo.lua")
        return await ctx.reply(embed=embed)

    attachment = ctx.message.attachments[0]

    if not attachment.filename.endswith(".lua"):
        embed = discord.Embed(
            title="❌  Formato inválido",
            description="Apenas arquivos **`.lua`** são aceitos.",
            color=0xFF4444
        )
        return await ctx.reply(embed=embed)

    loading = await ctx.reply(
        embed=discord.Embed(
            title="🔎  Escaneando padrões...",
            description="Aguarde um momento.",
            color=0x5865F2
        )
    )

    tmp_path = await salvar_anexo(attachment)
    if tmp_path is None:
        await loading.edit(embed=discord.Embed(
            title="❌  Arquivo muito grande",
            description="O arquivo excede o limite de **500 KB**.",
            color=0xFF4444
        ))
        return

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
        await loading.edit(embed=discord.Embed(
            title="💥  Erro ao escanear",
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
        title="🛡️  Scan de Padrões",
        description=f"**Arquivo:** `{attachment.filename}`",
        color=cor
    )

    embed.add_field(
        name="📊  Resumo",
        value=(
            f"{emoji} **Nível de risco:** {risco}\n"
            f"🎯 **Score total:** {score}\n"
            f"📏 **Tamanho:** {tamanho:,} caracteres"
        ),
        inline=False
    )

    if deteccoes:
        linhas = []
        for nome, info in deteccoes.items():
            nome_fmt = nome.replace("_", " ").title()
            barra    = "█" * min(info['match_count'], 10) + "░" * (10 - min(info['match_count'], 10))
            linhas.append(f"`{barra}` **{nome_fmt}** — {info['match_count']}x")

        embed.add_field(
            name="🔎  Detecções",
            value="\n".join(linhas[:10]),
            inline=False
        )
    else:
        embed.add_field(
            name="🔎  Detecções",
            value="✅ Nenhum padrão suspeito encontrado.",
            inline=False
        )

    embed.set_footer(text=f"WeAreDevs Deobfuscator  •  Scan concluído em {duracao:.2f}s")
    await loading.edit(embed=embed)


# ─────────────────────────────────────────────────────────────
#  Comando: .help (personalizado)
# ─────────────────────────────────────────────────────────────
@bot.command(name="ajuda")
async def ajuda(ctx: commands.Context):
    embed = discord.Embed(
        title="📖  Comandos Disponíveis",
        description="Bot de desobfuscação de scripts Lua.",
        color=0x5865F2
    )
    embed.add_field(
        name="`.deobf` + arquivo.lua",
        value="Faz a análise **completa**: extrai strings, escaneia padrões e executa em sandbox.",
        inline=False
    )
    embed.add_field(
        name="`.s` + arquivo.lua",
        value="Scan **rápido** de padrões suspeitos, sem executar o script.",
        inline=False
    )
    embed.add_field(
        name="`.ajuda`",
        value="Mostra esta mensagem.",
        inline=False
    )
    embed.set_footer(text="WeAreDevs Deobfuscator")
    await ctx.reply(embed=embed)


# ─────────────────────────────────────────────────────────────
#  Inicia o bot
# ─────────────────────────────────────────────────────────────
bot.run(TOKEN)
