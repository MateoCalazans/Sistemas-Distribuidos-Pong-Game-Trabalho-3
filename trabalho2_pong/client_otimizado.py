"""
client_otimizado.py — Cliente Pong Otimizado (Sem Travamentos)
================================================================
Versão melhorada com:
  ✅ Timeouts em sockets (não fica bloqueado)
  ✅ Buffer circular (processa sem congestionamento)
  ✅ Descarta frames antigos se ficar atrasado
  ✅ Melhor sincronização de threads
  ✅ Detecção rápida de desconexão

Uso: python client_otimizado.py --mode tcp --ip 192.168.1.100 --port 5555
"""

import argparse, csv, json, os, sys, socket, threading, time, collections
import tkinter as tk
from tkinter import simpledialog

def safe_print(*args, **kwargs):
    try:
        sys.__stdout__.write(" ".join(map(str, args)) + "\n")
    except:
        pass
print = safe_print

try:
    import pygame
except ImportError:
    print("ERRO: pip install pygame"); sys.exit(1)

from network import NetworkMode

# =====================================================================
# CONSTANTES
# =====================================================================
LARGURA, ALTURA, FPS = 800, 600, 60
PRETO, BRANCO, CINZA = (0,0,0), (255,255,255), (100,100,100)
VERDE, VERMELHO, AMARELO, AZUL = (0,200,100), (200,50,50), (255,200,0), (50,100,200)
PADDLE_LARGURA, PADDLE_ALTURA, BOLA_TAM = 15, 100, 15
PADDLE1_X, PADDLE2_X = 30, LARGURA - 45

# Buffer circular para estados do jogo
BUFFER_SIZE = 30  # Armazena até 30 frames
TIMEOUT_SOCKET = 0.1  # 100ms timeout para não ficar bloqueado
TIMEOUT_DESCONEXAO = 3.0  # 3 segundos sem receber = desconectado

# =====================================================================
# VARIÁVEIS GLOBAIS
# =====================================================================
estado_buffer = collections.deque(maxlen=BUFFER_SIZE)
lock_buffer = threading.Lock()

meu_jogador = 0
conectado = False
rodando = True
ultimo_pacote = time.time()
seq_esperado = 0

# =====================================================================
# THREAD DE RECEBIMENTO (NÃO BLOQUEANTE)
# =====================================================================

def thread_receber(rede):
    """
    Thread otimizada que:
    - Não bloqueia por mais de 100ms
    - Processa múltiplos pacotes por frame
    - Descarta frames antigos se acumular
    """
    global meu_jogador, conectado, rodando, ultimo_pacote, seq_esperado
    
    while rodando:
        try:
            # timeout=TIMEOUT_SOCKET garante que não fica pendurado
            estado = rede.receber_cliente()
            
            if estado:
                ultimo_pacote = time.time()
                
                # Mensagem de confirmação (qual jogador é)
                if estado.get("tipo") == "confirmacao":
                    meu_jogador = estado["jogador"]
                    conectado = True
                    seq_esperado = 0
                    print(f"[OK] Você é Jogador {meu_jogador}")
                    continue
                
                # Se ficamos muito atrasados, descarta frames antigos
                with lock_buffer:
                    if len(estado_buffer) >= BUFFER_SIZE - 2:
                        # Limpa buffer se está muito cheio
                        estado_buffer.clear()
                    
                    seq_atual = estado.get("seq", 0)
                    # Só adiciona se é mais recente que o esperado
                    if seq_atual >= seq_esperado:
                        estado_buffer.append(estado)
                        seq_esperado = seq_atual + 1
                        
        except socket.timeout:
            # Timeout esperado, continua o loop
            continue
        except Exception as e:
            # Erro na recepção
            if rodando:
                time.sleep(0.01)


# =====================================================================
# DESENHO (SEM BLOQUEIOS)
# =====================================================================

def desenhar(tela, estado, rede, fontes, modo):
    """Desenha a tela sem bloquear threads."""
    fg, fm, fp = fontes
    tela.fill(PRETO)
    
    # Linha central
    for y in range(0, ALTURA, 20):
        pygame.draw.rect(tela, CINZA, (LARGURA//2-2, y, 4, 10))
    
    # Paddles
    p1y = estado.get("paddle1_y", 250)
    p2y = estado.get("paddle2_y", 250)
    pygame.draw.rect(tela, AZUL, (PADDLE1_X, p1y, PADDLE_LARGURA, PADDLE_ALTURA))
    pygame.draw.rect(tela, VERMELHO, (PADDLE2_X, p2y, PADDLE_LARGURA, PADDLE_ALTURA))
    
    # Bola
    bx = int(estado.get("bola_x", 400))
    by = int(estado.get("bola_y", 300))
    pygame.draw.rect(tela, BRANCO, (bx, by, BOLA_TAM, BOLA_TAM))
    
    # Placar
    txt = fg.render(f"{estado.get('placar1',0)}  :  {estado.get('placar2',0)}", True, BRANCO)
    tela.blit(txt, txt.get_rect(center=(LARGURA//2, 40)))
    tela.blit(fp.render("Jogador 1", True, AZUL), (LARGURA//4-40, 15))
    tela.blit(fp.render("Jogador 2", True, VERMELHO), (3*LARGURA//4-40, 15))
    
    # Métricas (canto inferior esquerdo)
    lat = rede.obter_latencia_atual()
    jit = rede.obter_jitter()
    cor = VERDE if lat < 20 else (AMARELO if lat < 50 else VERMELHO)
    
    yb = ALTURA - 80
    fundo = pygame.Surface((220, 75), pygame.SRCALPHA)
    fundo.fill((0, 0, 0, 150))
    tela.blit(fundo, (5, yb-5))
    
    tela.blit(fp.render(f"Modo: {modo.upper()}", True, BRANCO), (10, yb))
    tela.blit(fp.render(f"Latência: {lat:.1f} ms", True, cor), (10, yb+18))
    tela.blit(fp.render(f"Jitter: {jit:.1f} ms", True, BRANCO), (10, yb+36))
    
    if modo == "udp":
        perdidos = rede.pacotes_perdidos if hasattr(rede, 'pacotes_perdidos') else 0
        cor_perdidos = AMARELO if perdidos > 0 else VERDE
        tela.blit(fp.render(f"Perdidos: {perdidos}", True, cor_perdidos), (10, yb+54))
    
    # Status de conexão e buffer (canto inferior direito)
    buffer_size = len(estado_buffer)
    cor_buffer = VERDE if buffer_size < 5 else (AMARELO if buffer_size < 15 else VERMELHO)
    tv = fp.render(f"Você: J{meu_jogador} | Buffer: {buffer_size}", True, cor_buffer)
    tela.blit(tv, (LARGURA - tv.get_width() - 10, ALTURA - 25))


# =====================================================================
# SALVAR MÉTRICAS
# =====================================================================

def salvar_metricas(rede):
    """Salva métricas coletadas em CSV."""
    try:
        m = rede.obter_metricas_finais()
        arq = "metricas_jogo.csv"
        novo = not os.path.exists(arq)
        
        with open(arq, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(m.keys()))
            if novo:
                w.writeheader()
            w.writerow(m)
        
        print(f"\n[MÉTRICAS] Salvas em {arq}")
        for k, v in m.items():
            print(f"  {k}: {v}")
    except Exception as e:
        print(f"[ERRO] Não foi possível salvar métricas: {e}")


# =====================================================================
# MAIN
# =====================================================================

def main():
    global rodando, ultimo_pacote
    
    print("=" * 50)
    print("   BEM-VINDO AO PONG (VERSÃO OTIMIZADA)")
    print("=" * 50)
    
    # Parse argumentos
    parser = argparse.ArgumentParser(description="Cliente Pong Otimizado")
    parser.add_argument("--mode", choices=["tcp", "udp"], default="tcp")
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()
    
    # Se executado sem argumentos, usa Pop-ups Windows
    if len(sys.argv) == 1:
        try:
            root = tk.Tk()
            root.withdraw()
            
            m = simpledialog.askstring("Modo", "Qual modo? udp ou tcp", initialvalue="tcp")
            modo = m.strip().lower() if m else "tcp"
            if modo not in ["tcp", "udp"]: modo = "tcp"
            
            i = simpledialog.askstring("IP", "IP do Servidor:", initialvalue="127.0.0.1")
            ip = i.strip() if i else "127.0.0.1"
            
            p = simpledialog.askstring("Porta", "Qual a porta?", initialvalue="5555")
            porta = int(p.strip()) if (p and p.strip().isdigit()) else 5555
            
            root.destroy()
        except Exception:
            # Fallback seguro
            modo, ip, porta = "tcp", "127.0.0.1", 5555
    else:
        modo = args.mode
        ip = args.ip
        porta = args.port
    
    # Inicializa rede com timeout configurado
    rede = NetworkMode(mode=modo, is_server=False)
    
    try:
        print(f"\n[CONECTANDO] {ip}:{porta} ({modo.upper()})...")
        rede.criar_socket_cliente(ip, porta)
        # Configura timeout para não ficar bloqueado
        if hasattr(rede, 'socket'):
            rede.socket.settimeout(TIMEOUT_SOCKET)
    except Exception as e:
        print(f"[ERRO] Não foi possível conectar: {e}")
        try: input("\nPressione ENTER para fechar...")
        except: pass
        sys.exit(1)
    
    # Inicia thread de recebimento
    threading.Thread(target=thread_receber, args=(rede,), daemon=True).start()
    
    # Pygame
    pygame.init()
    tela = pygame.display.set_mode((LARGURA, ALTURA))
    pygame.display.set_caption(f"Pong Otimizado — {modo.upper()}")
    clock = pygame.time.Clock()
    fontes = (
        pygame.font.SysFont("Arial", 48, bold=True),
        pygame.font.SysFont("Arial", 24),
        pygame.font.SysFont("Arial", 16),
    )
    
    print("[OK] Conectado! Aguardando jogo iniciar...\n")
    
    try:
        while rodando:
            # Eventos
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    rodando = False
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    rodando = False
            
            if not rodando:
                break
            
            # Detecta desconexão (sem pacotes por 3 segundos)
            if conectado and (time.time() - ultimo_pacote) > TIMEOUT_DESCONEXAO:
                print("[DESCONEXÃO] Servidor não responde há 3 segundos")
                rodando = False
                break
            
            # Input do jogador
            teclas = pygame.key.get_pressed()
            t = "nenhum"
            
            if meu_jogador == 1:
                if teclas[pygame.K_w]:
                    t = "cima"
                elif teclas[pygame.K_s]:
                    t = "baixo"
            elif meu_jogador == 2:
                if teclas[pygame.K_UP]:
                    t = "cima"
                elif teclas[pygame.K_DOWN]:
                    t = "baixo"
            
            # Envia input (não bloqueante)
            if conectado:
                try:
                    rede.enviar_cliente({"tecla": t})
                except:
                    pass
            
            # Pega o estado mais recente do buffer
            estado_para_desenhar = None
            with lock_buffer:
                if estado_buffer:
                    # Pega o último estado (mais recente)
                    estado_para_desenhar = dict(estado_buffer[-1])
            
            # Desenha
            if estado_para_desenhar and conectado:
                desenhar(tela, estado_para_desenhar, rede, fontes, modo)
            else:
                tela.fill(PRETO)
                msg = "Aguardando jogadores..." if not conectado else "Carregando..."
                tela.blit(fontes[1].render(msg, True, CINZA),
                         (LARGURA // 2 - 130, ALTURA // 2))
            
            pygame.display.flip()
            clock.tick(FPS)
    
    except KeyboardInterrupt:
        pass
    
    finally:
        rodando = False
        if hasattr(rede, 'latencias') and rede.latencias:
            salvar_metricas(rede)
        rede.fechar()
        pygame.quit()
        print("\n[FIM] Cliente encerrado.")
        try: input("Pressione ENTER para fechar...")
        except: pass


if __name__ == "__main__":
    main()
