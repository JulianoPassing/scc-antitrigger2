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
alerted_keys = {}  # Chaves (license+acao) que já dispararam alerta: {chave: {timestamp, count}}

# --- MEMÓRIA PARA TRANSFERÊNCIAS ---
# Formato: {veiculo_id: {timestamp, jogador, license, player_id, item, quantidade, local}}
depositos_veiculos = {}
alerted_transfers = {}  # Transferências já alertadas

def extrair_info_jogador(texto):
    """
    Extrai informações do jogador da mensagem de log.
    Retorna: (nome_jogador, license, log_completo) ou None se não encontrar
    
    Formatos esperados:
    - "O jogador JPZIN (license:1b0779c03eb4dd2f7ae1e2e74522aaa49069bf37, 275) colocou..."
    - "O jogador **Jeeh** (license:...) pegou..." (com markdown)
    """
    # Remover markdown ** do texto para facilitar o parsing
    texto_limpo = texto.replace('**', '')
    
    # Regex para capturar: nome do jogador (pode ter espaços), license e ID
    # Usa .+? para capturar tudo até encontrar (license:
    pattern = r'O jogador (.+?) \(license:([a-f0-9]+), (\d+)\)'
    match = re.search(pattern, texto_limpo)
    
    if match:
        nome_jogador = match.group(1)
        license = match.group(2)
        player_id = match.group(3)
        return (nome_jogador, license, player_id, texto_limpo)
    
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

def extrair_item_e_quantidade(texto):
    """
    Extrai o item e a quantidade da log.
    Exemplo: "colocou money x200" -> "money x200"
    Exemplo com markdown: "**money** x**200**" -> "money x200"
    Retorna a string completa "item xValor"
    """
    # Remover markdown ** do texto
    texto_limpo = texto.replace('**', '')
    
    # Regex para capturar: qualquer palavra seguida de x e números
    # Exemplos: money x200, black_money x90610, dirty_money x1000
    pattern = r'(\w+)\s+x(\d+)'
    match = re.search(pattern, texto_limpo)
    
    if match:
        item = match.group(1)
        quantidade = match.group(2)
        # Ignorar palavras comuns que não são itens
        palavras_ignorar = ['jogador', 'veiculo', 'veículo', 'coordenadas', 'license', 'trunk', 'glove']
        if item.lower() not in palavras_ignorar:
            return f"{item} x{quantidade}"
    
    return "?"

def extrair_veiculo_id(texto):
    """
    Extrai o ID do veículo da log.
    Exemplo: "do veículo glove02G0F98W" -> "glove02G0F98W"
    Exemplo: "do veículo trunkUQKI3439" -> "trunkUQKI3439"
    """
    # Regex para capturar: glove ou trunk seguido do ID (com ou sem acento em veículo)
    patterns = [
        r'veículo\s+((?:glove|trunk)[A-Za-z0-9]+)',  # com acento
        r'veiculo\s+((?:glove|trunk)[A-Za-z0-9]+)',  # sem acento
        r'(glove[A-Za-z0-9]+)',  # só glove + ID
        r'(trunk[A-Za-z0-9]+)',  # só trunk + ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, texto)
        if match:
            return match.group(1)
    
    return None

def extrair_tipo_veiculo(veiculo_id):
    """
    Retorna se é glove (porta-luvas) ou trunk (porta-malas).
    """
    if veiculo_id:
        if veiculo_id.startswith('glove'):
            return 'PORTA-LUVAS'
        elif veiculo_id.startswith('trunk'):
            return 'PORTA-MALAS'
    return 'DESCONHECIDO'

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
    
    # Extrair item e quantidade (retorna string como "money x200")
    item_quantidade = extrair_item_e_quantidade(texto_completo)
    
    # Debug: mostrar sempre o que foi extraído
    print(f"[{agora}] 🔍 DEBUG - Item/Qtd extraído: '{item_quantidade}'")
    
    # Debug: se não encontrou quantidade, mostrar parte do texto
    if item_quantidade == "?":
        print(f"[{agora}] ⚠️ DEBUG - Texto completo: {repr(texto_completo[:300])}")
    
    if not tipo_acao:
        print(f"[{agora}] ❌ Não conseguiu identificar ação (colocou/pegou)")
        return
    
    # Chave única: license + tipo de ação + local (NÃO inclui valor, então conta independente do valor)
    chave = f"{license}_{tipo_acao}_{local_acao}"
    
    # Extrair ID do veículo
    veiculo_id = extrair_veiculo_id(texto_completo)
    tipo_veiculo = extrair_tipo_veiculo(veiculo_id)
    
    # Debug: se não encontrou veículo, mostrar aviso
    if not veiculo_id:
        print(f"[{agora}] ⚠️ DEBUG - Não encontrou veículo no texto")
    
    print(f"[{agora}] ✅ VÁLIDA - Jogador: {nome_jogador} | Ação: {tipo_acao.upper()} | Local: {local_acao} | {item_quantidade} | Veículo: {veiculo_id or '?'}")
    
    # ========== SISTEMA DE DETECÇÃO DE TRANSFERÊNCIAS ==========
    if veiculo_id:
        # Limpar depósitos antigos (mais de 60 segundos)
        for vid in list(depositos_veiculos.keys()):
            if (now - depositos_veiculos[vid]['timestamp']).total_seconds() >= TIME_WINDOW_SECONDS:
                del depositos_veiculos[vid]
        
        # Limpar alertas de transferência antigos
        for key in list(alerted_transfers.keys()):
            if (now - alerted_transfers[key]).total_seconds() >= TIME_WINDOW_SECONDS:
                del alerted_transfers[key]
        
        if tipo_acao == 'colocou':
            # Registrar depósito no veículo
            depositos_veiculos[veiculo_id] = {
                'timestamp': now,
                'jogador': nome_jogador,
                'license': license,
                'player_id': player_id,
                'item_quantidade': item_quantidade,
                'local': local_acao
            }
            print(f"[{agora}] 💾 Depósito registrado no veículo {veiculo_id}")
        
        elif tipo_acao == 'pegou':
            # Verificar se existe depósito recente de OUTRO jogador neste veículo
            if veiculo_id in depositos_veiculos:
                deposito = depositos_veiculos[veiculo_id]
                
                # Verificar se é outro jogador
                if deposito['license'] != license:
                    # Chave única para evitar alertas duplicados
                    transfer_key = f"{veiculo_id}_{deposito['license']}_{license}"
                    
                    if transfer_key not in alerted_transfers:
                        print(f"[{agora}] 🔄 TRANSFERÊNCIA DETECTADA no veículo {veiculo_id}!")
                        
                        # Marcar como alertado
                        alerted_transfers[transfer_key] = now
                        
                        # Montar embed de alerta de transferência (VERDE)
                        transfer_embed = discord.Embed(
                            title="🔄 TRANSFERÊNCIA SUSPEITA DETECTADA! 🔄",
                            color=0x00FF00  # Verde
                        )
                        transfer_embed.add_field(
                            name="📥 DEPÓSITO",
                            value=(
                                f"👤 **Jogador:** {deposito['jogador']}\n"
                                f"🔑 **License:** `{deposito['license']}`\n"
                                f"🆔 **ID:** {deposito['player_id']}\n"
                                f"💰 **Colocou:** {deposito['item_quantidade']}"
                            ),
                            inline=False
                        )
                        transfer_embed.add_field(
                            name="📤 RETIRADA",
                            value=(
                                f"👤 **Jogador:** {nome_jogador}\n"
                                f"🔑 **License:** `{license}`\n"
                                f"🆔 **ID:** {player_id}\n"
                                f"💰 **Pegou:** {item_quantidade}"
                            ),
                            inline=False
                        )
                        transfer_embed.add_field(
                            name="🚗 VEÍCULO",
                            value=f"`{veiculo_id}` ({tipo_veiculo})",
                            inline=True
                        )
                        transfer_embed.add_field(
                            name="⏱️ TEMPO",
                            value=f"Menos de {TIME_WINDOW_SECONDS} segundos",
                            inline=True
                        )
                        transfer_embed.set_footer(text="⚠️ Possível transferência de itens entre jogadores!")
                        
                        # Enviar alerta de transferência
                        try:
                            alert_channel = client.get_channel(ALERT_CHANNEL_ID)
                            if alert_channel:
                                await alert_channel.send(content="@everyone", embed=transfer_embed)
                                print(f"[{agora}] ✅ Alerta de TRANSFERÊNCIA enviado!")
                            else:
                                print(f"[{agora}] ❌ Canal de alerta não encontrado")
                        except Exception as e:
                            print(f"[{agora}] ❌ ERRO ao enviar alerta de transferência: {e}")
                        
                        # Remover o depósito após alertar
                        del depositos_veiculos[veiculo_id]
    
    # ========== SISTEMA DE DETECÇÃO DE SPAM (3x mesma ação) ==========
    
    # Limpeza do histórico antigo (cada entrada tem 3 elementos: ts, linha, qtd)
    for key in list(log_history.keys()):
        entries = log_history[key]
        valid_entries = [entry for entry in entries if (now - entry[0]).total_seconds() < TIME_WINDOW_SECONDS]
        if not valid_entries:
            del log_history[key]
        else:
            log_history[key] = valid_entries
    
    # Limpeza das chaves já alertadas (mantém histórico de alertas, mas limpa após 5 minutos)
    for key in list(alerted_keys.keys()):
        if (now - alerted_keys[key]['timestamp']).total_seconds() >= 300:  # 5 minutos
            del alerted_keys[key]
    
    # Adicionar ao histórico (salva timestamp, primeira linha e item_quantidade)
    if chave not in log_history:
        log_history[chave] = []
    
    # Extrair primeira linha para o resumo
    primeira_linha = log_texto.split('\n')[0] if '\n' in log_texto else log_texto[:60]
    log_history[chave].append((now, primeira_linha, item_quantidade))
    
    log_count = len(log_history[chave])
    
    # Mostrar valores diferentes se houver
    valores_unicos = set()
    for _, _, qtd in log_history[chave]:
        if qtd != "?":
            valores_unicos.add(qtd)
    
    if len(valores_unicos) > 1:
        print(f"[{agora}] 📊 Contagem para {nome_jogador} ({tipo_acao.upper()} {local_acao}): {log_count}/{LOG_COUNT_THRESHOLD} | Valores diferentes: {', '.join(valores_unicos)}")
    else:
        print(f"[{agora}] 📊 Contagem para {nome_jogador} ({tipo_acao.upper()} {local_acao}): {log_count}/{LOG_COUNT_THRESHOLD}")
    
    # Verificar se atingiu o limite
    if log_count >= LOG_COUNT_THRESHOLD:
        # Contar quantas vezes já foi alertado
        vezes_alertado = 0
        if chave in alerted_keys:
            vezes_alertado = alerted_keys[chave]['count']
        
        # Atualizar contador de alertas
        if chave not in alerted_keys:
            alerted_keys[chave] = {'timestamp': now, 'count': 1}
        else:
            alerted_keys[chave]['count'] += 1
            vezes_alertado = alerted_keys[chave]['count']
        
        print(f"[{agora}] 🚨 ALERTA DISPARADO para jogador: {nome_jogador} ({tipo_acao.upper()} {local_acao}) - {vezes_alertado}ª vez")
        
        # Montar embed de alerta de spam (VERMELHO)
        logs_resumo = []
        item_qtd_atual = item_quantidade
        valores_diferentes = []
        total_valor = 0
        
        for i, (ts, linha, qtd) in enumerate(log_history[chave][-LOG_COUNT_THRESHOLD:], 1):
            if qtd != "?":
                item_qtd_atual = qtd
                # Extrair valor numérico para calcular total
                match_valor = re.search(r'x(\d+)', qtd)
                if match_valor:
                    valor = int(match_valor.group(1))
                    total_valor += valor
                    if qtd not in valores_diferentes:
                        valores_diferentes.append(qtd)
            logs_resumo.append(f"**{i}.** {linha[:40]}... | **{qtd}**")
        
        acao_texto = "COLOCOU" if tipo_acao == "colocou" else "PEGOU"
        
        # Se for reincidente, tornar mais chamativo
        if vezes_alertado > 1:
            # Cor mais intensa (vermelho escuro) e título mais chamativo
            cor_embed = 0x8B0000  # Vermelho escuro
            titulo = f"🚨🚨🚨 REINCIDENTE! ALERTA #{vezes_alertado} - ATIVIDADE SUSPEITA! 🚨🚨🚨"
            mentions = "@everyone @everyone @everyone"  # 3x mentions
            footer_text = f"⚠️⚠️⚠️ JOGADOR REINCIDENTE! Já foi alertado {vezes_alertado} vezes! AÇÃO URGENTE NECESSÁRIA! ⚠️⚠️⚠️"
        else:
            cor_embed = 0xFF0000  # Vermelho normal
            titulo = "🚨 ALERTA DE ATIVIDADE SUSPEITA DETECTADA! 🚨"
            mentions = "@everyone"
            footer_text = "⚠️ Verifique este jogador imediatamente!"
        
        spam_embed = discord.Embed(
            title=titulo,
            color=cor_embed
        )
        spam_embed.add_field(
            name="👤 Jogador",
            value=nome_jogador,
            inline=True
        )
        spam_embed.add_field(
            name="🆔 ID",
            value=player_id,
            inline=True
        )
        spam_embed.add_field(
            name="💰 Item/Qtd",
            value=item_qtd_atual or '?',
            inline=True
        )
        spam_embed.add_field(
            name="🔑 License",
            value=f"`{license}`",
            inline=False
        )
        spam_embed.add_field(
            name="📦 Ação",
            value=f"{acao_texto} no {local_acao.upper()}",
            inline=True
        )
        spam_embed.add_field(
            name="⏱️ Frequência",
            value=f"{LOG_COUNT_THRESHOLD}x em {TIME_WINDOW_SECONDS}s",
            inline=True
        )
        # Mostrar valores diferentes e total se houver múltiplos valores
        if len(valores_diferentes) > 1:
            total_formatado = f"{total_valor:,}".replace(",", ".")
            spam_embed.add_field(
                name="💵 Valores diferentes detectados",
                value=f"{', '.join(valores_diferentes)}\n**Total: x{total_formatado}**",
                inline=False
            )
        if vezes_alertado > 1:
            spam_embed.add_field(
                name="⚠️ REINCIDÊNCIA",
                value=f"**Este jogador já foi alertado {vezes_alertado} vezes!**",
                inline=False
            )
        spam_embed.add_field(
            name="📋 Logs detectados",
            value="\n".join(logs_resumo),
            inline=False
        )
        spam_embed.set_footer(text=footer_text)
        
        # Enviar alerta
        try:
            alert_channel = client.get_channel(ALERT_CHANNEL_ID)
            if alert_channel:
                await alert_channel.send(content=mentions, embed=spam_embed)
                print(f"✅ Alerta enviado para canal: {ALERT_CHANNEL_ID} ({vezes_alertado}ª vez)")
            else:
                print(f"❌ Canal de alerta não encontrado: {ALERT_CHANNEL_ID}")
        except Exception as e:
            print(f"❌ ERRO ao enviar alerta: {e}")
        
        # NÃO limpar histórico - permite novos alertas se continuar
        # Apenas limpa entradas antigas na próxima iteração

if TOKEN:
    client.run(TOKEN)
else:
    print("❌ TOKEN não encontrado! Verifique o arquivo .env")
