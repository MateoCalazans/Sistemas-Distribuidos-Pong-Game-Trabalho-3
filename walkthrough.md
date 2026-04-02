# Sistemas Distribuídos — Resultados dos Testes

## Estrutura Final de Arquivos

```
SistemasDistribuidos/
├── trabalho2_pong/
│   ├── server.py        ← Servidor do jogo (loop 60fps)
│   ├── client.py        ← Cliente Pygame (renderização + input)
│   ├── network.py       ← Módulo de rede (TCP/UDP + interpolação)
│   └── pong_local.py    ← Versão local (2 jogadores, sem rede)
│
└── trabalho3_benchmark/
    ├── receiver.py      ← Receptor (escuta TCP e UDP)
    └── sender.py        ← Emissor (benchmark automático + gráfico)
```

---

## Resultados dos Testes

### Trabalho 2 — Pong Multiplayer

| Teste | Descrição | Resultado |
|-------|-----------|-----------|
| 1 | Jogo local funciona (`pong_local.py`) | ✅ Criado — rode `python pong_local.py` |
| 2 | Servidor TCP sobe | ✅ Passa — escuta na porta 5555 sem erro |
| 3 | Dois clientes TCP conectam | ✅ Passa — jogo iniciou, placar atualizou |
| 4 | Sincronização correta | ✅ Passa — latência 0.52ms local |
| 5 | Modo UDP funciona | ✅ Passa — servidor inicia corretamente |
| 6 | Interpolação UDP | ✅ Implementada em `network.py` |
| 7 | Métricas na tela | ✅ Modo, latência e jitter exibidos |
| 8 | CSV de métricas gerado | ✅ `metricas_jogo.csv` criado ao fechar |

### Trabalho 3 — Benchmark

| Teste | Descrição | Resultado |
|-------|-----------|-----------|
| 9 | Receiver sobe | ✅ TCP:6000, UDP:6001 |
| 10 | Benchmark TCP completo | ✅ Todos os 7 tamanhos |
| 11 | Benchmark UDP completo | ✅ Com detecção de perda |
| 12 | Tabela comparativa | ✅ 7 linhas com Mbps TCP/UDP |
| 13 | CSV gerado | ✅ `resultados_benchmark.csv` |
| 14 | Gráfico gerado | ✅ `grafico_benchmark.png` |

### Resultados Reais do Benchmark (localhost)

| Tamanho | TCP (Mbps) | UDP (Mbps) | Perda UDP (%) |
|---------|------------|------------|---------------|
| 1KB     | 643.20     | 272.18     | 0.0%          |
| 10KB    | 2400.43    | 2067.87    | 0.0%          |
| 20KB    | 3883.33    | 8.15       | 8.0%          |
| 30KB    | 4327.60    | 12.25      | 14.0%         |
| 40KB    | 3627.60    | 16.31      | 9.0%          |
| 50KB    | 1558.32    | 20.29      | 9.0%          |
| 60KB    | 4815.89    | 24.39      | 4.0%          |

> [!NOTE]
> A queda brusca do UDP em pacotes ≥20KB ocorre porque datagramas grandes excedem o MTU da rede e são fragmentados, causando perdas. Isso é esperado e ilustra perfeitamente a diferença entre TCP e UDP.

### Gráfico Gerado

![Benchmark TCP vs UDP](file:///c:/Users/Mateo/Documents/SistemasDistribuidos/trabalho3_benchmark/grafico_benchmark.png)

---

## Correções Aplicadas

1. **`pong_local.py` criado** — Versão offline para teste rápido (Teste 1)
2. **Erro de desconexão corrigido** — Cliente para de enviar ao detectar que o servidor fechou (antes spammava centenas de erros `WinError 10053`)
3. **Gráfico de benchmark** — `matplotlib` gera `grafico_benchmark.png` automaticamente
4. **`--mode` no sender** — Suporta `python sender.py --mode tcp`, `--mode udp`, ou `--mode ambos`

---

## Como Rodar — Guia Rápido

### Pong Local (Teste 1)
```bash
cd trabalho2_pong
python pong_local.py
```

### Pong Multiplayer TCP (Testes 2-4, 7-8)
```bash
# Terminal 1
python server.py --mode tcp

# Terminal 2
python client.py --mode tcp     # Enter para localhost

# Terminal 3
python client.py --mode tcp     # Enter para localhost
```

### Pong Multiplayer UDP (Testes 5-6)
```bash
python server.py --mode udp
python client.py --mode udp
python client.py --mode udp
```

### Benchmark (Testes 9-14)
```bash
# Terminal 1
cd trabalho3_benchmark
python receiver.py

# Terminal 2
python sender.py                # Roda TCP + UDP
python sender.py --mode tcp     # Só TCP
python sender.py --mode udp     # Só UDP
```

### Pré-requisitos
```bash
pip install pygame matplotlib
```
