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
log_history = {}  # Formato: {license: [(timestamp, log_info), ...]}
alerted_licenses = {}  # Licenças que já dispararam alerta

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
    
    # Verificar se é uma log de porta-malas ou porta-luvas
    if not eh_log_porta_malas_ou_luvas(texto_completo):
        return
    
    # Extrair informações do jogador
    info = extrair_info_jogador(texto_completo)
    if not info:
        return
    
    nome_jogador, license, player_id, log_texto = info
    now = datetime.datetime.now()
    
    print(f"📋 Log detectado - Jogador: {nome_jogador} | License: {license[:10]}... | ID: {player_id}")
    
    # Limpeza do histórico antigo
    for key in list(log_history.keys()):
        entries = log_history[key]
        valid_entries = [(ts, log) for ts, log in entries if (now - ts).total_seconds() < TIME_WINDOW_SECONDS]
        if not valid_entries:
            del log_history[key]
        else:
            log_history[key] = valid_entries
    
    # Limpeza das licenças já alertadas
    for key in list(alerted_licenses.keys()):
        if (now - alerted_licenses[key]).total_seconds() >= TIME_WINDOW_SECONDS:
            del alerted_licenses[key]
    
    # Verificar se este jogador já disparou alerta recentemente
    if license in alerted_licenses:
        print(f"⏭️ Jogador {nome_jogador} já foi alertado recentemente, ignorando...")
        return
    
    # Adicionar ao histórico
    if license not in log_history:
        log_history[license] = []
    log_history[license].append((now, log_texto))
    
    log_count = len(log_history[license])
    
    print(f"📊 Contagem para {nome_jogador}: {log_count}/{LOG_COUNT_THRESHOLD}")
    
    # Verificar se atingiu o limite
    if log_count >= LOG_COUNT_THRESHOLD:
        print(f"🚨 ALERTA DISPARADO para jogador: {nome_jogador} (License: {license})")
        
        # Marcar como já alertado
        alerted_licenses[license] = now
        
        # Montar mensagem de alerta
        logs_resumo = []
        for i, (ts, log) in enumerate(log_history[license][-LOG_COUNT_THRESHOLD:], 1):
            # Extrair primeira linha (tipo de ação)
            primeira_linha = log.split('\n')[0] if '\n' in log else log[:50]
            logs_resumo.append(f"**{i}.** {primeira_linha}")
        
        alert_message = (
            f"@everyone\n"
            f"🚨 **ALERTA DE ATIVIDADE SUSPEITA DETECTADA!** 🚨\n\n"
            f"👤 **Jogador:** {nome_jogador}\n"
            f"🔑 **License:** `{license}`\n"
            f"🆔 **ID no Servidor:** {player_id}\n"
            f"⏱️ **{LOG_COUNT_THRESHOLD} logs em menos de {TIME_WINDOW_SECONDS} segundos!**\n\n"
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
        
        # Limpar histórico deste jogador após enviar alerta
        if license in log_history:
            del log_history[license]

if TOKEN:
    client.run(TOKEN)
else:
    print("❌ TOKEN não encontrado! Verifique o arquivo .env")
