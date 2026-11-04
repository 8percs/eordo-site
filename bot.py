import io
import logging
import os
from pathlib import Path

import qrcode
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]  # export BOT_TOKEN=...
FLASK_API_URL = os.environ.get("FLASK_API_URL", "http://localhost:5000/api/generate")

# ── Questions posées par le bot ────────────────────────────────────────────
# Modifie / ajoute / retire des lignes ci-dessous : la conversation s'adapte
# automatiquement (numérotation, nombre d'étapes, champs de la page).
QUESTIONS = [
    "Nom du patient :", "Prénom :", "Date de naissance :", "Date de préscription :", "Préscription n°1 :", "Posologie n°1 :", "Préscription n°2 :", "Posologie n°2 :"

 ]
# ────────────────────────────────────────────────────────────────────────────

# Tout dans le même dossier que le bot (comme les pages générées par Flask).
BASE_DIR = Path(__file__).parent

REPONDRE = 0  # unique état : on boucle sur QUESTIONS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["i"] = 0
    context.user_data["champs"] = []
    await update.message.reply_text(
        "Salut ! Je te pose quelques questions, puis je génère ta page de validation.\n"
        "(/cancel pour annuler)\n\n"
        f"Question 1/{len(QUESTIONS)} — {QUESTIONS[0]}"
    )
    return REPONDRE


async def repondre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    i = context.user_data["i"]
    context.user_data["champs"].append({"label": QUESTIONS[i], "valeur": update.message.text})
    i += 1
    context.user_data["i"] = i

    if i < len(QUESTIONS):
        await update.message.reply_text(f"Question {i + 1}/{len(QUESTIONS)} — {QUESTIONS[i]}")
        return REPONDRE

    # Toutes les réponses collectées -> Flask tire un code à 4 chiffres et
    # génère <code>-idtlg.html dans son dossier.
    reponse = requests.post(
        FLASK_API_URL,
        json={"champs": context.user_data["champs"]},
        timeout=10,
    )
    reponse.raise_for_status()
    data = reponse.json()
    code = data["code"]   # ex. 1234
    url = data["url"]      # ex. https://tondomaine.fr/1234-idtlg.html

    # QR code qui redirige vers la page de validation
    image_qr = qrcode.make(url)

    # 1) enregistrement local, dans le même dossier : <code>-idtlg.png
    chemin_local = BASE_DIR / f"{code}-idtlg.png"
    image_qr.save(chemin_local)

    # 2) envoi du même QR dans le chat Telegram
    buffer = io.BytesIO()
    image_qr.save(buffer, format="PNG")
    buffer.seek(0)

    await update.message.reply_text(f"Ta page de validation : {url}")
    await update.message.reply_photo(photo=buffer, caption="QR code vers ta page de validation")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Annulé.")
    return ConversationHandler.END


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={REPONDRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, repondre)]},
            fallbacks=[CommandHandler("cancel", cancel)],
        )
    )
    app.run_polling()


if __name__ == "__main__":
    main()
