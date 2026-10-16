import random
import hashlib
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from extensions import db
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, TEXTS


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


import logging
import smtplib
import socket

logger = logging.getLogger(__name__)

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="color-scheme" content="dark" />
  <meta name="supported-color-schemes" content="dark" />
  <title>TichuStats</title>
</head>
<body style="margin:0; padding:0; background-color:#1c1c1e; color:#f5f5f7; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; -webkit-font-smoothing:antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#1c1c1e;">
    <tr>
      <td align="center" style="padding:80px 24px;">
        <table role="presentation" width="450" cellpadding="0" cellspacing="0" style="max-width:450px; width:100%; background-color:#1c1c1e; border:1px solid #2c2c2e; border-radius:18px; box-shadow:0 11px 34px rgba(0,0,0,0.65);">
          <tr>
            <td style="padding:65px 50px 55px; text-align:left;">
              <h1 style="margin:0 0 24px 0; font-size:34px; font-weight:600; letter-spacing:-0.374px; color:#f5f5f7; line-height:1.1;">TichuStats</h1>
              <p style="margin:0; font-size:17px; line-height:1.47; letter-spacing:-0.374px; color:#a1a1a6;">{intro}</p>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:20px; margin-bottom:20px;">
                <tr>
                  <td align="center" valign="middle" height="75" bgcolor="#252527" style="height:75px; padding:0; background-color:#252527; border:1px solid #2c2c2e; border-radius:12px; font-size:50px; line-height:75px; font-weight:700; letter-spacing:5px; color:#f5f5f7; text-align:center;">{code}</td>
                </tr>
              </table>
              <p style="margin:0; font-size:17px; line-height:1.47; letter-spacing:-0.374px; color:#a1a1a6;">{expiry}</p>
              <p style="margin:50px 0 0 0; font-size:14px; line-height:1.47; letter-spacing:-0.374px; color:#a1a1a6;">{sign}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#1c1c1e;">
    <tr>
      <td align="center" style="border-top:1px solid #2c2c2e; padding:20px 24px; font-size:12px; letter-spacing:-0.12px; color:#a1a1a6;">
        <a href="mailto:leon@tichu.dev" style="color:#a1a1a6; text-decoration:none;">Contact</a> | <a href="https://tichu.dev/privacy" style="color:#a1a1a6; text-decoration:none;">Privacy Policy</a>
      </td>
    </tr>
  </table>
</body>
</html>
"""

def send_email(to_email: str, code: str, language_code: str) -> bool:
    lang = language_code if language_code in TEXTS else "en"
    t = TEXTS[lang]
    m = CODE_EXPIRY_MINUTES

    subject = t["subject"]
    text_body = t["text"].format(code=code, m=m)
    html_body = HTML_TEMPLATE.format(
        lang=lang,
        intro=t["intro"],
        code=code,
        expiry=t["expiry"].format(m=m),
        sign=t["sign"],
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed — check SMTP_USER/SMTP_PASSWORD")
    except smtplib.SMTPRecipientsRefused:
        logger.warning("Email rejected for recipient: %s", to_email)
    except smtplib.SMTPException as e:
        logger.error("SMTP error sending to %s: %s", to_email, e)
    except (socket.timeout, ConnectionError, OSError) as e:
        logger.error("Connection error sending to %s: %s", to_email, e)
    return False


def generate_and_send_code(email: str,language_code:str) -> None:
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

    send_email(email, code,language_code)


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