"""
network.py — Módulo auxiliar de rede para o Pong Multiplayer
=============================================================
Fornece a classe NetworkMode que abstrai a comunicação via TCP ou UDP.
No modo UDP, implementa interpolação linear para suavizar movimentos
quando pacotes chegam fora de ordem ou com atraso.

Autores: Alunos UFRN — Sistemas Distribuídos
"""

import socket
import json
import time
import threading


class NetworkMode:
    """
    Classe que encapsula a lógica de rede (TCP ou UDP).
    
    Parâmetros:
        mode (str): "tcp" ou "udp"
        is_server (bool): True se for o servidor, False se for o cliente
    """
    
    def __init__(self, mode="tcp", is_server=False):
        self.mode = mode.lower()          # Modo de operação: "tcp" ou "udp"
        self.is_server = is_server        # Indica se é servidor ou cliente
        self.socket = None                # Socket principal
        self.connections = []             # Lista de conexões (TCP) ou endereços (UDP)
        self.lock = threading.Lock()      # Lock para acesso thread-safe
        
        # --- Variáveis para interpolação (usadas no cliente UDP) ---
        self.ultimo_estado = None         # Último estado recebido do servidor
        self.estado_anterior = None       # Estado anterior (para interpolar)
        self.timestamp_recebido = 0       # Quando o último estado chegou
        self.ultimo_seq = -1              # Número de sequência do último pacote
        
        # --- Métricas de rede ---
        self.latencias = []               # Lista de todas as latências medidas
        self.pacotes_perdidos = 0         # Contador de pacotes perdidos (UDP)
        self.ultimo_timestamp_latencia = 0  # Para cálculo de jitter
        self.desconectado = False         # Flag para parar de enviar após desconexão
        
    # ======================================================================
    # CONFIGURAÇÃO DO SOCKET
    # ======================================================================
    
    def criar_socket_servidor(self, host="0.0.0.0", porta=5555):
        """
        Cria e configura o socket do servidor.
        TCP: faz bind + listen
        UDP: apenas faz bind
        """
        if self.mode == "tcp":
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((host, porta))
            self.socket.listen(2)  # Aceita até 2 conexões (2 jogadores)
            print(f"[SERVIDOR TCP] Escutando em {host}:{porta}")
        else:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind((host, porta))
            print(f"[SERVIDOR UDP] Escutando em {host}:{porta}")
    
    def aceitar_conexao(self):
        """
        Aguarda e aceita a conexão de um cliente.
        TCP: usa accept() padrão
        UDP: espera o primeiro pacote do cliente para registrar o endereço
        Retorna: índice do jogador (0 ou 1)
        """
        if self.mode == "tcp":
            conn, addr = self.socket.accept()
            with self.lock:
                indice = len(self.connections)
                self.connections.append(conn)
            print(f"[TCP] Jogador {indice + 1} conectado de {addr}")
            return indice
        else:
            # No UDP, esperamos receber um pacote "registro" do cliente
            dados, addr = self.socket.recvfrom(4096)
            with self.lock:
                indice = len(self.connections)
                self.connections.append(addr)
            print(f"[UDP] Jogador {indice + 1} registrado de {addr}")
            return indice
    
    def criar_socket_cliente(self, host, porta=5555):
        """
        Cria o socket do cliente e conecta ao servidor.
        TCP: connect() padrão
        UDP: envia pacote de registro + configura timeout
        """
        if self.mode == "tcp":
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((host, porta))
            print(f"[TCP] Conectado ao servidor {host}:{porta}")
        else:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.servidor_addr = (host, porta)
            # Envia um pacote de "registro" para o servidor saber nosso endereço
            self.socket.sendto(b"registro", self.servidor_addr)
            # Timeout de 100ms para não bloquear se um pacote se perder
            self.socket.settimeout(0.1)
            print(f"[UDP] Registrado no servidor {host}:{porta}")
    
    # ======================================================================
    # ENVIO DE DADOS
    # ======================================================================
    
    def enviar_servidor(self, dados_dict, indice_jogador):
        """
        Servidor envia dados para um jogador específico.
        dados_dict: dicionário Python que será serializado em JSON
        indice_jogador: 0 (jogador 1) ou 1 (jogador 2)
        """
        # Adiciona timestamp e número de sequência ao pacote
        dados_dict["timestamp_envio"] = time.time()
        mensagem = json.dumps(dados_dict).encode("utf-8")
        
        try:
            if self.mode == "tcp":
                # TCP: envia com delimitador de nova linha para separar mensagens
                conn = self.connections[indice_jogador]
                conn.sendall(mensagem + b"\n")
            else:
                # UDP: envia datagrama para o endereço registrado do jogador
                addr = self.connections[indice_jogador]
                self.socket.sendto(mensagem, addr)
        except Exception as e:
            print(f"[ERRO] Falha ao enviar para jogador {indice_jogador + 1}: {e}")
    
    def enviar_cliente(self, dados_dict):
        """
        Cliente envia dados (input do jogador) para o servidor.
        Se a conexão foi perdida, para de tentar enviar.
        """
        if self.desconectado:
            return  # Não tenta enviar se já desconectou
        
        dados_dict["timestamp_envio"] = time.time()
        mensagem = json.dumps(dados_dict).encode("utf-8")
        
        try:
            if self.mode == "tcp":
                self.socket.sendall(mensagem + b"\n")
            else:
                self.socket.sendto(mensagem, self.servidor_addr)
        except Exception as e:
            if not self.desconectado:
                self.desconectado = True
                print(f"[REDE] Servidor desconectou. Encerrando...")
    
    # ======================================================================
    # RECEBIMENTO DE DADOS
    # ======================================================================
    
    def receber_servidor(self, indice_jogador):
        """
        Servidor recebe dados de um jogador específico.
        Retorna: dicionário Python com os dados recebidos, ou None se falhar
        """
        try:
            if self.mode == "tcp":
                conn = self.connections[indice_jogador]
                dados = self._receber_tcp(conn)
                if dados:
                    return json.loads(dados)
            else:
                # No UDP, o servidor recebe de qualquer endereço
                # (o servidor principal gerencia isso de forma diferente)
                dados, addr = self.socket.recvfrom(4096)
                return json.loads(dados.decode("utf-8"))
        except socket.timeout:
            return None
        except Exception as e:
            return None
    
    def receber_cliente(self):
        """
        Cliente recebe estado do jogo do servidor.
        No modo UDP, aplica interpolação linear se houver atraso.
        Retorna: dicionário com o estado do jogo
        """
        if self.desconectado:
            return self.ultimo_estado
        
        try:
            if self.mode == "tcp":
                dados = self._receber_tcp(self.socket)
                if dados:
                    estado = json.loads(dados)
                    self._calcular_metricas(estado)
                    return estado
                else:
                    # _receber_tcp retornou None = timeout normal, sem dados ainda
                    return self.ultimo_estado
            else:
                dados, addr = self.socket.recvfrom(4096)
                estado = json.loads(dados.decode("utf-8"))
                self._calcular_metricas(estado)
                
                # --- INTERPOLAÇÃO LINEAR (diferencial do UDP) ---
                estado = self._interpolar_estado(estado)
                return estado
                
        except socket.timeout:
            # Se não recebeu pacote (timeout), conta como perda no UDP
            if self.mode == "udp":
                self.pacotes_perdidos += 1
            return self.ultimo_estado  # Retorna o último estado conhecido
        except (ConnectionResetError, ConnectionAbortedError, OSError):
            # Conexão realmente caiu
            if not self.desconectado:
                self.desconectado = True
                print("[REDE] Servidor desconectou.")
            return self.ultimo_estado
        except Exception as e:
            return self.ultimo_estado
    
    # ======================================================================
    # INTERPOLAÇÃO LINEAR (EXCLUSIVA DO MODO UDP)
    # ======================================================================
    
    def _interpolar_estado(self, novo_estado):
        """
        Implementa interpolação linear para suavizar o movimento no UDP.
        
        Se um pacote demorar mais de 2 frames (>33ms a 60fps) ou vier
        fora de ordem, interpolamos entre a última posição conhecida
        e a nova posição, evitando "pulos" bruscos na tela.
        
        A interpolação funciona assim:
        - Calcula o tempo entre o pacote anterior e o novo
        - Se o atraso for grande, usa um fator de suavização (0.0 a 1.0)
        - A posição final é: pos_anterior + fator * (pos_nova - pos_anterior)
        """
        seq = novo_estado.get("seq", 0)
        agora = time.time()
        
        # Se é o primeiro pacote, não há o que interpolar
        if self.ultimo_estado is None:
            self.ultimo_estado = novo_estado
            self.estado_anterior = novo_estado
            self.timestamp_recebido = agora
            self.ultimo_seq = seq
            return novo_estado
        
        # Calcula o tempo desde o último pacote recebido
        delta_tempo = agora - self.timestamp_recebido
        tempo_2_frames = 2.0 / 60.0  # ~33.3ms (2 frames a 60fps)
        
        # Verifica se o pacote está fora de ordem
        fora_de_ordem = seq < self.ultimo_seq
        atraso_grande = delta_tempo > tempo_2_frames
        
        if fora_de_ordem:
            # Pacote antigo: descarta (já temos dados mais recentes)
            self.pacotes_perdidos += 1
            return self.ultimo_estado
        
        if atraso_grande:
            # Pacote atrasado: interpola para suavizar
            # Fator de interpolação: quanto mais atrasado, mais suave
            # Usamos 0.5 como fator base para transição gradual
            fator = min(1.0, tempo_2_frames / delta_tempo) * 0.5 + 0.5
            
            estado_interpolado = novo_estado.copy()
            
            # Interpola posição da bola
            estado_interpolado["bola_x"] = self._lerp(
                self.ultimo_estado.get("bola_x", 400),
                novo_estado.get("bola_x", 400),
                fator
            )
            estado_interpolado["bola_y"] = self._lerp(
                self.ultimo_estado.get("bola_y", 300),
                novo_estado.get("bola_y", 300),
                fator
            )
            
            # Interpola posição dos paddles
            estado_interpolado["paddle1_y"] = self._lerp(
                self.ultimo_estado.get("paddle1_y", 250),
                novo_estado.get("paddle1_y", 250),
                fator
            )
            estado_interpolado["paddle2_y"] = self._lerp(
                self.ultimo_estado.get("paddle2_y", 250),
                novo_estado.get("paddle2_y", 250),
                fator
            )
            
            self.estado_anterior = self.ultimo_estado
            self.ultimo_estado = estado_interpolado
        else:
            # Pacote chegou no tempo: usa diretamente
            self.estado_anterior = self.ultimo_estado
            self.ultimo_estado = novo_estado
        
        self.timestamp_recebido = agora
        self.ultimo_seq = seq
        return self.ultimo_estado
    
    @staticmethod
    def _lerp(a, b, t):
        """
        Interpolação linear entre dois valores.
        a: valor inicial
        b: valor final
        t: fator de interpolação (0.0 = a, 1.0 = b)
        """
        return a + (b - a) * t
    
    # ======================================================================
    # MÉTRICAS DE REDE
    # ======================================================================
    
    def _calcular_metricas(self, estado):
        """
        Calcula latência e jitter a partir do timestamp do pacote.
        Latência = tempo_atual - timestamp_envio (ida simples)
        Jitter = variação entre latências consecutivas
        """
        timestamp_envio = estado.get("timestamp_envio", 0)
        if timestamp_envio > 0:
            latencia = (time.time() - timestamp_envio) * 1000  # Converte para ms
            self.latencias.append(latencia)
    
    def obter_latencia_atual(self):
        """Retorna a latência do último pacote em ms."""
        if self.latencias:
            return self.latencias[-1]
        return 0.0
    
    def obter_jitter(self):
        """
        Calcula o jitter (variação da latência) em ms.
        Jitter = média das diferenças absolutas entre latências consecutivas.
        """
        if len(self.latencias) < 2:
            return 0.0
        # Pega as últimas 10 latências para calcular o jitter recente
        recentes = self.latencias[-10:]
        diferencas = [abs(recentes[i] - recentes[i-1]) for i in range(1, len(recentes))]
        return sum(diferencas) / len(diferencas) if diferencas else 0.0
    
    def obter_metricas_finais(self):
        """
        Retorna um dicionário com todas as métricas coletadas.
        Chamado ao fechar o jogo para salvar no CSV.
        """
        if self.latencias:
            latencia_media = sum(self.latencias) / len(self.latencias)
            latencia_maxima = max(self.latencias)
        else:
            latencia_media = 0.0
            latencia_maxima = 0.0
        
        return {
            "modo": self.mode.upper(),
            "latencia_media_ms": round(latencia_media, 2),
            "latencia_maxima_ms": round(latencia_maxima, 2),
            "jitter_medio_ms": round(self.obter_jitter(), 2),
            "pacotes_perdidos": self.pacotes_perdidos,
        }
    
    # ======================================================================
    # UTILITÁRIOS INTERNOS
    # ======================================================================
    
    def _receber_tcp(self, conn):
        """
        Recebe dados via TCP usando delimitador de nova linha.
        TCP é um protocolo de stream, então precisamos de um delimitador
        para saber onde uma mensagem termina e outra começa.
        
        Retorna:
            str: mensagem recebida
            None: timeout (sem dados ainda, normal)
        Levanta:
            ConnectionAbortedError: se a conexão foi fechada pelo servidor
        """
        conn.settimeout(0.1)  # Timeout curto para não bloquear o loop do jogo
        try:
            buffer = b""
            while True:
                pedaco = conn.recv(4096)
                if not pedaco:
                    # recv retornou b"" → servidor fechou a conexão de verdade
                    raise ConnectionAbortedError("Servidor fechou a conexão")
                buffer += pedaco
                # Procura o delimitador de nova linha
                if b"\n" in buffer:
                    # Retorna apenas a primeira mensagem completa
                    mensagem, _ = buffer.split(b"\n", 1)
                    return mensagem.decode("utf-8")
        except socket.timeout:
            # Timeout = sem dados ainda, não é erro
            return None
    
    def fechar(self):
        """Fecha todos os sockets e conexões."""
        try:
            for conn in self.connections:
                if isinstance(conn, socket.socket):
                    conn.close()
            if self.socket:
                self.socket.close()
        except:
            pass
