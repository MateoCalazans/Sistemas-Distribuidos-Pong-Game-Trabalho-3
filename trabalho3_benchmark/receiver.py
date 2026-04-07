"""
receiver.py — Receptor do Benchmark TCP vs UDP
================================================
Servidor que escuta conexões TCP e UDP simultaneamente.

Protocolo binário:
  Header (12 bytes): seq(4) + tamanho(4) + timestamp(4)
  Payload: bytes 'X' para completar o tamanho

TCP: recebe mensagens com length-prefix (4 bytes tamanho + dados)
UDP: recebe datagramas, envia ACK (4 bytes com seq)
     Suporta --loss para simular perda de pacotes (equivalente ao tc qdisc)

Uso:
    python receiver.py                   (sem perda simulada)
    python receiver.py --loss 10         (simula 10% de perda no UDP)
"""

import socket
import struct
import threading
import time
import argparse
import random


# ======================================================================
# CONSTANTES
# ======================================================================

BUFFER_SIZE = 65536
TIMEOUT_RODADA = 5.0

# Header: seq(4) + tamanho(4) + timestamp(4) = 12 bytes
HEADER_FORMAT = "!III"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


# ======================================================================
# RECEPTOR TCP
# ======================================================================

def receptor_tcp(porta):
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(("0.0.0.0", porta))
    servidor.listen(5)
    print(f"[TCP] Escutando na porta {porta}")

    while True:
        conn, addr = servidor.accept()
        print(f"\n[TCP] Conexão de {addr}")
        t = threading.Thread(target=tratar_conexao_tcp, args=(conn, addr), daemon=True)
        t.start()


def recv_exato(conn, n):
    """Recebe exatamente n bytes do socket TCP."""
    dados = b""
    while len(dados) < n:
        parte = conn.recv(n - len(dados))
        if not parte:
            return None
        dados += parte
    return dados


def tratar_conexao_tcp(conn, addr):
    """Cada mensagem: [4 bytes tamanho][pacote]"""
    pacotes_recebidos = []
    conn.settimeout(TIMEOUT_RODADA)

    try:
        while True:
            try:
                header_len = recv_exato(conn, 4)
                if header_len is None:
                    break
                msg_len = struct.unpack("!I", header_len)[0]
                dados = recv_exato(conn, msg_len)
                if dados is None:
                    break
                if len(dados) >= HEADER_SIZE:
                    seq, tamanho, ts_ms = struct.unpack(HEADER_FORMAT, dados[:HEADER_SIZE])
                    pacotes_recebidos.append((seq, tamanho, ts_ms))
            except socket.timeout:
                break
    except Exception as e:
        print(f"[TCP] Erro: {e}")
    finally:
        conn.close()

    imprimir_estatisticas("TCP", pacotes_recebidos)


# ======================================================================
# RECEPTOR UDP
# ======================================================================

def receptor_udp(porta, taxa_perda):
    """
    Escuta pacotes UDP e envia ACK.
    Se taxa_perda > 0, simula perda ignorando pacotes aleatoriamente
    (equivalente a 'tc qdisc add dev lo root netem loss X%' no Linux).
    """
    servidor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servidor.bind(("0.0.0.0", porta))
    servidor.settimeout(TIMEOUT_RODADA)

    if taxa_perda > 0:
        print(f"[UDP] Escutando na porta {porta} (SIMULANDO {taxa_perda}% de perda)")
    else:
        print(f"[UDP] Escutando na porta {porta}")

    while True:
        pacotes_recebidos = []
        pacotes_perdidos_sim = 0
        rodada_ativa = False

        while True:
            try:
                dados, addr = servidor.recvfrom(BUFFER_SIZE)

                if len(dados) >= HEADER_SIZE:
                    seq, tamanho, ts_ms = struct.unpack(HEADER_FORMAT, dados[:HEADER_SIZE])

                    if not rodada_ativa:
                        rodada_ativa = True
                        print(f"\n[UDP] Recebendo pacotes de {addr}...")

                    # Simula perda: ignora o pacote (não envia ACK)
                    if taxa_perda > 0 and random.random() < (taxa_perda / 100.0):
                        pacotes_perdidos_sim += 1
                        continue  # NÃO envia ACK → sender vai considerar como perdido

                    pacotes_recebidos.append((seq, tamanho, ts_ms))

                    # Envia ACK: 4 bytes com seq
                    ack = struct.pack("!I", seq)
                    servidor.sendto(ack, addr)

            except socket.timeout:
                if rodada_ativa:
                    imprimir_estatisticas("UDP", pacotes_recebidos, pacotes_perdidos_sim)
                    pacotes_recebidos = []
                    pacotes_perdidos_sim = 0
                    rodada_ativa = False
                continue
            except Exception as e:
                print(f"[UDP] Erro: {e}")
                continue


# ======================================================================
# ESTATÍSTICAS
# ======================================================================

def imprimir_estatisticas(protocolo, pacotes, perdidos_sim=0):
    if not pacotes:
        print(f"\n[{protocolo}] Nenhum pacote recebido nesta rodada.")
        return

    total = len(pacotes)
    seqs = [p[0] for p in pacotes]
    seq_min, seq_max = min(seqs), max(seqs)
    esperados = seq_max - seq_min + 1

    fora_de_ordem = sum(1 for i in range(1, len(seqs)) if seqs[i] < seqs[i-1])
    perdidos = esperados - total
    taxa_perda = (perdidos / esperados * 100) if esperados > 0 else 0
    tamanho = pacotes[0][1] if pacotes else 0

    print(f"\n{'='*50}")
    print(f"  ESTATÍSTICAS — {protocolo}")
    print(f"{'='*50}")
    print(f"  Tamanho do pacote: {tamanho} bytes")
    print(f"  Pacotes recebidos: {total}")
    if perdidos_sim > 0:
        print(f"  Perdidos (simulado): {perdidos_sim}")
    print(f"  Fora de ordem:     {fora_de_ordem}")
    print(f"{'='*50}")


# ======================================================================
# MAIN
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Receptor Benchmark TCP/UDP")
    parser.add_argument("--port", type=int, default=6000,
                        help="Porta base (TCP=port, UDP=port+1). Padrão: 6000")
    parser.add_argument("--loss", type=float, default=0,
                        help="Simular perda de pacotes UDP (%%). Ex: --loss 10 = 10%% de perda")
    args = parser.parse_args()

    porta_tcp = args.port
    porta_udp = args.port + 1

    print("=" * 55)
    print("  RECEPTOR — Benchmark TCP vs UDP")
    print("=" * 55)
    print(f"  TCP na porta {porta_tcp}")
    print(f"  UDP na porta {porta_udp}")
    if args.loss > 0:
        print(f"  ⚠️  Simulação de perda UDP: {args.loss}%")
    print(f"  Protocolo: binário ({HEADER_SIZE} bytes header)")
    print("  Pressione Ctrl+C para encerrar")
    print("=" * 55)

    t_tcp = threading.Thread(target=receptor_tcp, args=(porta_tcp,), daemon=True)
    t_udp = threading.Thread(target=receptor_udp, args=(porta_udp, args.loss), daemon=True)
    t_tcp.start()
    t_udp.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[FIM] Receptor encerrado.")


if __name__ == "__main__":
    main()
