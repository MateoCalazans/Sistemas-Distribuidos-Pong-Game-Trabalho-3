"""
cliente_grpc.py — Cliente Pong via gRPC (Pygame)
=================================================
Responsabilidade:
  • Capturar teclas do jogador e invocar MoverRaquete() remotamente
  • Fazer polling de ObterEstado() a ~60fps para obter o estado do jogo
  • Renderizar a tela com Pygame

Dinâmica de comunicação (Polling):
  Como o gRPC não faz push nativo ao cliente, o game loop
  invoca ObterEstado() a cada frame (~16ms). Se a rede engarrafar,
  o cliente usa o último estado válido recebido como fallback,
  garantindo que a tela não congele.

Uso:
    python cliente_grpc.py
    python cliente_grpc.py --ip 192.168.1.10 --port 50051

Autores: Guilherme Felipe, Jeane Mirele, Caio Cesar, Mateo Calazans
"""

import argparse
import sys
import time
import tkinter as tk
from tkinter import simpledialog

try:
    import pygame
except ImportError:
    print("ERRO: pip install pygame")
    sys.exit(1)

import os
# Adds the current directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import grpc
    import pong_pb2
    import pong_pb2_grpc
except ImportError:
    print("ERRO: pip install grpcio grpcio-tools")
    sys.exit(1)


# ======================================================================
# CONSTANTES DE EXIBIÇÃO
# ======================================================================

LARGURA, ALTURA, FPS = 800, 600, 60

PADDLE_LARGURA, PADDLE_ALTURA = 15, 100
BOLA_TAM = 15
PADDLE1_X = 30
PADDLE2_X = LARGURA - 45

# Paleta de cores
PRETO    = (  0,   0,   0)
BRANCO   = (255, 255, 255)
CINZA    = (100, 100, 100)
CINZA_E  = ( 40,  40,  40)
AZUL     = ( 50, 130, 255)
VERMELHO = (220,  60,  60)
VERDE    = (  0, 200, 100)
AMARELO  = (255, 210,   0)
ROXO     = (160,  60, 220)
LARANJA  = (255, 140,   0)


# ======================================================================
# STUB gRPC (invocação remota)
# ======================================================================

class ClienteGrpc:
    """
    Encapsula o stub gRPC e mede a latência de cada chamada RPC.
    Cada método é uma invocação remota — executado no servidor.
    """

    def __init__(self, ip: str, porta: int):
        self.endereco = f"{ip}:{porta}"
        # Canal de comunicação com o servidor
        self.canal = grpc.insecure_channel(self.endereco)
        # Stub: objeto local que "finge" ter os métodos do servidor
        self.stub = pong_pb2_grpc.PongServiceStub(self.canal)

        self.id_jogador    = 0
        self.latencias     = []          # Histórico de latências RPC (ms)
        self.ultimo_estado = None        # Último estado válido recebido

    # ── ConectarJogador ────────────────────────────────────────────
    def conectar(self, nome="Jogador"):
        """Invoca ConectarJogador() no servidor. Retorna o ID recebido."""
        t0 = time.perf_counter()
        resp = self.stub.ConectarJogador(pong_pb2.ConectarRequest(nome=nome))
        self._registrar_latencia(t0)
        return resp

    # ── MoverRaquete ───────────────────────────────────────────────
    def mover_raquete(self, direcao: str):
        """
        Invoca MoverRaquete() no servidor com a direção atual.
        Chamado a cada frame em que o jogador pressiona uma tecla.
        """
        try:
            t0 = time.perf_counter()
            self.stub.MoverRaquete(pong_pb2.MoverRequest(
                id_jogador=self.id_jogador,
                direcao=direcao
            ))
            self._registrar_latencia(t0)
        except grpc.RpcError:
            pass  # Será detectado no próximo ObterEstado

    # ── ObterEstado ────────────────────────────────────────────────
    def obter_estado(self):
        """
        Invoca ObterEstado() no servidor (polling).
        LATÊNCIA: se a chamada demorar demais, retorna o último estado.

        FALLBACK: em caso de timeout ou erro de rede, o último estado
        válido é retornado para que a tela não congele.
        """
        try:
            t0 = time.perf_counter()
            estado = self.stub.ObterEstado(
                pong_pb2.EstadoRequest(id_jogador=self.id_jogador),
                timeout=0.5  # Máximo 500ms por chamada
            )
            self._registrar_latencia(t0)
            self.ultimo_estado = estado
            return estado
        except grpc.RpcError:
            # Fallback: retorna último estado conhecido
            return self.ultimo_estado

    # ── Métricas ───────────────────────────────────────────────────
    def _registrar_latencia(self, t0: float):
        ms = (time.perf_counter() - t0) * 1000
        self.latencias.append(ms)
        if len(self.latencias) > 120:        # Janela deslizante: últimos 2s
            self.latencias.pop(0)

    def latencia_atual(self) -> float:
        return self.latencias[-1] if self.latencias else 0.0

    def jitter(self) -> float:
        if len(self.latencias) < 2:
            return 0.0
        recentes = self.latencias[-10:]
        diffs = [abs(recentes[i] - recentes[i-1]) for i in range(1, len(recentes))]
        return sum(diffs) / len(diffs) if diffs else 0.0

    def fechar(self):
        self.canal.close()


# ======================================================================
# RENDERIZAÇÃO
# ======================================================================

def _draw_dashed_line(surf, color, x, y_start, y_end, dash=10, gap=8):
    """Desenha linha vertical tracejada (linha central do campo)."""
    y = y_start
    while y < y_end:
        pygame.draw.rect(surf, color, (x - 2, y, 4, min(dash, y_end - y)))
        y += dash + gap


def desenhar_aguardando(tela, fontes, modo, ip, porta):
    """Tela de espera enquanto o P2 não conectou."""
    fg, fm, fp = fontes
    tela.fill(PRETO)
    _draw_dashed_line(tela, CINZA_E, LARGURA // 2, 0, ALTURA)

    msg1 = fm.render("PONG — gRPC", True, BRANCO)
    msg2 = fp.render("Aguardando o segundo jogador...", True, CINZA)
    msg3 = fp.render(f"Servidor: {ip}:{porta}  |  Modo: gRPC", True, CINZA)
    spinner = "|/-\\"[int(time.time() * 4) % 4]
    msg4 = fm.render(spinner, True, AZUL)

    tela.blit(msg1, msg1.get_rect(center=(LARGURA // 2, 220)))
    tela.blit(msg2, msg2.get_rect(center=(LARGURA // 2, 290)))
    tela.blit(msg3, msg3.get_rect(center=(LARGURA // 2, 320)))
    tela.blit(msg4, msg4.get_rect(center=(LARGURA // 2, 370)))


def desenhar_jogo(tela, estado, cliente: ClienteGrpc, fontes, meu_id):
    """Renderiza o frame principal do jogo."""
    fg, fm, fp = fontes
    tela.fill(PRETO)

    # Linha central tracejada
    _draw_dashed_line(tela, CINZA_E, LARGURA // 2, 0, ALTURA)

    # ── Raquetes ──────────────────────────────────────────────────
    p1y = int(estado.raquete1_y)
    p2y = int(estado.raquete2_y)

    # Destaca a raquete do jogador local com brilho extra
    cor_p1 = AZUL   if meu_id == 1 else (30, 80, 180)
    cor_p2 = VERMELHO if meu_id == 2 else (140, 30, 30)

    pygame.draw.rect(tela, cor_p1,    (PADDLE1_X, p1y, PADDLE_LARGURA, PADDLE_ALTURA))
    pygame.draw.rect(tela, cor_p2,    (PADDLE2_X, p2y, PADDLE_LARGURA, PADDLE_ALTURA))

    # Borda de destaque na raquete local
    if meu_id == 1:
        pygame.draw.rect(tela, BRANCO, (PADDLE1_X, p1y, PADDLE_LARGURA, PADDLE_ALTURA), 2)
    else:
        pygame.draw.rect(tela, BRANCO, (PADDLE2_X, p2y, PADDLE_LARGURA, PADDLE_ALTURA), 2)

    # ── Bola ──────────────────────────────────────────────────────
    bx, by = int(estado.bola_x), int(estado.bola_y)
    pygame.draw.rect(tela, BRANCO, (bx, by, BOLA_TAM, BOLA_TAM))
    pygame.draw.rect(tela, CINZA,  (bx, by, BOLA_TAM, BOLA_TAM), 1)

    # ── Placar ────────────────────────────────────────────────────
    txt_placar = fg.render(
        f"{estado.placar1}  :  {estado.placar2}", True, BRANCO)
    tela.blit(txt_placar, txt_placar.get_rect(center=(LARGURA // 2, 40)))

    tela.blit(fp.render("Jogador 1", True, AZUL),    (LARGURA // 4 - 40, 15))
    tela.blit(fp.render("Jogador 2", True, VERMELHO), (3 * LARGURA // 4 - 40, 15))

    # ── Painel de métricas (canto inferior esquerdo) ──────────────
    lat = cliente.latencia_atual()
    jit = cliente.jitter()
    cor_lat = VERDE if lat < 30 else (AMARELO if lat < 80 else VERMELHO)

    painel = pygame.Surface((230, 80), pygame.SRCALPHA)
    painel.fill((0, 0, 0, 160))
    tela.blit(painel, (5, ALTURA - 88))

    tela.blit(fp.render("Protocolo: gRPC (RPC)", True, BRANCO),  (10, ALTURA - 85))
    tela.blit(fp.render(f"Latência RPC: {lat:.1f} ms",  True, cor_lat), (10, ALTURA - 67))
    tela.blit(fp.render(f"Jitter:       {jit:.1f} ms",  True, BRANCO),  (10, ALTURA - 49))
    tela.blit(fp.render(f"Frame seq:    {estado.seq}",  True, CINZA),   (10, ALTURA - 31))

    # ── Indicador do jogador (canto inferior direito) ─────────────
    cor_eu = AZUL if meu_id == 1 else VERMELHO
    txt_eu = fp.render(f"Você: Jogador {meu_id}  |  gRPC Polling", True, cor_eu)
    tela.blit(txt_eu, (LARGURA - txt_eu.get_width() - 10, ALTURA - 25))


def desenhar_fim(tela, estado, fontes, meu_id):
    """Tela de encerramento com resultado da partida."""
    fg, fm, fp = fontes
    tela.fill(PRETO)
    _draw_dashed_line(tela, CINZA_E, LARGURA // 2, 0, ALTURA)

    vencedor = estado.vencedor
    motivo   = estado.motivo

    if vencedor == meu_id:
        titulo = "🏆  VOCÊ VENCEU!  🏆"
        cor    = VERDE
    elif vencedor == 0:
        titulo = "JOGO ENCERRADO"
        cor    = CINZA
    else:
        titulo = "VOCÊ PERDEU"
        cor    = VERMELHO

    if motivo == "wo":
        subtitulo = "Vitória por W.O. (rival desconectou)"
        cor_sub   = LARANJA
    else:
        subtitulo = f"Placar final:  {estado.placar1} × {estado.placar2}"
        cor_sub   = BRANCO

    tela.blit(fg.render(titulo, True, cor),
              fg.render(titulo, True, cor).get_rect(center=(LARGURA // 2, 230)))
    tela.blit(fm.render(subtitulo, True, cor_sub),
              fm.render(subtitulo, True, cor_sub).get_rect(center=(LARGURA // 2, 300)))
    tela.blit(fp.render("Pressione ESC ou feche a janela para sair", True, CINZA),
              fp.render("Pressione ESC ou feche a janela para sair", True, CINZA
                        ).get_rect(center=(LARGURA // 2, 360)))


# ======================================================================
# MAIN
# ======================================================================

def main():
    print("=" * 50)
    print("   PONG — Cliente gRPC")
    print("=" * 50)

    # ── Parse de argumentos ────────────────────────────────────────
    parser = argparse.ArgumentParser(description="Cliente Pong gRPC")
    parser.add_argument("--ip",   default="")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    # Se executado sem argumentos, exibe pop-ups
    if not args.ip or not args.port:
        try:
            root = tk.Tk(); root.withdraw()
            ip_input = simpledialog.askstring(
                "Servidor", "IP do Servidor gRPC:", initialvalue="127.0.0.1")
            ip = (ip_input or "127.0.0.1").strip()

            porta_input = simpledialog.askstring(
                "Porta", "Porta do Servidor:", initialvalue="50051")
            porta = int(porta_input.strip()) if porta_input and porta_input.strip().isdigit() else 50051
            root.destroy()
        except Exception:
            ip, porta = "127.0.0.1", 50051
    else:
        ip    = args.ip
        porta = args.port

    print(f"\n[CONECTANDO] {ip}:{porta} via gRPC...")

    # ── Conecta ao servidor ────────────────────────────────────────
    cliente = ClienteGrpc(ip, porta)

    try:
        resp = cliente.conectar()
    except grpc.RpcError as e:
        print(f"[ERRO] Não foi possível conectar ao servidor: {e.details()}")
        input("Pressione ENTER para sair...")
        sys.exit(1)

    if not resp.sucesso:
        print(f"[ERRO] {resp.mensagem}")
        input("Pressione ENTER para sair...")
        sys.exit(1)

    cliente.id_jogador = resp.id_jogador
    print(f"[OK] {resp.mensagem}")
    print(f"[OK] Você é o Jogador {cliente.id_jogador}")

    # ── Pygame ────────────────────────────────────────────────────
    pygame.init()
    tela  = pygame.display.set_mode((LARGURA, ALTURA))
    pygame.display.set_caption(f"Pong gRPC — Jogador {cliente.id_jogador}")
    clock = pygame.time.Clock()
    fontes = (
        pygame.font.SysFont("Arial", 48, bold=True),  # fg
        pygame.font.SysFont("Arial", 28, bold=True),  # fm
        pygame.font.SysFont("Arial", 16),              # fp
    )

    rodando = True
    print("[OK] Pygame iniciado. Aguardando início do jogo...\n")

    # ── Game Loop ─────────────────────────────────────────────────
    try:
        while rodando:
            # Eventos de janela
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    rodando = False
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    rodando = False
            if not rodando:
                break

            # ── Input do jogador ──────────────────────────────────
            teclas = pygame.key.get_pressed()
            direcao = "parado"
            if cliente.id_jogador == 1:
                if teclas[pygame.K_w]:
                    direcao = "cima"
                elif teclas[pygame.K_s]:
                    direcao = "baixo"
            else:
                if teclas[pygame.K_UP]:
                    direcao = "cima"
                elif teclas[pygame.K_DOWN]:
                    direcao = "baixo"

            # ── MoverRaquete (invocação remota) ───────────────────
            # Enviamos mesmo "parado" para manter o heartbeat ativo
            cliente.mover_raquete(direcao)

            # ── ObterEstado (polling remoto) ───────────────────────
            estado = cliente.obter_estado()

            # ── Renderização ───────────────────────────────────────
            if estado is None:
                # Nenhum estado ainda: tela preta com mensagem
                tela.fill(PRETO)
                msg = fontes[1].render("Conectando ao servidor...", True, CINZA)
                tela.blit(msg, msg.get_rect(center=(LARGURA // 2, ALTURA // 2)))

            elif estado.status == "aguardando":
                desenhar_aguardando(tela, fontes, "gRPC", ip, porta)

            elif estado.status == "jogando":
                desenhar_jogo(tela, estado, cliente, fontes, cliente.id_jogador)

            elif estado.status == "encerrado":
                desenhar_fim(tela, estado, fontes, cliente.id_jogador)
                pygame.display.flip()
                # Aguarda ESC ou fechamento
                esperando = True
                while esperando:
                    for ev in pygame.event.get():
                        if ev.type == pygame.QUIT:
                            esperando = False; rodando = False
                        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                            esperando = False; rodando = False
                    clock.tick(10)
                break

            pygame.display.flip()
            clock.tick(FPS)

    except KeyboardInterrupt:
        pass
    finally:
        cliente.fechar()
        pygame.quit()
        print("\n[FIM] Cliente encerrado.")


if __name__ == "__main__":
    main()
