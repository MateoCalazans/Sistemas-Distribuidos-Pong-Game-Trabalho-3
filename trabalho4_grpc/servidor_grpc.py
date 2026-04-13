"""
servidor_grpc.py — Servidor Autoritativo do Pong via gRPC
==========================================================
Equivalente ao "Authoritative Server" descrito no enunciado.

Responsabilidades:
  • Manter o estado canônico do jogo (posição da bola e raquetes, placar)
  • Rodar a física (colisões, pontuação) em thread separada a 60 fps
  • Expor 3 métodos RPC:
      ConectarJogador()  → retorna ID 1 ou 2
      MoverRaquete()     → atualiza direcao desejada de um paddle
      ObterEstado()      → retorna snapshot do estado atual
  • Proteger o estado compartilhado com RLock (thread safety)
  • Detectar desconexão via watchdog e conceder W.O. ao rival

Uso:
    python servidor_grpc.py
    python servidor_grpc.py --port 50051

Autores: Guilherme Felipe, Jeane Mirele, Caio Cesar, Mateo Calazans
"""

import argparse
import threading
import time
import math
import concurrent.futures
import sys
import os

# Adds the current directory to sys.path so the generated pb2 files are accessible
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import grpc
import pong_pb2
import pong_pb2_grpc


# ======================================================================
# CONSTANTES DO JOGO
# ======================================================================

LARGURA  = 800
ALTURA   = 600
FPS      = 60
TEMPO_FRAME = 1.0 / FPS

PADDLE_LARGURA = 15
PADDLE_ALTURA  = 100
PADDLE_VEL     = 6          # Pixels por frame

BOLA_TAM       = 15
BOLA_VEL_X     = 5
BOLA_VEL_Y     = 5

PADDLE1_X = 30
PADDLE2_X = LARGURA - 30 - PADDLE_LARGURA

PLACAR_VITORIA = 7          # Primeiro a 7 pontos vence
TIMEOUT_DESCONEXAO = 10.0   # Segundos sem heartbeat → W.O.


# ======================================================================
# ESTADO DO JOGO (compartilhado entre threads)
# ======================================================================

class EstadoJogo:
    """
    Encapsula todo o estado mutável do jogo.
    Usa RLock (reentrant lock) para que a mesma thread possa adquirir
    o lock múltiplas vezes sem deadlock (útil em callbacks aninhados).

    Acesso ao estado:
        with estado.lock:
            estado.bola_x = ...
    """
    def __init__(self):
        self.lock = threading.RLock()

        # ── Física ──────────────────────────────────────────────────
        self.bola_x    = float(LARGURA // 2)
        self.bola_y    = float(ALTURA  // 2)
        self.bola_vx   = float(BOLA_VEL_X)
        self.bola_vy   = float(BOLA_VEL_Y)

        self.raquete1_y = float(ALTURA // 2 - PADDLE_ALTURA // 2)
        self.raquete2_y = float(ALTURA // 2 - PADDLE_ALTURA // 2)

        # Direção desejada de cada paddle (escrita pelo RPC MoverRaquete)
        self.direcao1 = "parado"
        self.direcao2 = "parado"

        # ── Placar ───────────────────────────────────────────────────
        self.placar1 = 0
        self.placar2 = 0

        # ── Controle de partida ──────────────────────────────────────
        # "aguardando" | "jogando" | "encerrado"
        self.status   = "aguardando"
        self.vencedor = 0   # 0=none, 1=P1, 2=P2
        self.motivo   = ""  # "placar" ou "wo"

        # Número de sequência do frame (monotonicamente crescente)
        self.seq = 0

        # ── Heartbeat dos clientes ────────────────────────────────────
        # Dicionário {id_jogador: timestamp_ultimo_contato}
        self.heartbeat = {}

        # ID dos jogadores conectados (conjunto)
        self.conectados = set()


# ======================================================================
# FÍSICA DO JOGO
# ======================================================================

def _resetar_bola(estado: EstadoJogo):
    """Reposiciona a bola no centro e inverte a direção horizontal."""
    estado.bola_x  = float(LARGURA // 2)
    estado.bola_y  = float(ALTURA  // 2)
    estado.bola_vx = -estado.bola_vx
    # Mantém sinal da componente vertical, mas reseta magnitude
    sinal_y = 1 if estado.bola_vy >= 0 else -1
    estado.bola_vy = sinal_y * BOLA_VEL_Y


def _atualizar_fisica(estado: EstadoJogo):
    """
    Roda um tick de física (chamado a 60fps).
    Deve ser chamado com o lock JÁ ADQUIRIDO.

    Sequência:
      1. Move paddles conforme direcao desejada
      2. Move bola
      3. Rebate nas paredes (topo/baixo)
      4. Colisão com raquetes
      5. Verifica pontuação
      6. Verifica vitória
    """
    # ── 1. Paddles ─────────────────────────────────────────────────
    if estado.direcao1 == "cima":
        estado.raquete1_y = max(0.0, estado.raquete1_y - PADDLE_VEL)
    elif estado.direcao1 == "baixo":
        estado.raquete1_y = min(float(ALTURA - PADDLE_ALTURA), estado.raquete1_y + PADDLE_VEL)

    if estado.direcao2 == "cima":
        estado.raquete2_y = max(0.0, estado.raquete2_y - PADDLE_VEL)
    elif estado.direcao2 == "baixo":
        estado.raquete2_y = min(float(ALTURA - PADDLE_ALTURA), estado.raquete2_y + PADDLE_VEL)

    # ── 2. Bola ────────────────────────────────────────────────────
    estado.bola_x += estado.bola_vx
    estado.bola_y += estado.bola_vy

    # ── 3. Paredes (topo e baixo) ──────────────────────────────────
    if estado.bola_y <= 0:
        estado.bola_y = 0
        estado.bola_vy = abs(estado.bola_vy)
    elif estado.bola_y >= ALTURA - BOLA_TAM:
        estado.bola_y = float(ALTURA - BOLA_TAM)
        estado.bola_vy = -abs(estado.bola_vy)

    # ── 4. Colisão com raquetes ────────────────────────────────────
    bx, by = estado.bola_x, estado.bola_y

    # Raquete 1 (esquerda)
    if (bx <= PADDLE1_X + PADDLE_LARGURA and
            bx >= PADDLE1_X and
            by + BOLA_TAM >= estado.raquete1_y and
            by <= estado.raquete1_y + PADDLE_ALTURA):
        estado.bola_vx = abs(estado.bola_vx)
        estado.bola_x  = float(PADDLE1_X + PADDLE_LARGURA + 1)

    # Raquete 2 (direita)
    if (bx + BOLA_TAM >= PADDLE2_X and
            bx + BOLA_TAM <= PADDLE2_X + PADDLE_LARGURA and
            by + BOLA_TAM >= estado.raquete2_y and
            by <= estado.raquete2_y + PADDLE_ALTURA):
        estado.bola_vx = -abs(estado.bola_vx)
        estado.bola_x  = float(PADDLE2_X - BOLA_TAM - 1)

    # ── 5. Pontuação ───────────────────────────────────────────────
    if estado.bola_x < 0:
        estado.placar2 += 1
        print(f"[PLACAR] P1: {estado.placar1}  P2: {estado.placar2}  (P2 marcou)")
        _resetar_bola(estado)
    elif estado.bola_x > LARGURA:
        estado.placar1 += 1
        print(f"[PLACAR] P1: {estado.placar1}  P2: {estado.placar2}  (P1 marcou)")
        _resetar_bola(estado)

    # ── 6. Vitória por placar ─────────────────────────────────────
    if estado.placar1 >= PLACAR_VITORIA:
        estado.status   = "encerrado"
        estado.vencedor = 1
        estado.motivo   = "placar"
        print(f"[FIM] Jogador 1 venceu! Placar final: {estado.placar1} x {estado.placar2}")
    elif estado.placar2 >= PLACAR_VITORIA:
        estado.status   = "encerrado"
        estado.vencedor = 2
        estado.motivo   = "placar"
        print(f"[FIM] Jogador 2 venceu! Placar final: {estado.placar1} x {estado.placar2}")

    estado.seq += 1


# ======================================================================
# THREADS DE BACKGROUND
# ======================================================================

def thread_fisica(estado: EstadoJogo):
    """
    Loop de física rodando a 60fps no servidor.

    GESTÃO DE LATÊNCIA:
      A física roda independentemente da velocidade de polling dos clientes.
      Mesmo que um cliente demore 200ms para invocar ObterEstado(), a bola
      continua sendo calculada corretamente aqui no servidor.
      O cliente simplesmente receberá um estado "atrasado" mas preciso.
    """
    print("[FÍSICA] Thread de física iniciada (60fps)")
    while True:
        inicio = time.perf_counter()

        with estado.lock:
            if estado.status == "jogando":
                _atualizar_fisica(estado)
            elif estado.status == "encerrado":
                break   # Encerra a thread quando jogo terminar

        elapsed = time.perf_counter() - inicio
        sleep_time = TEMPO_FRAME - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

    print("[FÍSICA] Thread de física encerrada.")


def thread_watchdog(estado: EstadoJogo):
    """
    Watchdog de desconexão.

    DETECÇÃO DE DESCONEXÃO:
      A cada 1 segundo, verifica se cada jogador conectado deu algum
      sinal de vida (MoverRaquete ou ObterEstado) nos últimos
      TIMEOUT_DESCONEXAO segundos.

      Se não, e a partida está em andamento, declara W.O. para o rival.
    """
    print(f"[WATCHDOG] Monitorando desconexões (timeout={TIMEOUT_DESCONEXAO}s)")
    while True:
        time.sleep(1.0)
        agora = time.time()

        with estado.lock:
            if estado.status not in ("jogando",):
                if estado.status == "encerrado":
                    break
                continue

            for id_jogador in list(estado.conectados):
                ultimo = estado.heartbeat.get(id_jogador, agora)
                if agora - ultimo > TIMEOUT_DESCONEXAO:
                    rival = 2 if id_jogador == 1 else 1
                    estado.status   = "encerrado"
                    estado.vencedor = rival
                    estado.motivo   = "wo"
                    print(f"[WATCHDOG] Jogador {id_jogador} sem resposta por "
                          f"{TIMEOUT_DESCONEXAO}s → W.O. → Jogador {rival} vence!")
                    break

    print("[WATCHDOG] Thread watchdog encerrada.")


# ======================================================================
# IMPLEMENTAÇÃO DO SERVIÇO gRPC
# ======================================================================

class PongServicer(pong_pb2_grpc.PongServiceServicer):
    """
    Implementa os 3 métodos RPC definidos em pong.proto.

    CONTROLE DE CONCORRÊNCIA:
      O gRPC usa um thread pool para servir requisições.
      Múltiplas chamadas RPC podem chegar simultaneamente
      (P1 move, P2 move, P1 pede estado, P2 pede estado).
      Todo acesso ao estado_jogo é protegido por estado.lock.
    """

    def __init__(self):
        self.estado = EstadoJogo()
        self._proximo_id = 1
        self._id_lock    = threading.Lock()

    # ── RPC: ConectarJogador ────────────────────────────────────────
    def ConectarJogador(self, request, context):
        """
        Registra um jogador e retorna seu ID (1 ou 2).
        Bloqueia se o jogo já tiver 2 jogadores.
        Quando o 2º jogador conecta, inicia a partida.
        """
        with self._id_lock:
            if len(self.estado.conectados) >= 2:
                return pong_pb2.ConectarResponse(
                    sucesso=False,
                    id_jogador=0,
                    mensagem="Jogo cheio! Máximo de 2 jogadores."
                )
            id_jogador = self._proximo_id
            self._proximo_id += 1

        with self.estado.lock:
            self.estado.conectados.add(id_jogador)
            self.estado.heartbeat[id_jogador] = time.time()
            num_conectados = len(self.estado.conectados)

        print(f"[CONEXÃO] Jogador {id_jogador} conectou. ({num_conectados}/2)")

        if num_conectados == 2:
            # Ambos conectados: inicia física e watchdog
            with self.estado.lock:
                self.estado.status = "jogando"
            print("[JOGO] Dois jogadores conectados → Iniciando partida!")

            t_fisica   = threading.Thread(target=thread_fisica,   args=(self.estado,), daemon=True)
            t_watchdog = threading.Thread(target=thread_watchdog, args=(self.estado,), daemon=True)
            t_fisica.start()
            t_watchdog.start()

            mensagem = f"Bem-vindo, Jogador {id_jogador}! Partida iniciada!"
        else:
            mensagem = f"Você é o Jogador {id_jogador}. Aguardando Jogador 2..."

        return pong_pb2.ConectarResponse(
            sucesso=True,
            id_jogador=id_jogador,
            mensagem=mensagem
        )

    # ── RPC: MoverRaquete ───────────────────────────────────────────
    def MoverRaquete(self, request, context):
        """
        Atualiza a direção desejada do paddle de um jogador.
        A física aplicará o movimento no próximo tick do loop.

        THREAD SAFETY: lock protege escrita em direcao1/direcao2.
        """
        id_jogador = request.id_jogador
        direcao    = request.direcao

        with self.estado.lock:
            # Atualiza heartbeat (prova de vida do cliente)
            self.estado.heartbeat[id_jogador] = time.time()

            if self.estado.status != "jogando":
                return pong_pb2.MoverResponse(sucesso=False)

            if id_jogador == 1:
                self.estado.direcao1 = direcao
            elif id_jogador == 2:
                self.estado.direcao2 = direcao

        return pong_pb2.MoverResponse(sucesso=True)

    # ── RPC: ObterEstado ───────────────────────────────────────────
    def ObterEstado(self, request, context):
        """
        Retorna um snapshot do estado atual do jogo.
        Chamado em polling pelo cliente a ~60fps.

        THREAD SAFETY: lock garante leitura consistente —
        não leremos bola_x e bola_y de frames diferentes.
        """
        id_jogador = request.id_jogador

        with self.estado.lock:
            # Atualiza heartbeat
            if id_jogador in self.estado.conectados:
                self.estado.heartbeat[id_jogador] = time.time()

            return pong_pb2.EstadoResponse(
                bola_x     = self.estado.bola_x,
                bola_y     = self.estado.bola_y,
                raquete1_y = self.estado.raquete1_y,
                raquete2_y = self.estado.raquete2_y,
                placar1    = self.estado.placar1,
                placar2    = self.estado.placar2,
                status     = self.estado.status,
                vencedor   = self.estado.vencedor,
                motivo     = self.estado.motivo,
                seq        = self.estado.seq,
            )


# ======================================================================
# MAIN
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Servidor gRPC do Pong")
    parser.add_argument("--port", type=int, default=50051,
                        help="Porta do servidor gRPC (padrão: 50051)")
    args = parser.parse_args()

    print("=" * 55)
    print("   SERVIDOR PONG — gRPC (Authoritative Server)")
    print("=" * 55)
    print(f"  Porta:          {args.port}")
    print(f"  FPS (física):   {FPS}")
    print(f"  Timeout W.O.:   {TIMEOUT_DESCONEXAO}s")
    print(f"  Placar vitória: Primeiro a {PLACAR_VITORIA} pontos")
    print("=" * 55)

    # Thread pool: permite múltiplos RPCs simultâneos (P1 move + P2 move + estados)
    servidor = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=10))
    servicer = PongServicer()
    pong_pb2_grpc.add_PongServiceServicer_to_server(servicer, servidor)

    servidor.add_insecure_port(f"[::]:{args.port}")
    servidor.start()

    print(f"\n[OK] Servidor escutando em 0.0.0.0:{args.port}")
    print("[AGUARDANDO] Esperando 2 jogadores se conectarem...\n")
    print("Pressione Ctrl+C para encerrar\n")

    try:
        servidor.wait_for_termination()
    except KeyboardInterrupt:
        print("\n[FIM] Servidor encerrado pelo usuário.")
        servidor.stop(grace=2)


if __name__ == "__main__":
    main()
