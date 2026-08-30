"""Pornirea serverului în container, cu procese `spawn` în loc de `fork`.

Pe Linux, granian își creează lucrătorii cu `fork`, iar părintele — `reflex
run`, care compilează paginile — a folosit deja Polars la precalcularea stării
inițiale. Fork-ul copiază bazinul de fire al lui Polars cu tot cu lacătele lui,
într-o stare din care nu se mai poate ieși: primul apel Polars din lucrător
așteaptă la nesfârșit un fir care nu există în copil. Simptomul văzut în
producție: pagina statică se servește, iar la prima filtrare întregul proces
îngheață, cu firul principal blocat în `collect()`.

`spawn` pornește lucrătorul curat, cu propriul lui Polars — este implicit pe
macOS și Windows, unde problema nu apare. Reflex face aceeași forțare în modul
lui de dezvoltare strictă; aici o facem pentru producție.
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> None:
    multiprocessing.set_start_method("spawn", force=True)
    from reflex.reflex import cli

    sys.argv = [
        "reflex",
        "run",
        "--env",
        "prod",
        "--frontend-port",
        "3000",
        "--backend-port",
        "3000",
    ]
    cli()


if __name__ == "__main__":
    main()
