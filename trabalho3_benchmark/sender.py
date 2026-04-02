"""
sender.py — Benchmark automático TCP vs UDP
=============================================
Envia 100 pacotes de cada tamanho em TCP e UDP.
Mede taxa de transmissão (Mbps), perda e ordem.
Salva resultados em resultados_benchmark.csv e gráfico.

Uso:
    python sender.py                      (roda TCP + UDP)
    python sender.py --mode tcp           (só TCP)
    python sender.py --mode udp           (só UDP)
    python sender.py --host 192.168.1.10  (IP remoto)
"""

import socket
import json
import time
import csv
import argparse

# ======================================================================
# CONFIGURAÇÃO DO BENCHMARK
# ======================================================================

# Tamanhos de mensagem a serem testados (bytes)
TAMANHOS = [1024, 10240, 20480, 30720, 40960, 51200, 61440]

# Rótulos para exibição na tabela
ROTULOS = ["1KB", "10KB", "20KB", "30KB", "40KB", "50KB", "60KB"]

# Número de pacotes enviados em cada rodada
NUM_PACOTES = 100

# Timeout para esperar ACKs no modo UDP (segundos)
ACK_TIMEOUT = 2.0

# Tamanho do buffer de recebimento
BUFFER_SIZE = 65536


# ======================================================================
# BENCHMARK TCP
# ======================================================================

def benchmark_tcp(host, porta, tamanho):
    """
    Envia NUM_PACOTES via TCP e mede o tempo total de transferência.
    
    Como o TCP garante entrega e ordem, a perda é sempre 0%
    e não há pacotes fora de ordem.
    
    Retorna:
        mbps (float): Taxa de transmissão em Megabits por segundo
        perda (float): Sempre 0.0 (TCP garante entrega)
        fora_ordem (int): Sempre 0 (TCP garante ordem)
    """
    # Cria socket TCP e conecta ao receiver
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, porta))
    
    # Cria o payload com o tamanho desejado (preenche com 'X')
    dados_base = "X" * max(1, tamanho - 100)  # Reserva espaço para metadados JSON
    
    inicio = time.time()
    
    for seq in range(NUM_PACOTES):
        # Monta o pacote como dicionário JSON
        pacote = {
            "seq": seq,                    # Número de sequência
            "tamanho": tamanho,            # Tamanho nominal do pacote
            "timestamp": time.time(),      # Momento do envio
            "dados": dados_base[:max(1, tamanho - 100)]  # Payload
        }
        # Serializa + delimitador de nova linha
        msg = json.dumps(pacote).encode("utf-8") + b"\n"
        sock.sendall(msg)
    
    fim = time.time()
    sock.close()
    
    # Calcula taxa de transmissão em Mbps
    tempo_total = fim - inicio
    bits_enviados = tamanho * NUM_PACOTES * 8  # bytes → bits
    mbps = (bits_enviados / tempo_total) / 1_000_000 if tempo_total > 0 else 0
    
    return mbps, 0.0, 0


# ======================================================================
# BENCHMARK UDP
# ======================================================================

def benchmark_udp(host, porta, tamanho):
    """
    Envia NUM_PACOTES via UDP e espera ACKs manuais do receiver.
    
    Ao contrário do TCP, o UDP não garante entrega nem ordem.
    Medimos quantos ACKs voltaram para calcular perda e ordem.
    
    Retorna:
        mbps (float): Taxa de transmissão em Megabits por segundo
        perda (float): Percentual de pacotes sem ACK recebido
        fora_ordem (int): Número de ACKs que chegaram fora de ordem
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(ACK_TIMEOUT)
    
    # Limita o payload para caber em um datagrama UDP (~65507 bytes max)
    tamanho_payload = min(tamanho, 60000)
    dados_base = "X" * max(1, tamanho_payload - 100)
    
    acks_recebidos = set()   # Conjunto de sequências ACK recebidas
    acks_ordem = []          # Ordem em que os ACKs chegaram
    
    inicio = time.time()
    
    # Fase 1: Envia todos os pacotes de uma vez
    for seq in range(NUM_PACOTES):
        pacote = {
            "seq": seq,
            "tamanho": tamanho,
            "timestamp": time.time(),
            "dados": dados_base
        }
        msg = json.dumps(pacote).encode("utf-8")
        try:
            sock.sendto(msg, (host, porta))
        except Exception as e:
            print(f"  [UDP] Erro ao enviar seq {seq}: {e}")
    
    # Fase 2: Espera os ACKs (com timeout)
    deadline = time.time() + ACK_TIMEOUT
    while time.time() < deadline and len(acks_recebidos) < NUM_PACOTES:
        try:
            dados, _ = sock.recvfrom(BUFFER_SIZE)
            ack = json.loads(dados.decode("utf-8"))
            seq_ack = ack.get("ack", -1)
            if seq_ack >= 0:
                acks_recebidos.add(seq_ack)
                acks_ordem.append(seq_ack)
        except socket.timeout:
            break
        except:
            continue
    
    fim = time.time()
    sock.close()
    
    # Calcula métricas
    tempo_total = fim - inicio
    bits_enviados = tamanho * NUM_PACOTES * 8
    mbps = (bits_enviados / tempo_total) / 1_000_000 if tempo_total > 0 else 0
    
    perdidos = NUM_PACOTES - len(acks_recebidos)
    perda = (perdidos / NUM_PACOTES) * 100
    
    # Conta ACKs que chegaram fora de ordem
    fora_ordem = 0
    for i in range(1, len(acks_ordem)):
        if acks_ordem[i] < acks_ordem[i-1]:
            fora_ordem += 1
    
    return mbps, perda, fora_ordem


# ======================================================================
# GERAÇÃO DE GRÁFICO
# ======================================================================

def gerar_grafico(resultados):
    """
    Gera um gráfico de barras comparando TCP vs UDP por tamanho de pacote.
    Usa matplotlib se disponível. Se não tiver, apenas avisa e segue.
    Salva o gráfico como 'grafico_benchmark.png'.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # Backend sem GUI (funciona em qualquer terminal)
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n[AVISO] matplotlib não instalado. Gráfico não gerado.")
        print("  Instale com: pip install matplotlib")
        return
    
    rotulos = [r["Tamanho"] for r in resultados]
    tcp_vals = [r["TCP_Mbps"] for r in resultados]
    udp_vals = [r["UDP_Mbps"] for r in resultados]
    perda_vals = [r["Perda_UDP_%"] for r in resultados]
    
    # Cria figura com 2 subplots
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Benchmark TCP vs UDP", fontsize=16, fontweight="bold")
    
    # --- Gráfico 1: Taxa de transmissão (Mbps) ---
    x = range(len(rotulos))
    largura = 0.35
    
    barras_tcp = ax1.bar([i - largura/2 for i in x], tcp_vals, largura,
                         label="TCP", color="#2196F3", alpha=0.85)
    barras_udp = ax1.bar([i + largura/2 for i in x], udp_vals, largura,
                         label="UDP", color="#FF5722", alpha=0.85)
    
    ax1.set_xlabel("Tamanho do pacote")
    ax1.set_ylabel("Taxa (Mbps)")
    ax1.set_title("Taxa de Transmissão")
    ax1.set_xticks(x)
    ax1.set_xticklabels(rotulos)
    ax1.legend()
    ax1.grid(axis="y", alpha=0.3)
    
    # Adiciona valores sobre as barras
    for b in barras_tcp:
        ax1.text(b.get_x() + b.get_width()/2, b.get_height() + 1,
                 f"{b.get_height():.0f}", ha="center", va="bottom", fontsize=7)
    for b in barras_udp:
        ax1.text(b.get_x() + b.get_width()/2, b.get_height() + 1,
                 f"{b.get_height():.0f}", ha="center", va="bottom", fontsize=7)
    
    # --- Gráfico 2: Perda de pacotes (UDP) ---
    ax2.bar(rotulos, perda_vals, color="#FF9800", alpha=0.85)
    ax2.set_xlabel("Tamanho do pacote")
    ax2.set_ylabel("Perda (%)")
    ax2.set_title("Taxa de Perda — UDP")
    ax2.grid(axis="y", alpha=0.3)
    ax2.set_ylim(0, max(max(perda_vals) * 1.5, 5))  # Mín 5% no eixo Y
    
    # Adiciona valores sobre as barras
    for i, v in enumerate(perda_vals):
        ax2.text(i, v + 0.2, f"{v:.1f}%", ha="center", va="bottom", fontsize=9)
    
    plt.tight_layout()
    arquivo = "grafico_benchmark.png"
    plt.savefig(arquivo, dpi=150)
    plt.close()
    print(f"[OK] Gráfico salvo em {arquivo}")


# ======================================================================
# MAIN
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Benchmark TCP vs UDP")
    parser.add_argument("--host", default="127.0.0.1",
                        help="IP do receiver (padrão: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=6000,
                        help="Porta base (TCP=port, UDP=port+1). Padrão: 6000")
    parser.add_argument("--mode", choices=["tcp", "udp", "ambos"], default="ambos",
                        help="Modo do teste: tcp, udp, ou ambos (padrão: ambos)")
    args = parser.parse_args()

    porta_tcp = args.port
    porta_udp = args.port + 1

    rodar_tcp = args.mode in ("tcp", "ambos")
    rodar_udp = args.mode in ("udp", "ambos")

    print("=" * 60)
    print("  BENCHMARK TCP vs UDP")
    print("=" * 60)
    print(f"  Servidor:  {args.host}")
    print(f"  Portas:    TCP={porta_tcp}, UDP={porta_udp}")
    print(f"  Modo:      {args.mode.upper()}")
    print(f"  Pacotes:   {NUM_PACOTES} por rodada")
    print(f"  Tamanhos:  {', '.join(ROTULOS)}")
    print("=" * 60)

    resultados = []

    for i, tamanho in enumerate(TAMANHOS):
        rotulo = ROTULOS[i]
        print(f"\n--- Testando {rotulo} ({tamanho} bytes) ---")

        tcp_mbps = 0.0
        udp_mbps, udp_perda, udp_fora = 0.0, 0.0, 0

        # Benchmark TCP
        if rodar_tcp:
            print(f"  [TCP] Enviando {NUM_PACOTES} pacotes...", end=" ", flush=True)
            try:
                tcp_mbps, _, _ = benchmark_tcp(args.host, porta_tcp, tamanho)
                print(f"OK — {tcp_mbps:.2f} Mbps")
            except Exception as e:
                print(f"ERRO: {e}")
                tcp_mbps = 0.0

            time.sleep(1)

        # Benchmark UDP
        if rodar_udp:
            print(f"  [UDP] Enviando {NUM_PACOTES} pacotes...", end=" ", flush=True)
            try:
                udp_mbps, udp_perda, udp_fora = benchmark_udp(args.host, porta_udp, tamanho)
                print(f"OK — {udp_mbps:.2f} Mbps, Perda: {udp_perda:.1f}%")
            except Exception as e:
                print(f"ERRO: {e}")
                udp_mbps, udp_perda, udp_fora = 0.0, 100.0, 0

        resultados.append({
            "Tamanho": rotulo,
            "Tamanho_bytes": tamanho,
            "TCP_Mbps": round(tcp_mbps, 2),
            "UDP_Mbps": round(udp_mbps, 2),
            "Perda_UDP_%": round(udp_perda, 1),
            "Fora_ordem_UDP": udp_fora,
        })

        time.sleep(1)

    # ======================================================================
    # TABELA COMPARATIVA NO TERMINAL
    # ======================================================================
    print("\n")
    print("=" * 60)
    print("  RESULTADOS DO BENCHMARK")
    print("=" * 60)
    print(f"{'Tamanho':<10} | {'TCP (Mbps)':<12} | {'UDP (Mbps)':<12} | {'Perda UDP (%)'}")
    print("-" * 60)
    for r in resultados:
        print(f"{r['Tamanho']:<10} | {r['TCP_Mbps']:<12.2f} | {r['UDP_Mbps']:<12.2f} | {r['Perda_UDP_%']:.1f}%")
    print("=" * 60)

    # ======================================================================
    # SALVA EM CSV
    # ======================================================================
    arquivo = "resultados_benchmark.csv"
    with open(arquivo, "w", newline="", encoding="utf-8") as f:
        campos = ["Tamanho", "Tamanho_bytes", "TCP_Mbps", "UDP_Mbps", "Perda_UDP_%", "Fora_ordem_UDP"]
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(resultados)

    print(f"\n[OK] Resultados salvos em {arquivo}")

    # ======================================================================
    # GERA GRÁFICO COMPARATIVO
    # ======================================================================
    gerar_grafico(resultados)


if __name__ == "__main__":
    main()
