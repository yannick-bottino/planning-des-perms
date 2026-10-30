"""Faux exécutable `claude -p --output-format json` pour les tests.

Lit la consigne sur l'entrée standard, l'ajoute à FAUX_CLAUDE_JOURNAL (une consigne par ligne JSON),
et renvoie la réponse suivante de FAUX_CLAUDE_REPONSES (liste JSON ; le dernier élément se répète).
Une réponse "ERREUR" simule un échec de Claude Code, "LENT" un dépassement de délai.
"""
import json
import os
import sys
import time
from pathlib import Path

consigne = sys.stdin.buffer.read().decode("utf-8")
journal = Path(os.environ["FAUX_CLAUDE_JOURNAL"])
with journal.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"args": sys.argv[1:], "consigne": consigne}, ensure_ascii=False) + "\n")
n = len(journal.read_text(encoding="utf-8").splitlines())
reponses = json.loads(Path(os.environ["FAUX_CLAUDE_REPONSES"]).read_text(encoding="utf-8"))
reponse = reponses[min(n, len(reponses)) - 1]
if reponse == "LENT":
    time.sleep(60)
if reponse == "ERREUR":
    print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in"}))
    sys.exit(1)
sys.stdout.buffer.write(json.dumps({"type": "result", "is_error": False, "result": reponse},
                                   ensure_ascii=False).encode("utf-8"))
