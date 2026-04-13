@echo off
:: =====================================================================
:: rodar.bat — Atalhos para rodar o Pong gRPC
:: =====================================================================
:: Uso:
::   rodar.bat servidor         → Inicia o servidor gRPC
::   rodar.bat cliente          → Inicia um cliente (exibe pop-up)
::   rodar.bat gerar-proto      → Regenera os arquivos pb2 do .proto
:: =====================================================================

SET PYTHON="C:\Users\guife\AppData\Local\Programs\Python\Python311\python.exe"

if "%1"=="servidor" (
    echo [PONG] Iniciando servidor gRPC...
    %PYTHON% servidor_grpc.py
    goto :eof
)

if "%1"=="cliente" (
    echo [PONG] Iniciando cliente gRPC...
    %PYTHON% cliente_grpc.py
    goto :eof
)

if "%1"=="gerar-proto" (
    echo [PROTO] Gerando arquivos pb2...
    %PYTHON% -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. pong.proto
    echo [OK] Arquivos gerados: pong_pb2.py e pong_pb2_grpc.py
    goto :eof
)

echo.
echo  PONG gRPC — Comandos disponíveis:
echo.
echo   rodar.bat servidor       → Inicia o servidor
echo   rodar.bat cliente        → Inicia um cliente
echo   rodar.bat gerar-proto    → Regenera código proto
echo.
