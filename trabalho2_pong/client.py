"""
client.py — Cliente do Pong Multiplayer (Pygame)
===================================================
Janela 800x600. Conecta ao servidor por IP.
J1: W/S | J2: Setas. Exibe latência e jitter.
Salva métricas em metricas_jogo.csv ao fechar.

Uso: python client.py --mode tcp
     python client.py --mode udp
"""

import argparse, csv, json, os, sys, socket, threading, time

try:
    import pygame
except ImportError:
    print("ERRO: pip install pygame"); sys.exit(1)

from network import NetworkMode

# Constantes
LARGURA, ALTURA, FPS = 800, 600, 60
PRETO, BRANCO, CINZA = (0,0,0), (255,255,255), (100,100,100)
VERDE, VERMELHO, AMARELO, AZUL = (0,200,100), (200,50,50), (255,200,0), (50,100,200)
PADDLE_LARGURA, PADDLE_ALTURA, BOLA_TAM = 15, 100, 15
PADDLE1_X, PADDLE2_X = 30, LARGURA - 45

# Globais
estado_atual = None
lock_estado = threading.Lock()
meu_jogador = 0
conectado = False
rodando = True

def thread_receber(rede):
    """Thread que recebe estado do servidor continuamente."""
    global estado_atual, meu_jogador, conectado, rodando
    while rodando:
        try:
            estado = rede.receber_cliente()
            if estado:
                with lock_estado:
                    if estado.get("tipo") == "confirmacao":
                        meu_jogador = estado["jogador"]
                        conectado = True
                        print(f"[OK] Você é Jogador {meu_jogador}")
                        continue
                    estado_atual = estado
        except:
            if rodando: time.sleep(0.01)

def desenhar(tela, estado, rede, fontes, modo):
    """Desenha campo, paddles, bola, placar e métricas."""
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
    bx, by = int(estado.get("bola_x",400)), int(estado.get("bola_y",300))
    pygame.draw.rect(tela, BRANCO, (bx, by, BOLA_TAM, BOLA_TAM))
    # Placar
    txt = fg.render(f"{estado.get('placar1',0)}  :  {estado.get('placar2',0)}", True, BRANCO)
    tela.blit(txt, txt.get_rect(center=(LARGURA//2, 40)))
    tela.blit(fp.render("Jogador 1", True, AZUL), (LARGURA//4-40, 15))
    tela.blit(fp.render("Jogador 2", True, VERMELHO), (3*LARGURA//4-40, 15))
    # Métricas
    lat = rede.obter_latencia_atual()
    jit = rede.obter_jitter()
    cor = VERDE if lat < 20 else (AMARELO if lat < 50 else VERMELHO)
    yb = ALTURA - 80
    fundo = pygame.Surface((200,75), pygame.SRCALPHA); fundo.fill((0,0,0,150))
    tela.blit(fundo, (5, yb-5))
    tela.blit(fp.render(f"Modo: {modo.upper()}", True, BRANCO), (10, yb))
    tela.blit(fp.render(f"Latência: {lat:.1f} ms", True, cor), (10, yb+18))
    tela.blit(fp.render(f"Jitter: {jit:.1f} ms", True, BRANCO), (10, yb+36))
    if modo=="udp":
        tela.blit(fp.render(f"Perdidos: {rede.pacotes_perdidos}", True, AMARELO), (10, yb+54))
    # Indicador
    c = AZUL if meu_jogador==1 else VERMELHO
    tv = fp.render(f"Você: Jogador {meu_jogador}", True, c)
    tela.blit(tv, (LARGURA-tv.get_width()-10, ALTURA-25))

def salvar_metricas(rede):
    """Salva métricas coletadas em CSV."""
    m = rede.obter_metricas_finais()
    arq = "metricas_jogo.csv"
    novo = not os.path.exists(arq)
    with open(arq, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(m.keys()))
        if novo: w.writeheader()
        w.writerow(m)
    print(f"\n[MÉTRICAS] Salvas em {arq}")
    for k,v in m.items(): print(f"  {k}: {v}")

def main():
    global estado_atual, rodando
    
    print("==========================================")
    print("           BEM-VINDO AO PONG")
    print("==========================================")
    
    # Perguntas para quem abre com duplo-clique no .exe
    modo = input("Qual modo de rede? udp ou tcp (Enter = udp): ").strip().lower()
    if modo not in ["tcp", "udp"]:
        modo = "udp"
        
    porta_str = input("Qual a porta do servidor? (Enter = 5556): ").strip()
    porta = int(porta_str) if porta_str.isdigit() else 5556
    
    ip = input("Qual o IP do servidor? (Enter = localhost): ").strip() or "127.0.0.1"

    rede = NetworkMode(mode=modo, is_server=False)
    try:
        print(f"\n[CONECTANDO] Tentando conectar a {ip}:{porta} ({modo.upper()})...")
        rede.criar_socket_cliente(ip, porta)
    except Exception as e:
        print(f"\n[ERRO MORTAL] Não foi possível conectar: {e}")
        input("\nPressione ENTER para fechar a janela...")
        sys.exit(1)

    threading.Thread(target=thread_receber, args=(rede,), daemon=True).start()

    pygame.init()
    tela = pygame.display.set_mode((LARGURA, ALTURA))
    pygame.display.set_caption(f"Pong — {modo.upper()}")
    clock = pygame.time.Clock()
    fontes = (
        pygame.font.SysFont("Arial", 48, bold=True),
        pygame.font.SysFont("Arial", 24),
        pygame.font.SysFont("Arial", 16),
    )

    try:
        while rodando:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT: rodando = False
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE: rodando = False
            if not rodando: break

            teclas = pygame.key.get_pressed()
            t = "nenhum"
            if meu_jogador==1:
                if teclas[pygame.K_w]: t="cima"
                elif teclas[pygame.K_s]: t="baixo"
            elif meu_jogador==2:
                if teclas[pygame.K_UP]: t="cima"
                elif teclas[pygame.K_DOWN]: t="baixo"

            if conectado:
                rede.enviar_cliente({"tecla": t})

            # Encerra se o servidor desconectou
            if rede.desconectado:
                print("[REDE] Servidor encerrou. Fechando cliente...")
                rodando = False
                break

            with lock_estado:
                ec = dict(estado_atual) if estado_atual else None

            if ec and conectado:
                desenhar(tela, ec, rede, fontes, modo)
            else:
                tela.fill(PRETO)
                tela.blit(fontes[1].render("Aguardando jogadores...", True, CINZA),
                          (LARGURA//2-130, ALTURA//2))

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
        input("Pressione ENTER para fechar esta janela...")

if __name__ == "__main__":
    main()
