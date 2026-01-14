import discord
import os
from dotenv import load_dotenv
import datetime
import re

load_dotenv()
TOKEN = os.getenv('TOKEN')

# Configurações do servidor e canais
GUILD_ID = 1313305951004135434  # Servidor alvo
LOG_CHANNEL_ID = 1460097551293218925  # Canal onde as logs são enviadas
APP_BOT_ID = 1460097576647790595  # ID do APP que envia as logs
ALERT_CHANNEL_ID = 1461066823687602392  # Canal para enviar alertas

# Configurações de detecção
TIME_WINDOW_SECONDS = 60  # Janela de tempo em segundos
LOG_COUNT_THRESHOLD = 3   # Número de logs para disparar o alerta

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

client = discord.Client(intents=intents)

# --- MEMÓRIA DO BOT ---
log_history = {}  # Formato: {license_acao: [(timestamp, log_info), ...]}
alerted_keys = {}  # Chaves (license+acao) que já dispararam alerta

def extrair_info_jogador(texto):
    """
    Extrai informações do jogador da mensagem de log.
    Retorna: (nome_jogador, license, log_completo) ou None se não encontrar
    
    Formatos esperados:
    - "O jogador JPZIN (license:1b0779c03eb4dd2f7ae1e2e74522aaa49069bf37, 275) colocou..."
    - "O jogador lucaspirespsn (license:4125f3186251695bc985402d3a0409fc3781aa48, 40) pegou..."
    """
    # Regex para capturar: nome do jogador, license e ID
    pattern = r'O jogador (\S+) \(license:([a-f0-9]+), (\d+)\)'
    match = re.search(pattern, texto)
    
    if match:
        nome_jogador = match.group(1)
        license = match.group(2)
        player_id = match.group(3)
        return (nome_jogador, license, player_id, texto)
    
    return None

def eh_log_porta_malas_ou_luvas(texto):
    """
    Verifica se a mensagem é uma log de porta-malas ou porta-luvas.
    """
    texto_lower = texto.lower()
    return ('porta-malas' in texto_lower or 'porta-luvas' in texto_lower) and 'o jogador' in texto_lower

def extrair_tipo_acao(texto):
    """
    Extrai o tipo de ação da log (Colocou ou Pegou).
    Retorna: 'colocou', 'pegou' ou None
    """
    texto_lower = texto.lower()
    if 'colocou' in texto_lower:
        return 'colocou'
    elif 'pegou' in texto_lower:
        return 'pegou'
    return None

def extrair_local_acao(texto):
    """
    Extrai o local da ação (porta-malas ou porta-luvas).
    """
    texto_lower = texto.lower()
    if 'porta-malas' in texto_lower:
        return 'porta-malas'
    elif 'porta-luvas' in texto_lower:
        return 'porta-luvas'
    return 'desconhecido'

@client.event
async def on_ready():
    print(f'🔍 Bot Verificador de Logs conectado como {client.user}')
    print(f'🎯 Servidor alvo: {GUILD_ID}')
    print(f'📥 Canal de logs monitorado: {LOG_CHANNEL_ID}')
    print(f'🤖 APP monitorado: {APP_BOT_ID}')
    print(f'📢 Canal de alertas: {ALERT_CHANNEL_ID}')
    print(f'⏰ Janela de tempo: {TIME_WINDOW_SECONDS}s | Limite: {LOG_COUNT_THRESHOLD} logs')
    print(f'✅ Bot online e monitorando logs de porta-malas/porta-luvas...')

@client.event
async def on_message(message):
    # Verificar se a mensagem é do canal correto e do APP correto
    if message.channel.id != LOG_CHANNEL_ID:
        return
    
    if message.author.id != APP_BOT_ID:
        return
    
    # Capturar texto da mensagem (pode estar em content ou embeds)
    texto_completo = message.content or ""
    
    # Também verificar embeds
    if message.embeds:
        for embed in message.embeds:
            if embed.title:
                texto_completo += " " + embed.title
            if embed.description:
                texto_completo += " " + embed.description
    
    # Mostrar timestamp
    agora = datetime.datetime.now().strftime("%H:%M:%S")
    
    # Mostrar log recebida (primeira linha ou primeiros 80 caracteres)
    preview = texto_completo.split('\n')[0][:80] if texto_completo else "(vazio)"
    print(f"[{agora}] 📨 Log recebida: {preview}")
    
    # Verificar se é uma log de porta-malas ou porta-luvas
    if not eh_log_porta_malas_ou_luvas(texto_completo):
        print(f"[{agora}] ⏭️ Ignorada (não é porta-malas/porta-luvas)")
        return
    
    # Extrair informações do jogador
    info = extrair_info_jogador(texto_completo)
    if not info:
        print(f"[{agora}] ❌ Não conseguiu extrair jogador da log")
        return
    
    nome_jogador, license, player_id, log_texto = info
    now = datetime.datetime.now()
    
    # Extrair tipo de ação (colocou/pegou) e local (porta-malas/porta-luvas)
    tipo_acao = extrair_tipo_acao(texto_completo)
    local_acao = extrair_local_acao(texto_completo)
    
    if not tipo_acao:
        print(f"[{agora}] ❌ Não conseguiu identificar ação (colocou/pegou)")
        return
    
    # Chave única: license + tipo de ação + local
    chave = f"{license}_{tipo_acao}_{local_acao}"
    
    print(f"[{agora}] ✅ VÁLIDA - Jogador: {nome_jogador} | Ação: {tipo_acao.upper()} | Local: {local_acao}")
    
    # Limpeza do histórico antigo
    for key in list(log_history.keys()):
        entries = log_history[key]
        valid_entries = [(ts, log) for ts, log in entries if (now - ts).total_seconds() < TIME_WINDOW_SECONDS]
        if not valid_entries:
            del log_history[key]
        else:
            log_history[key] = valid_entries
    
    # Limpeza das chaves já alertadas
    for key in list(alerted_keys.keys()):
        if (now - alerted_keys[key]).total_seconds() >= TIME_WINDOW_SECONDS:
            del alerted_keys[key]
    
    # Verificar se esta combinação já disparou alerta recentemente
    if chave in alerted_keys:
        print(f"[{agora}] ⚠️ Jogador {nome_jogador} ({tipo_acao}) já foi alertado recentemente, ignorando...")
        return
    
    # Adicionar ao histórico
    if chave not in log_history:
        log_history[chave] = []
    log_history[chave].append((now, log_texto))
    
    log_count = len(log_history[chave])
    
    print(f"[{agora}] 📊 Contagem para {nome_jogador} ({tipo_acao.upper()} {local_acao}): {log_count}/{LOG_COUNT_THRESHOLD}")
    
    # Verificar se atingiu o limite
    if log_count >= LOG_COUNT_THRESHOLD:
        print(f"[{agora}] 🚨 ALERTA DISPARADO para jogador: {nome_jogador} ({tipo_acao.upper()} {local_acao})")
        
        # Marcar como já alertado
        alerted_keys[chave] = now
        
        # Montar mensagem de alerta
        logs_resumo = []
        for i, (ts, log) in enumerate(log_history[chave][-LOG_COUNT_THRESHOLD:], 1):
            # Extrair primeira linha (tipo de ação)
            primeira_linha = log.split('\n')[0] if '\n' in log else log[:50]
            logs_resumo.append(f"**{i}.** {primeira_linha}")
        
        acao_texto = "COLOCOU" if tipo_acao == "colocou" else "PEGOU"
        
        alert_message = (
            f"@everyone\n"
            f"🚨 **ALERTA DE ATIVIDADE SUSPEITA DETECTADA!** 🚨\n\n"
            f"👤 **Jogador:** {nome_jogador}\n"
            f"🔑 **License:** `{license}`\n"
            f"🆔 **ID no Servidor:** {player_id}\n"
            f"📦 **Ação:** {acao_texto} no {local_acao.upper()}\n"
            f"⏱️ **{LOG_COUNT_THRESHOLD}x a mesma ação em menos de {TIME_WINDOW_SECONDS} segundos!**\n\n"
            f"📋 **Logs detectados:**\n" + "\n".join(logs_resumo) + "\n\n"
            f"⚠️ **Verifique este jogador imediatamente!**"
        )
        
        # Enviar alerta
        try:
            alert_channel = client.get_channel(ALERT_CHANNEL_ID)
            if alert_channel:
                await alert_channel.send(alert_message)
                print(f"✅ Alerta enviado para canal: {ALERT_CHANNEL_ID}")
            else:
                print(f"❌ Canal de alerta não encontrado: {ALERT_CHANNEL_ID}")
        except Exception as e:
            print(f"❌ ERRO ao enviar alerta: {e}")
        
        # Limpar histórico desta chave após enviar alerta
        if chave in log_history:
            del log_history[chave]

if TOKEN:
    client.run(TOKEN)
else:
    print("❌ TOKEN não encontrado! Verifique o arquivo .env")
