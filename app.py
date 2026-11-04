import datetime
import json
import os
import re
import secrets
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Tout vit dans le dossier de app.py : les pages générées <code>-idtlg.html,
# le fichier d'état validations.json et le template.
BASE_DIR = Path(__file__).parent
STORE = BASE_DIR / "validations.json"

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000")

app = Flask(__name__)
jinja_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html"]),  # échappe les réponses -> pas d'injection HTML
)

CODE_RE = re.compile(r"^\d{4}$")  # un code = exactement 4 chiffres


def _charger() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {}


def _sauver(data: dict) -> None:
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _nouveau_code(data: dict) -> str:
    """Tire un code à 4 chiffres non encore utilisé (ni en base, ni sur le disque)."""
    for _ in range(10000):
        code = f"{secrets.randbelow(10000):04d}"  # 0000 -> 9999
        if code not in data and not (BASE_DIR / f"{code}-idtlg.html").exists():
            return code
    abort(500, "plus de codes disponibles")


def generer_page(champs: list):
    """Écrit <code>-idtlg.html dans le dossier de l'appli. Renvoie (code, url)."""
    data = _charger()
    code = _nouveau_code(data)

    contenu = jinja_env.get_template("page.html").render(code=code, champs=champs)
    (BASE_DIR / f"{code}-idtlg.html").write_text(contenu, encoding="utf-8")

    data[code] = {
        "champs": champs,
        "valide": False,
        "date_validation": None,
        "confirmation": None,
    }
    _sauver(data)
    return code, f"{PUBLIC_BASE_URL}/{code}-idtlg.html"


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Appelé par le bot : reçoit les champs, génère la page, renvoie code + url."""
    body = request.get_json(force=True)
    code, url = generer_page(body.get("champs", []))
    return jsonify({"code": code, "url": url})


@app.route("/<code>-idtlg.html")
def servir_page(code):
    """Sert la page à l'URL /<code>-idtlg.html (joignable via le domaine du A record)."""
    if not CODE_RE.match(code):
        abort(404)
    fichier = f"{code}-idtlg.html"
    if not (BASE_DIR / fichier).exists():
        abort(404)
    return send_from_directory(str(BASE_DIR), fichier)


@app.route("/valider/<code>", methods=["POST"])
def valider(code):
    """Validation réelle : marque les réponses confirmées, renvoie un code daté."""
    if not CODE_RE.match(code):
        abort(404)
    data = _charger()
    enr = data.get(code)
    if enr is None:
        abort(404)
    if not enr["valide"]:
        enr["valide"] = True
        enr["date_validation"] = datetime.datetime.now().isoformat(timespec="seconds")
        enr["confirmation"] = secrets.token_hex(4).upper()
        _sauver(data)
    return jsonify({"valide": True, "confirmation": enr["confirmation"], "date": enr["date_validation"]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
