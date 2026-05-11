#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Entrada de la app local para detectar imagenes duplicadas."""

from __future__ import annotations

import argparse

from constants import DEFAULT_PORT
from server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Detector local de imagenes duplicadas")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Puerto local para la interfaz")
    parser.add_argument("--no-open", action="store_true", help="No abrir el navegador automaticamente")
    args = parser.parse_args()

    run_server(port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    main()
