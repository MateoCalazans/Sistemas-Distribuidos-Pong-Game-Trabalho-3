"""
server.py — Servidor do Pong Multiplayer
==========================================
Roda o loop principal do jogo a 60fps.
Mantém a posição da bola, dos paddles e o placar.
Aceita conexão de 2 clientes (TCP ou UDP).
A cada frame: recebe inputs, calcula física, envia estado.

Uso:
    python server.py --mode tcp
    python server.py --mode udp

Autores: Alunos UFRN — Sistemas Distribuídos
"""

import argparse
import json
import socket
import threading
import time
import sys

from network import NetworkMode


# ======================================================================
# CONSTANTES DO JOGO
# ======================================================================

LARGURA = 800               # Largura da tela
ALTURA = 600                # Altura da tela
FPS = 60                    # Frames por segundo
TEMPO_FRAME = 1.0 / FPS    # Duração de cada frame

# Dimensões dos objetos
PADDLE_LARGURA = 15
PADDLE_ALTURA = 100
BOLA_TAMANHO = 15

# Velocidades
PADDLE_VELOCIDADE = 6       # Pixels por frame que o paddle se move
BOLA_VELOCIDADE_X = 5       # Velocidade horizontal da bola
BOLA_VELOCIDADE_Y = 5       # Velocidade vertical da bola

# Posições iniciais
PADDLE1_X = 30                          # Posição X do paddle esquerdo
PADDLE2_X = LARGURA - 30 - PADDLE_LARGURA  # Posição X do paddle direito


# ======================================================================
# ESTADO DO JOGO (variáveis globais compartilhadas)
# ======================================================================

estado_jogo = {
    "bola_x": LARGURA // 2,             # Posição X da bola (centro)
    "bola_y": ALTURA // 2,              # Posição Y da bola (centro)
    "paddle1_y": ALTURA // 2 - PADDLE_ALTURA // 2,  # Paddle 1 centralizado
    "paddle2_y": ALTURA // 2 - PADDLE_ALTURA // 2,  # Paddle 2 centralizado
    "placar1": 0,                        # Placar do jogador 1
    "placar2": 0,                        # Placar do jogador 2
    "timestamp": 0,                      # Timestamp do frame atual
    "seq": 0,                            # Número de sequência do pacote
}

# Velocidade atual da bola (pode inverter em colisões)
bola_vel_x = BOLA_VELOCIDADE_X
bola_vel_y = BOLA_VELOCIDADE_Y

# Inputs dos jogadores (atualizados pelas threads de recebimento)
inputs_jogadores = {"jogador1": "nenhum", "jogador2": "nenhum"}
lock_inputs = threading.Lock()

# Controle de conexão
jogadores_conectados = 0
jogo_rodando = False


# ======================================================================
# FUNÇÕES DE FÍSICA DO JOGO
# ======================================================================

def resetar_bola():
    """
    Reposiciona a bola no centro após um ponto ser marcado.
    Inverte a direção horizontal para alternar o saque.
    """
    global bola_vel_x, bola_vel_y
    estado_jogo["bola_x"] = LARGURA // 2
    estado_jogo["bola_y"] = ALTURA // 2
    bola_vel_x = -bola_vel_x  # Inverte direção (alterna quem recebe)
    bola_vel_y = BOLA_VELOCIDADE_Y if bola_vel_y > 0 else -BOLA_VELOCIDADE_Y


def atualizar_fisica():
    """
    Calcula a física do jogo a cada frame:
    1. Move os paddles de acordo com os inputs
    2. Move a bola
    3. Verifica colisão com paredes (topo/baixo)
    4. Verifica colisão com paddles
    5. Verifica se alguém marcou ponto
    """
    global bola_vel_x, bola_vel_y
    
    # --- 1. Movimentação dos paddles ---
    with lock_inputs:
        input1 = inputs_jogadores["jogador1"]
        input2 = inputs_jogadores["jogador2"]
    
    # Paddle 1 (W = subir, S = descer)
    if input1 == "cima":
        estado_jogo["paddle1_y"] = max(0, estado_jogo["paddle1_y"] - PADDLE_VELOCIDADE)
    elif input1 == "baixo":
        estado_jogo["paddle1_y"] = min(ALTURA - PADDLE_ALTURA, estado_jogo["paddle1_y"] + PADDLE_VELOCIDADE)
    
    # Paddle 2 (Seta cima/baixo)
    if input2 == "cima":
        estado_jogo["paddle2_y"] = max(0, estado_jogo["paddle2_y"] - PADDLE_VELOCIDADE)
    elif input2 == "baixo":
        estado_jogo["paddle2_y"] = min(ALTURA - PADDLE_ALTURA, estado_jogo["paddle2_y"] + PADDLE_VELOCIDADE)
    
    # --- 2. Movimentação da bola ---
    estado_jogo["bola_x"] += bola_vel_x
    estado_jogo["bola_y"] += bola_vel_y
    
    # --- 3. Colisão com paredes (topo e baixo) ---
    if estado_jogo["bola_y"] <= 0:
        estado_jogo["bola_y"] = 0
        bola_vel_y = abs(bola_vel_y)  # Rebate para baixo
    elif estado_jogo["bola_y"] >= ALTURA - BOLA_TAMANHO:
        estado_jogo["bola_y"] = ALTURA - BOLA_TAMANHO
        bola_vel_y = -abs(bola_vel_y)  # Rebate para cima
    
    # --- 4. Colisão com paddles ---
    bola_x = estado_jogo["bola_x"]
    bola_y = estado_jogo["bola_y"]
    
    # Colisão com paddle 1 (esquerdo)
    if (bola_x <= PADDLE1_X + PADDLE_LARGURA and
        bola_x >= PADDLE1_X and
        bola_y + BOLA_TAMANHO >= estado_jogo["paddle1_y"] and
        bola_y <= estado_jogo["paddle1_y"] + PADDLE_ALTURA):
        bola_vel_x = abs(bola_vel_x)  # Rebate para a direita
        estado_jogo["bola_x"] = PADDLE1_X + PADDLE_LARGURA + 1
    
    # Colisão com paddle 2 (direito)
    if (bola_x + BOLA_TAMANHO >= PADDLE2_X and
        bola_x + BOLA_TAMANHO <= PADDLE2_X + PADDLE_LARGURA and
        bola_y + BOLA_TAMANHO >= estado_jogo["paddle2_y"] and
        bola_y <= estado_jogo["paddle2_y"] + PADDLE_ALTURA):
        bola_vel_x = -abs(bola_vel_x)  # Rebate para a esquerda
        estado_jogo["bola_x"] = PADDLE2_X - BOLA_TAMANHO - 1
    
    # --- 5. Verificação de pontos ---
    if estado_jogo["bola_x"] < 0:
        # Bola saiu pela esquerda → Jogador 2 marca ponto
        estado_jogo["placar2"] += 1
        print(f"[PLACAR] Jogador 1: {estado_jogo['placar1']} x {estado_jogo['placar2']} :Jogador 2")
        resetar_bola()
    
    elif estado_jogo["bola_x"] > LARGURA:
        # Bola saiu pela direita → Jogador 1 marca ponto
        estado_jogo["placar1"] += 1
        print(f"[PLACAR] Jogador 1: {estado_jogo['placar1']} x {estado_jogo['placar2']} :Jogador 2")
        resetar_bola()
    
    # Atualiza timestamp e sequência
    estado_jogo["timestamp"] = time.time()
    estado_jogo["seq"] += 1


# ======================================================================
# THREAD: RECEBIMENTO DE INPUTS (MODO TCP)
# ======================================================================

def thread_receber_input_tcp(rede, indice_jogador):
    """
    Thread dedicada para receber inputs de um jogador via TCP.
    Roda em loop contínuo até o jogo terminar.
    Cada jogador tem sua própria thread de recebimento.
    """
    global jogo_rodando
    chave = f"jogador{indice_jogador + 1}"
    conn = rede.connections[indice_jogador]
    conn.settimeout(1.0)
    buffer = b""
    
    while jogo_rodando:
        try:
            pedaco = conn.recv(4096)
            if not pedaco:
                print(f"[TCP] Jogador {indice_jogador + 1} desconectou")
                jogo_rodando = False
                break
            buffer += pedaco
            
            # Processa todas as mensagens completas no buffer
            while b"\n" in buffer:
                mensagem, buffer = buffer.split(b"\n", 1)
                try:
                    dados = json.loads(mensagem.decode("utf-8"))
                    with lock_inputs:
                        inputs_jogadores[chave] = dados.get("tecla", "nenhum")
                except json.JSONDecodeError:
                    pass
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[ERRO] Thread receber jogador {indice_jogador + 1}: {e}")
            break


# ======================================================================
# THREAD: RECEBIMENTO DE INPUTS (MODO UDP)
# ======================================================================

def thread_receber_input_udp(rede):
    """
    Thread dedicada para receber inputs de ambos jogadores via UDP.
    No UDP, todos os pacotes chegam pelo mesmo socket.
    Identificamos o jogador pelo endereço de origem.
    """
    global jogo_rodando
    rede.socket.settimeout(1.0)
    
    while jogo_rodando:
        try:
            dados_bytes, addr = rede.socket.recvfrom(4096)
            dados = json.loads(dados_bytes.decode("utf-8"))
            
            # Identifica qual jogador enviou pelo endereço
            with rede.lock:
                if addr in rede.connections:
                    indice = rede.connections.index(addr)
                    chave = f"jogador{indice + 1}"
                    with lock_inputs:
                        inputs_jogadores[chave] = dados.get("tecla", "nenhum")
        except socket.timeout:
            continue
        except Exception as e:
            continue


# ======================================================================
# FUNÇÃO PRINCIPAL
# ======================================================================

def main():
    global jogadores_conectados, jogo_rodando
    
    # --- Argumentos de linha de comando ---
    parser = argparse.ArgumentParser(description="Servidor Pong Multiplayer")
    parser.add_argument("--mode", choices=["tcp", "udp"], default="tcp",
                        help="Modo de rede: tcp ou udp (padrão: tcp)")
    parser.add_argument("--port", type=int, default=5555,
                        help="Porta do servidor (padrão: 5555)")
    args = parser.parse_args()
    
    print("=" * 50)
    print(f"  SERVIDOR PONG — Modo {args.mode.upper()}")
    print("=" * 50)
    
    # --- Inicializa a rede ---
    rede = NetworkMode(mode=args.mode, is_server=True)
    rede.criar_socket_servidor(porta=args.port)
    
    # --- Aguarda 2 jogadores ---
    print("\n[AGUARDANDO] Esperando 2 jogadores se conectarem...\n")
    
    if args.mode == "tcp":
        # TCP: aceita 2 conexões separadas
        for i in range(2):
            rede.aceitar_conexao()
            jogadores_conectados += 1
            print(f"  → {jogadores_conectados}/2 jogadores conectados")
    else:
        # UDP: espera 2 registros
        for i in range(2):
            rede.aceitar_conexao()
            jogadores_conectados += 1
            print(f"  → {jogadores_conectados}/2 jogadores conectados")
    
    print("\n[JOGO] Ambos jogadores conectados! Iniciando o jogo...")
    
    # Envia confirmação para os clientes (qual jogador cada um é)
    for i in range(2):
        confirmacao = {"tipo": "confirmacao", "jogador": i + 1}
        rede.enviar_servidor(confirmacao, i)
    
    # Pequeno atraso para os clientes processarem a confirmação
    time.sleep(0.5)
    
    # --- Inicia threads de recebimento ---
    jogo_rodando = True
    
    if args.mode == "tcp":
        # TCP: uma thread por jogador
        t1 = threading.Thread(target=thread_receber_input_tcp, args=(rede, 0), daemon=True)
        t2 = threading.Thread(target=thread_receber_input_tcp, args=(rede, 1), daemon=True)
        t1.start()
        t2.start()
    else:
        # UDP: uma thread para ambos
        t_udp = threading.Thread(target=thread_receber_input_udp, args=(rede,), daemon=True)
        t_udp.start()
    
    # --- Loop principal do jogo (60 FPS) ---
    print("[JOGO] Loop do jogo iniciado (60 FPS)")
    print("[JOGO] Pressione Ctrl+C para encerrar\n")
    
    try:
        while jogo_rodando:
            inicio_frame = time.time()
            
            # 1. Calcula a física (movimento, colisões, pontos)
            atualizar_fisica()
            
            # 2. Envia o estado atualizado para ambos jogadores
            for i in range(2):
                try:
                    rede.enviar_servidor(dict(estado_jogo), i)
                except:
                    pass
            
            # 3. Controla o framerate (espera até completar 1/60s)
            tempo_gasto = time.time() - inicio_frame
            tempo_espera = TEMPO_FRAME - tempo_gasto
            if tempo_espera > 0:
                time.sleep(tempo_espera)
                
    except KeyboardInterrupt:
        print("\n\n[JOGO] Servidor encerrado pelo usuário.")
    finally:
        jogo_rodando = False
        rede.fechar()
        print("[JOGO] Conexões fechadas. Até logo!")


if __name__ == "__main__":
    main()
