import random
import hashlib
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

from extensions import db
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM

CODE_EXPIRY_MINUTES = 10
MAX_ATTEMPTS = 5


class LoginCode(db.Model):
    __tablename__ = "login_codes"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    code_hash = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


import logging
import smtplib
import socket

logger = logging.getLogger(__name__)


def _send_email(to_email: str, code: str) -> bool:
    subject = "Your login code"
    body = f"Your login code is: {code}\n\nIt expires in {CODE_EXPIRY_MINUTES} minutes."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed — check SMTP_USER/SMTP_PASSWORD")
        return False

    except smtplib.SMTPRecipientsRefused:
        logger.warning("Email rejected for recipient: %s", to_email)
        return False

    except smtplib.SMTPException as e:
        logger.error("SMTP error sending to %s: %s", to_email, e)
        return False

    except (socket.timeout, ConnectionError, OSError) as e:
        logger.error("Connection error sending to %s: %s", to_email, e)
        return False


def generate_and_send_code(email: str) -> None:
    # Invalidate any previous unused codes for this email
    LoginCode.query.filter_by(email=email, used=False).update({"used": True})

    code = f"{random.randint(0, 999999):06d}"
    print(f"CODE:{code}")

    login_code = LoginCode(
        email=email,
        code_hash=_hash_code(code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRY_MINUTES),
    )
    db.session.add(login_code)
    db.session.commit()

    _send_email(email, code)


def verify_code(email: str, code: str) -> bool:
    entry = (
        LoginCode.query
        .filter_by(email=email, used=False)
        .order_by(LoginCode.created_at.desc())
        .first()
    )

    if not entry:
        return False

    if entry.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return False

    if entry.attempts >= MAX_ATTEMPTS:
        return False

    entry.attempts += 1

    if entry.code_hash != _hash_code(code):
        db.session.commit()
        return False

    entry.used = True
    db.session.commit()
    return True