"""
receiver.py — Receptor do Benchmark TCP vs UDP
================================================
Servidor que escuta conexões TCP e UDP simultaneamente.
Para cada pacote: registra seq, tamanho, timestamp.
UDP: envia ACK manual com número de sequência.
No final de cada rodada: imprime estatísticas.

Uso: python receiver.py [--port PORTA]
"""

import socket
import json
import threading
import time
import argparse


# ======================================================================
# CONSTANTES
# ======================================================================

BUFFER_SIZE = 65536          # Tamanho máximo do buffer de recebimento
TIMEOUT_RODADA = 5.0         # Segundos sem pacote = fim da rodada


# ======================================================================
# RECEPTOR TCP
# ======================================================================

def receptor_tcp(porta):
    """
    Thread que escuta conexões TCP.
    Para cada conexão, recebe todos os pacotes de uma rodada,
    registra estatísticas e imprime ao final.
    """
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind(("0.0.0.0", porta))
    servidor.listen(5)
    print(f"[TCP] Escutando na porta {porta}")

    while True:
        conn, addr = servidor.accept()
        print(f"\n[TCP] Conexão de {addr}")
        # Cada conexão é tratada em sua própria thread
        t = threading.Thread(target=tratar_conexao_tcp, args=(conn, addr), daemon=True)
        t.start()


def tratar_conexao_tcp(conn, addr):
    """
    Trata uma conexão TCP individual.
    Recebe pacotes até o cliente fechar a conexão.
    Cada pacote é um JSON com: seq, tamanho, dados, timestamp.
    """
    pacotes_recebidos = []       # Lista de (seq, tamanho, timestamp)
    buffer = b""

    conn.settimeout(TIMEOUT_RODADA)

    try:
        while True:
            try:
                dados = conn.recv(BUFFER_SIZE)
                if not dados:
                    break  # Conexão fechada pelo cliente
                buffer += dados

                # Processa todas as mensagens completas (delimitadas por \n)
                while b"\n" in buffer:
                    msg, buffer = buffer.split(b"\n", 1)
                    try:
                        pacote = json.loads(msg.decode("utf-8"))
                        seq = pacote.get("seq", -1)
                        tamanho = pacote.get("tamanho", 0)
                        timestamp = pacote.get("timestamp", 0)
                        pacotes_recebidos.append((seq, tamanho, timestamp))
                    except json.JSONDecodeError:
                        pass

            except socket.timeout:
                break

    except Exception as e:
        print(f"[TCP] Erro: {e}")
    finally:
        conn.close()

    # Imprime estatísticas da rodada
    imprimir_estatisticas("TCP", pacotes_recebidos)


# ======================================================================
# RECEPTOR UDP
# ======================================================================

def receptor_udp(porta):
    """
    Thread que escuta pacotes UDP.
    Para cada pacote recebido: registra e envia ACK de volta.
    Usa timeout para detectar fim de rodada.
    """
    servidor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servidor.bind(("0.0.0.0", porta))
    servidor.settimeout(TIMEOUT_RODADA)
    print(f"[UDP] Escutando na porta {porta}")

    while True:
        pacotes_recebidos = []  # Lista de (seq, tamanho, timestamp)
        rodada_ativa = False

        while True:
            try:
                dados, addr = servidor.recvfrom(BUFFER_SIZE)

                try:
                    pacote = json.loads(dados.decode("utf-8"))
                    seq = pacote.get("seq", -1)
                    tamanho = pacote.get("tamanho", 0)
                    timestamp = pacote.get("timestamp", 0)

                    # Registra o pacote
                    pacotes_recebidos.append((seq, tamanho, timestamp))

                    if not rodada_ativa:
                        rodada_ativa = True
                        print(f"\n[UDP] Recebendo pacotes de {addr}...")

                    # Envia ACK manual com o número de sequência
                    ack = json.dumps({"ack": seq}).encode("utf-8")
                    servidor.sendto(ack, addr)

                except json.JSONDecodeError:
                    pass

            except socket.timeout:
                # Se a rodada estava ativa e parou de receber, imprime stats
                if rodada_ativa:
                    imprimir_estatisticas("UDP", pacotes_recebidos)
                    pacotes_recebidos = []
                    rodada_ativa = False
                # Continua esperando novos pacotes
                continue


# ======================================================================
# ESTATÍSTICAS
# ======================================================================

def imprimir_estatisticas(protocolo, pacotes):
    """
    Calcula e imprime estatísticas de uma rodada:
    - Total de pacotes recebidos
    - Pacotes fora de ordem
    - Taxa de perda (baseada nos números de sequência)
    """
    if not pacotes:
        print(f"\n[{protocolo}] Nenhum pacote recebido nesta rodada.")
        return

    total = len(pacotes)
    seqs = [p[0] for p in pacotes]

    # Calcula o esperado (do menor ao maior seq recebido)
    seq_min = min(seqs)
    seq_max = max(seqs)
    esperados = seq_max - seq_min + 1

    # Pacotes fora de ordem: quantos não estão em ordem crescente
    fora_de_ordem = 0
    for i in range(1, len(seqs)):
        if seqs[i] < seqs[i-1]:
            fora_de_ordem += 1

    # Taxa de perda
    perdidos = esperados - total
    taxa_perda = (perdidos / esperados * 100) if esperados > 0 else 0

    tamanho = pacotes[0][1] if pacotes else 0

    print(f"\n{'='*50}")
    print(f"  ESTATÍSTICAS — {protocolo}")
    print(f"{'='*50}")
    print(f"  Tamanho do pacote: {tamanho} bytes")
    print(f"  Pacotes esperados: {esperados}")
    print(f"  Pacotes recebidos: {total}")
    print(f"  Pacotes perdidos:  {perdidos}")
    print(f"  Fora de ordem:     {fora_de_ordem}")
    print(f"  Taxa de perda:     {taxa_perda:.1f}%")
    print(f"{'='*50}")


# ======================================================================
# MAIN
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Receptor Benchmark TCP/UDP")
    parser.add_argument("--port", type=int, default=6000,
                        help="Porta base (TCP=port, UDP=port+1). Padrão: 6000")
    args = parser.parse_args()

    porta_tcp = args.port
    porta_udp = args.port + 1

    print("=" * 50)
    print("  RECEPTOR — Benchmark TCP vs UDP")
    print("=" * 50)
    print(f"  TCP na porta {porta_tcp}")
    print(f"  UDP na porta {porta_udp}")
    print("  Pressione Ctrl+C para encerrar")
    print("=" * 50)

    # Inicia ambos receptores em threads separadas
    t_tcp = threading.Thread(target=receptor_tcp, args=(porta_tcp,), daemon=True)
    t_udp = threading.Thread(target=receptor_udp, args=(porta_udp,), daemon=True)
    t_tcp.start()
    t_udp.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[FIM] Receptor encerrado.")


if __name__ == "__main__":
    main()
