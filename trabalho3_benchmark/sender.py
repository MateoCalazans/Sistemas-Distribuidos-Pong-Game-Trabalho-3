"""
sender.py — Benchmark automático TCP vs UDP
=============================================
Envia N pacotes de tamanho T do cliente para o servidor.
Mede taxa de transmissão (Mbps), tempo, perda e ordem.
Salva resultados em CSV e gera gráfico comparativo.

Uso:
    python sender.py                        (TCP + UDP, sem perda)
    python sender.py --mode tcp             (só TCP)
    python sender.py --mode udp             (só UDP)
    python sender.py --host 192.168.1.10    (IP remoto)

Notas:
    - O receiver deve estar rodando antes de iniciar o sender
    - Para simular perda, use --loss no RECEIVER (ex: python receiver.py --loss 10)
"""

import socket
import struct
import time
import csv
import argparse

# ======================================================================
# CONFIGURAÇÃO
# ======================================================================

# Tamanhos de mensagem (bytes) — conforme tabela do trabalho
TAMANHOS = [1024, 10240, 20480, 30720, 40960, 51200, 61440]
ROTULOS  = ["1KB", "10KB", "20KB", "30KB", "40KB", "50KB", "60KB"]

# Número de pacotes por teste
NUM_PACOTES = 100

# Número de rodadas para média
NUM_RODADAS = 3

# Timeout para ACKs do UDP (segundos)
ACK_TIMEOUT = 3.0

# Buffer de recepção
BUFFER_SIZE = 65536

# Header binário: seq(4) + tamanho(4) + timestamp(4) = 12 bytes
HEADER_FORMAT = "!III"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


# ======================================================================
# FUNÇÕES AUXILIARES
# ======================================================================

def criar_pacote(seq, tamanho):
    """Cria pacote binário: header(12 bytes) + payload de 'X'."""
    ts_ms = int(time.time() * 1000) & 0xFFFFFFFF
    header = struct.pack(HEADER_FORMAT, seq, tamanho, ts_ms)
    payload = b"X" * max(0, tamanho - HEADER_SIZE)
    return header + payload


def parsear_ack(dados):
    """Parseia ACK (4 bytes uint32 big-endian)."""
    if len(dados) >= 4:
        return struct.unpack("!I", dados[:4])[0]
    return -1


# ======================================================================
# BENCHMARK TCP
# ======================================================================

def benchmark_tcp(host, porta, tamanho):
    """
    Envia NUM_PACOTES via TCP. Garante entrega e ordem.
    Retorna: (mbps, tempo_seg)
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.connect((host, porta))

    pacotes = [criar_pacote(seq, tamanho) for seq in range(NUM_PACOTES)]

    inicio = time.perf_counter()
    for pacote in pacotes:
        prefixo = struct.pack("!I", len(pacote))
        sock.sendall(prefixo + pacote)
    fim = time.perf_counter()

    sock.close()

    tempo = fim - inicio
    bits = tamanho * NUM_PACOTES * 8
    mbps = (bits / tempo) / 1_000_000 if tempo > 0 else 0

    return mbps, tempo


# ======================================================================
# BENCHMARK UDP
# ======================================================================

def _coletar_acks(sock, acks, acks_ordem):
    """Coleta todos os ACKs disponíveis (com timeout do socket)."""
    while True:
        try:
            dados, _ = sock.recvfrom(BUFFER_SIZE)
            seq_ack = parsear_ack(dados)
            if seq_ack >= 0:
                acks.add(seq_ack)
                acks_ordem.append(seq_ack)
        except socket.timeout:
            break
        except:
            break


def benchmark_udp(host, porta, tamanho):
    """
    Envia NUM_PACOTES via UDP. Sem garantias do protocolo.
    ACKs são enviados manualmente pelo receiver.
    Retransmite pacotes perdidos (até 3 tentativas).
    
    Retorna: (mbps, tempo_envio, perda_pct, fora_ordem, retransmissoes)
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    pacotes = [criar_pacote(seq, tamanho) for seq in range(NUM_PACOTES)]

    acks = set()
    acks_ordem = []
    retransmissoes = 0

    # Fase 1: envia todos os pacotes e mede o tempo de ENVIO
    inicio = time.perf_counter()
    for seq, pacote in enumerate(pacotes):
        try:
            sock.sendto(pacote, (host, porta))
        except:
            pass
    fim_envio = time.perf_counter()
    tempo_envio = fim_envio - inicio

    # Fase 2: coleta ACKs (com timeout curto)
    sock.settimeout(0.5)
    _coletar_acks(sock, acks, acks_ordem)

    # Fase 3: retransmissão dos perdidos (até 2 tentativas extras)
    for tentativa in range(2):
        faltantes = [seq for seq in range(NUM_PACOTES) if seq not in acks]
        if not faltantes:
            break
        
        for seq in faltantes:
            try:
                sock.sendto(pacotes[seq], (host, porta))
                retransmissoes += 1
            except:
                pass

        _coletar_acks(sock, acks, acks_ordem)

    sock.close()

    # Métricas — throughput baseado no tempo de ENVIO (não no tempo de espera de ACKs)
    bits = tamanho * NUM_PACOTES * 8
    mbps = (bits / tempo_envio) / 1_000_000 if tempo_envio > 0 else 0

    perdidos = NUM_PACOTES - len(acks)
    perda = (perdidos / NUM_PACOTES) * 100

    # Fora de ordem
    fora_ordem = sum(1 for i in range(1, len(acks_ordem)) if acks_ordem[i] < acks_ordem[i-1])

    return mbps, tempo_envio, perda, fora_ordem, retransmissoes


# ======================================================================
# GRÁFICO
# ======================================================================

def gerar_grafico(resultados):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n[AVISO] matplotlib não instalado. pip install matplotlib")
        return

    rotulos = [r["Tamanho"] for r in resultados]
    tcp_tempo = [r["TCP_Tempo_s"] for r in resultados]
    udp_tempo = [r["UDP_Tempo_s"] for r in resultados]
    tcp_mbps = [r["TCP_Mbps"] for r in resultados]
    udp_mbps = [r["UDP_Mbps"] for r in resultados]
    perda = [r["Perda_UDP_%"] for r in resultados]
    retrans = [r["Retransmissoes_UDP"] for r in resultados]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Benchmark TCP vs UDP — Comparação de Desempenho",
                 fontsize=16, fontweight="bold")

    x = range(len(rotulos))
    largura = 0.35

    # --- 1) Tempo de transmissão ---
    ax = axes[0][0]
    ax.bar([i - largura/2 for i in x], tcp_tempo, largura,
           label="TCP", color="#2196F3", alpha=0.85)
    ax.bar([i + largura/2 for i in x], udp_tempo, largura,
           label="UDP", color="#FF5722", alpha=0.85)
    ax.set_xlabel("Tamanho do Pacote")
    ax.set_ylabel("Tempo (s)")
    ax.set_title("Tempo de Transmissão")
    ax.set_xticks(list(x))
    ax.set_xticklabels(rotulos)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    # Valores sobre barras
    for i in range(len(rotulos)):
        ax.text(i - largura/2, tcp_tempo[i], f"{tcp_tempo[i]:.4f}",
                ha="center", va="bottom", fontsize=7, color="#1565C0")
        ax.text(i + largura/2, udp_tempo[i], f"{udp_tempo[i]:.4f}",
                ha="center", va="bottom", fontsize=7, color="#BF360C")

    # --- 2) Taxa de transmissão (Mbps) ---
    ax = axes[0][1]
    ax.plot(list(x), tcp_mbps, "o-", color="#2196F3", linewidth=2.5,
            markersize=8, label="TCP")
    ax.plot(list(x), udp_mbps, "s--", color="#FF5722", linewidth=2.5,
            markersize=8, label="UDP")
    for i, v in enumerate(tcp_mbps):
        ax.annotate(f"{v:.0f}", (i, v), textcoords="offset points",
                    xytext=(0, 10), ha="center", fontsize=8, color="#1565C0")
    for i, v in enumerate(udp_mbps):
        ax.annotate(f"{v:.0f}", (i, v), textcoords="offset points",
                    xytext=(0, -15), ha="center", fontsize=8, color="#BF360C")
    ax.set_xlabel("Tamanho do Pacote")
    ax.set_ylabel("Taxa (Mbps)")
    ax.set_title("Taxa de Transmissão")
    ax.set_xticks(list(x))
    ax.set_xticklabels(rotulos)
    ax.legend()
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=0)

    # --- 3) Perda de Pacotes (UDP) ---
    ax = axes[1][0]
    cores = ["#4CAF50" if v == 0 else "#FF9800" if v < 10 else "#F44336" for v in perda]
    ax.bar(rotulos, perda, color=cores, alpha=0.85)
    ax.set_xlabel("Tamanho do Pacote")
    ax.set_ylabel("Perda (%)")
    ax.set_title("Perda de Pacotes — UDP")
    ax.grid(axis="y", alpha=0.3)
    ax.set_ylim(0, max(max(perda) * 1.3, 5))
    for i, v in enumerate(perda):
        ax.text(i, v + 0.2, f"{v:.1f}%", ha="center", va="bottom",
                fontsize=9, fontweight="bold")

    # --- 4) Retransmissões (UDP) ---
    ax = axes[1][1]
    ax.bar(rotulos, retrans, color="#9C27B0", alpha=0.85)
    ax.set_xlabel("Tamanho do Pacote")
    ax.set_ylabel("Retransmissões")
    ax.set_title("Retransmissões — UDP")
    ax.grid(axis="y", alpha=0.3)
    for i, v in enumerate(retrans):
        ax.text(i, v + 0.2, str(v), ha="center", va="bottom",
                fontsize=9, fontweight="bold")

    plt.tight_layout()
    arquivo = "grafico_benchmark.png"
    plt.savefig(arquivo, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"[OK] Gráfico salvo em {arquivo}")


# ======================================================================
# MAIN
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Benchmark TCP vs UDP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6000)
    parser.add_argument("--mode", choices=["tcp", "udp", "ambos"], default="ambos")
    parser.add_argument("--rodadas", type=int, default=NUM_RODADAS)
    args = parser.parse_args()

    porta_tcp = args.port
    porta_udp = args.port + 1
    num_rodadas = args.rodadas
    rodar_tcp = args.mode in ("tcp", "ambos")
    rodar_udp = args.mode in ("udp", "ambos")

    print("=" * 60)
    print("  BENCHMARK TCP vs UDP")
    print("=" * 60)
    print(f"  Servidor:  {args.host}")
    print(f"  Portas:    TCP={porta_tcp}, UDP={porta_udp}")
    print(f"  Modo:      {args.mode.upper()}")
    print(f"  Pacotes:   {NUM_PACOTES} por rodada")
    print(f"  Rodadas:   {num_rodadas} (média)")
    print(f"  Tamanhos:  {', '.join(ROTULOS)}")
    print("=" * 60)

    resultados = []

    for i, tamanho in enumerate(TAMANHOS):
        rotulo = ROTULOS[i]
        print(f"\n--- Testando {rotulo} ({tamanho} bytes) ---")

        tcp_rodadas = []
        udp_rodadas = []

        for rodada in range(num_rodadas):
            # TCP
            if rodar_tcp:
                print(f"  R{rodada+1} [TCP] ", end="", flush=True)
                try:
                    mbps, tempo = benchmark_tcp(args.host, porta_tcp, tamanho)
                    tcp_rodadas.append((mbps, tempo))
                    print(f"OK — {mbps:.1f} Mbps, {tempo*1000:.1f} ms")
                except Exception as e:
                    print(f"ERRO: {e}")
                    tcp_rodadas.append((0, 0))
                time.sleep(0.3)

            # UDP
            if rodar_udp:
                print(f"  R{rodada+1} [UDP] ", end="", flush=True)
                try:
                    mbps, tempo, perda, fora, retrans = benchmark_udp(
                        args.host, porta_udp, tamanho)
                    udp_rodadas.append((mbps, tempo, perda, fora, retrans))
                    print(f"OK — {mbps:.1f} Mbps, {tempo*1000:.1f} ms, "
                          f"Perda: {perda:.1f}%, Retrans: {retrans}")
                except Exception as e:
                    print(f"ERRO: {e}")
                    udp_rodadas.append((0, 0, 100, 0, 0))
                time.sleep(0.3)

        # Médias
        if tcp_rodadas:
            tcp_mbps = sum(r[0] for r in tcp_rodadas) / len(tcp_rodadas)
            tcp_tempo = sum(r[1] for r in tcp_rodadas) / len(tcp_rodadas)
        else:
            tcp_mbps, tcp_tempo = 0, 0

        if udp_rodadas:
            udp_mbps = sum(r[0] for r in udp_rodadas) / len(udp_rodadas)
            udp_tempo = sum(r[1] for r in udp_rodadas) / len(udp_rodadas)
            udp_perda = sum(r[2] for r in udp_rodadas) / len(udp_rodadas)
            udp_fora = sum(r[3] for r in udp_rodadas) // len(udp_rodadas)
            udp_retrans = sum(r[4] for r in udp_rodadas) // len(udp_rodadas)
        else:
            udp_mbps, udp_tempo, udp_perda, udp_fora, udp_retrans = 0, 0, 0, 0, 0

        resultados.append({
            "Tamanho": rotulo,
            "Tamanho_bytes": tamanho,
            "TCP_Mbps": round(tcp_mbps, 2),
            "TCP_Tempo_s": round(tcp_tempo, 6),
            "UDP_Mbps": round(udp_mbps, 2),
            "UDP_Tempo_s": round(udp_tempo, 6),
            "Perda_UDP_%": round(udp_perda, 1),
            "Fora_ordem_UDP": udp_fora,
            "Retransmissoes_UDP": udp_retrans,
        })

        time.sleep(0.5)

    # ======================================================================
    # TABELA (formato do professor)
    # ======================================================================
    print("\n\n")
    print("=" * 80)
    print(f"  RESULTADOS (média de {num_rodadas} rodadas, {NUM_PACOTES} pacotes)")
    print("=" * 80)

    # Tabela 1: Tempos (formato do professor)
    print(f"\n{'Tamanho':<10} | {'TCP (tempo)':<15} | {'UDP (tempo)':<15}")
    print("-" * 45)
    for r in resultados:
        print(f"{r['Tamanho']:<10} | {r['TCP_Tempo_s']*1000:<12.2f} ms | "
              f"{r['UDP_Tempo_s']*1000:<12.2f} ms")

    # Tabela 2: Métricas completas
    print(f"\n{'Tamanho':<10} | {'TCP Mbps':<10} | {'UDP Mbps':<10} | "
          f"{'Perda%':<8} | {'F.Ordem':<8} | {'Retrans'}")
    print("-" * 70)
    for r in resultados:
        print(f"{r['Tamanho']:<10} | {r['TCP_Mbps']:<10.1f} | {r['UDP_Mbps']:<10.1f} | "
              f"{r['Perda_UDP_%']:<8.1f} | {r['Fora_ordem_UDP']:<8} | "
              f"{r['Retransmissoes_UDP']}")
    print("=" * 80)

    # CSV
    arquivo_csv = "resultados_benchmark.csv"
    with open(arquivo_csv, "w", newline="", encoding="utf-8") as f:
        campos = list(resultados[0].keys())
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(resultados)
    print(f"\n[OK] Resultados salvos em {arquivo_csv}")

    # Gráfico
    gerar_grafico(resultados)


if __name__ == "__main__":
    main()
