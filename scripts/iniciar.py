"""Sobe o gateway e os quatro serviços, cada um em um processo próprio."""
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# Exatamente os cinco programas executados por `python scripts/iniciar.py`.
MODULOS = [
    "src.servicos.quartos",
    "src.servicos.pessoas",
    "src.servicos.senhas",
    "src.servicos.acessos",
    "src.gateway",
]


def encerrar(processos):
    for p in processos:
        if p.poll() is None:
            p.terminate()
    for p in processos:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    processos = [subprocess.Popen([sys.executable, "-m", m], cwd=RAIZ) for m in MODULOS]
    codigo = 0
    try:
        while True:
            for p in processos:
                if p.poll() is not None:  # um caiu: derruba todos
                    codigo = p.returncode or 1
                    raise SystemExit(codigo)
            time.sleep(0.5)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        encerrar(processos)
    sys.exit(codigo)


if __name__ == "__main__":
    main()
