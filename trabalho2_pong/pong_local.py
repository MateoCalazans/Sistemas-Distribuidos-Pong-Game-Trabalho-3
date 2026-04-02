"""
pong_local.py — Pong Local (2 jogadores na mesma máquina)
==========================================================
Versão offline para teste rápido. Não usa rede.
Jogador 1: W/S | Jogador 2: Setas cima/baixo.
Toda a lógica roda localmente no mesmo processo.

Uso: python pong_local.py
"""

import sys

try:
    import pygame
except ImportError:
    print("ERRO: pip install pygame"); sys.exit(1)

# ======================================================================
# CONSTANTES
# ======================================================================

LARGURA, ALTURA, FPS = 800, 600, 60
PRETO, BRANCO, CINZA = (0,0,0), (255,255,255), (100,100,100)
VERDE, VERMELHO, AMARELO, AZUL = (0,200,100), (200,50,50), (255,200,0), (50,100,200)

PADDLE_LARGURA, PADDLE_ALTURA = 15, 100
BOLA_TAMANHO = 15
PADDLE_VEL = 6
BOLA_VEL = 5

PADDLE1_X = 30
PADDLE2_X = LARGURA - 30 - PADDLE_LARGURA


def main():
    pygame.init()
    tela = pygame.display.set_mode((LARGURA, ALTURA))
    pygame.display.set_caption("Pong Local — 2 Jogadores")
    clock = pygame.time.Clock()

    # Fontes
    fonte_grande = pygame.font.SysFont("Arial", 48, bold=True)
    fonte_media = pygame.font.SysFont("Arial", 24)
    fonte_pequena = pygame.font.SysFont("Arial", 16)

    # --- Estado do jogo ---
    bola_x = LARGURA // 2
    bola_y = ALTURA // 2
    bola_vel_x = BOLA_VEL
    bola_vel_y = BOLA_VEL
    paddle1_y = ALTURA // 2 - PADDLE_ALTURA // 2
    paddle2_y = ALTURA // 2 - PADDLE_ALTURA // 2
    placar1 = 0
    placar2 = 0

    rodando = True

    print("=" * 50)
    print("  PONG LOCAL — 2 Jogadores")
    print("=" * 50)
    print("  Jogador 1: W (subir) / S (descer)")
    print("  Jogador 2: Seta Cima / Seta Baixo")
    print("  ESC para sair")
    print("=" * 50)

    while rodando:
        # --- Eventos ---
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                rodando = False
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                rodando = False

        if not rodando:
            break

        # --- Input dos jogadores ---
        teclas = pygame.key.get_pressed()

        # Jogador 1: W/S
        if teclas[pygame.K_w]:
            paddle1_y = max(0, paddle1_y - PADDLE_VEL)
        if teclas[pygame.K_s]:
            paddle1_y = min(ALTURA - PADDLE_ALTURA, paddle1_y + PADDLE_VEL)

        # Jogador 2: Setas
        if teclas[pygame.K_UP]:
            paddle2_y = max(0, paddle2_y - PADDLE_VEL)
        if teclas[pygame.K_DOWN]:
            paddle2_y = min(ALTURA - PADDLE_ALTURA, paddle2_y + PADDLE_VEL)

        # --- Física da bola ---
        bola_x += bola_vel_x
        bola_y += bola_vel_y

        # Colisão com topo/baixo
        if bola_y <= 0:
            bola_y = 0
            bola_vel_y = abs(bola_vel_y)
        elif bola_y >= ALTURA - BOLA_TAMANHO:
            bola_y = ALTURA - BOLA_TAMANHO
            bola_vel_y = -abs(bola_vel_y)

        # Colisão com paddle 1 (esquerdo)
        if (bola_x <= PADDLE1_X + PADDLE_LARGURA and
            bola_x >= PADDLE1_X and
            bola_y + BOLA_TAMANHO >= paddle1_y and
            bola_y <= paddle1_y + PADDLE_ALTURA):
            bola_vel_x = abs(bola_vel_x)
            bola_x = PADDLE1_X + PADDLE_LARGURA + 1

        # Colisão com paddle 2 (direito)
        if (bola_x + BOLA_TAMANHO >= PADDLE2_X and
            bola_x + BOLA_TAMANHO <= PADDLE2_X + PADDLE_LARGURA and
            bola_y + BOLA_TAMANHO >= paddle2_y and
            bola_y <= paddle2_y + PADDLE_ALTURA):
            bola_vel_x = -abs(bola_vel_x)
            bola_x = PADDLE2_X - BOLA_TAMANHO - 1

        # Pontos
        if bola_x < 0:
            placar2 += 1
            print(f"[PLACAR] {placar1} x {placar2}")
            bola_x, bola_y = LARGURA // 2, ALTURA // 2
            bola_vel_x = -bola_vel_x

        elif bola_x > LARGURA:
            placar1 += 1
            print(f"[PLACAR] {placar1} x {placar2}")
            bola_x, bola_y = LARGURA // 2, ALTURA // 2
            bola_vel_x = -bola_vel_x

        # --- Desenho ---
        tela.fill(PRETO)

        # Linha central tracejada
        for y in range(0, ALTURA, 20):
            pygame.draw.rect(tela, CINZA, (LARGURA//2 - 2, y, 4, 10))

        # Paddles
        pygame.draw.rect(tela, AZUL, (PADDLE1_X, paddle1_y, PADDLE_LARGURA, PADDLE_ALTURA))
        pygame.draw.rect(tela, VERMELHO, (PADDLE2_X, paddle2_y, PADDLE_LARGURA, PADDLE_ALTURA))

        # Bola
        pygame.draw.rect(tela, BRANCO, (int(bola_x), int(bola_y), BOLA_TAMANHO, BOLA_TAMANHO))

        # Placar
        txt = fonte_grande.render(f"{placar1}  :  {placar2}", True, BRANCO)
        tela.blit(txt, txt.get_rect(center=(LARGURA//2, 40)))
        tela.blit(fonte_pequena.render("Jogador 1 (W/S)", True, AZUL), (LARGURA//4 - 50, 15))
        tela.blit(fonte_pequena.render("Jogador 2 (↑/↓)", True, VERMELHO), (3*LARGURA//4 - 50, 15))

        # Instruções no rodapé
        tela.blit(fonte_pequena.render("ESC para sair | Modo: LOCAL", True, CINZA), (10, ALTURA - 25))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    print("[FIM] Jogo encerrado.")


if __name__ == "__main__":
    main()
