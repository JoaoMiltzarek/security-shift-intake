#!/usr/bin/env python3
"""Launcher oficial da UI de revisão — loopback only (SSI-1009 / finding F-08).

A API de revisão NÃO tem autenticação e `GET /drafts/{id}` devolve o estado
completo (transcrição/PII). O único deploy suportado é single-operator em
localhost; este launcher torna a convenção executável: qualquer host fora de
loopback é recusado, a menos que o operador passe a flag explícita
`--i-know-this-exposes-pii` (e assuma o risco por escrito no comando).

Uso:
    make serve                      # 127.0.0.1:8000
    make serve PORT=8080
    INTAKE_CONFIG=... make serve    # config alternativa (mesma env da app)
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Serve a UI de revisão (loopback only).")
    parser.add_argument("--port", type=int, default=int(os.environ.get("INTAKE_PORT", "8000")))
    parser.add_argument(
        "--host",
        default=os.environ.get("INTAKE_HOST", "127.0.0.1"),
        help="Só loopback é suportado; ver --i-know-this-exposes-pii.",
    )
    parser.add_argument(
        "--i-know-this-exposes-pii",
        action="store_true",
        help="Permite bind fora de loopback SEM auth — expõe PII a quem alcançar a porta.",
    )
    args = parser.parse_args(argv)

    if args.host not in _LOOPBACK_HOSTS and not args.i_know_this_exposes_pii:
        print(
            f"ERRO: host '{args.host}' não é loopback. A UI não tem autenticação e o\n"
            "estado dos drafts contém PII — expor isso a uma rede publica os dados.\n"
            "Use 127.0.0.1 (default) ou, se você REALMENTE precisa, repita com\n"
            "--i-know-this-exposes-pii.",
            file=sys.stderr,
        )
        return 2

    uvicorn.run("src.api.app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
