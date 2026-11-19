import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app, render_template

OUTLOOK_SMTP_SERVER = "smtp-mail.outlook.com"
OUTLOOK_SMTP_PORT = 587
GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


class PasswordResetEmailError(Exception):
    pass


def send_password_reset_email(recipient, code):
    sender = current_app.config.get("MAIL_EMAIL")
    password = current_app.config.get("MAIL_APP_PASSWORD")
    if not isinstance(sender, str) or not sender.strip() or not isinstance(password, str) or not password:
        raise PasswordResetEmailError(
            "MAIL_EMAIL and MAIL_APP_PASSWORD must be configured."
        )

    sender_address = sender.strip().lower()
    if sender_address.endswith("@gmail.com") or sender_address.endswith("@googlemail.com"):
        smtp_server = GMAIL_SMTP_SERVER
        smtp_port = GMAIL_SMTP_PORT
        provider_name = "Gmail"
    else:
        smtp_server = OUTLOOK_SMTP_SERVER
        smtp_port = OUTLOOK_SMTP_PORT
        provider_name = "Outlook"

    message = EmailMessage()
    message["Subject"] = "Student Hub password reset code"
    message["From"] = sender.strip()
    message["To"] = recipient
    message.set_content(
        f"Your Student Hub password reset code is {code}. "
        "It expires in 15 minutes. Do not share this code."
    )
    message.add_alternative(
        render_template("auth/email.html", code=code),
        subtype="html",
    )

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(sender.strip(), password.strip())
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise PasswordResetEmailError(f"{provider_name} SMTP delivery failed.") from error
