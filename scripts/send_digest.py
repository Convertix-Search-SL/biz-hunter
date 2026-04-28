"""Envía digest HTML por SMTP. Llamado desde la skill 'reporter'.

Uso:
    python scripts/send_digest.py --html-file data/reports/2026-04-28.html
    python scripts/send_digest.py --inline "<h1>...</h1>"
"""
import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path


def send(html: str, subject: str | None = None) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    pwd = os.environ["SMTP_PASSWORD"]
    sender = os.environ.get("SMTP_FROM") or user
    to = os.environ["SMTP_TO"]

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject or "Biz Hunter Digest"
    msg.set_content("Tu cliente no soporta HTML. Mira el HTML alternativo.")
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)

    print(f"Digest enviado a {to}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--html-file", type=Path, help="Archivo HTML a enviar")
    parser.add_argument("--inline", help="HTML literal inline")
    parser.add_argument("--subject", default=None)
    args = parser.parse_args()

    if args.html_file:
        if not args.html_file.is_file():
            print(f"No existe: {args.html_file}", file=sys.stderr)
            sys.exit(1)
        html = args.html_file.read_text()
    elif args.inline:
        html = args.inline
    else:
        print("Pasa --html-file o --inline", file=sys.stderr)
        sys.exit(1)

    send(html, subject=args.subject)
