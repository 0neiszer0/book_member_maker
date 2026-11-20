"""Send school email authentication codes without exposing provider errors."""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

import requests


DEFAULT_FROM = '책 먹는 호반우 <noreply@knu-read.xyz>'


class MailDeliveryError(RuntimeError):
    """The configured provider could not accept the verification email."""


def send_verification_code(to_email, code, purpose_label):
    provider = os.environ.get('MAIL_PROVIDER', 'disabled').strip().lower()
    sender = os.environ.get('MAIL_FROM') or DEFAULT_FROM
    subject = f'[책 먹는 호반우] {purpose_label} 인증코드'
    body = f'인증코드는 {code}입니다. 10분 안에 입력해주세요. 직접 요청하지 않았다면 이 메일을 무시하셔도 됩니다.'
    try:
        if provider == 'resend' and (api_key := os.environ.get('RESEND_API_KEY')):
            requests.post('https://api.resend.com/emails', timeout=10,
                          headers={'Authorization': f'Bearer {api_key}'},
                          json={'from': sender, 'to': [to_email], 'subject': subject, 'text': body}).raise_for_status()
            return
        if provider == 'brevo' and (api_key := os.environ.get('BREVO_API_KEY')):
            sender_name, sender_email = parseaddr(sender)
            requests.post('https://api.brevo.com/v3/smtp/email', timeout=10, headers={'api-key': api_key},
                          json={'sender': {'name': sender_name, 'email': sender_email}, 'to': [{'email': to_email}],
                                'subject': subject, 'textContent': body}).raise_for_status()
            return
        if provider == 'smtp' and (host := os.environ.get('SMTP_HOST')):
            message = EmailMessage()
            message['From'], message['To'], message['Subject'] = sender, to_email, subject
            message.set_content(body)
            port = int(os.environ.get('SMTP_PORT') or 587)
            tls = os.environ.get('SMTP_USE_TLS', 'true').strip().lower() in ('true', '1', 'yes', 'on')
            user = os.environ.get('SMTP_USER')
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                if tls:
                    smtp.starttls(context=ssl.create_default_context())
                if user:
                    smtp.login(user, os.environ.get('SMTP_PASSWORD') or '')
                smtp.send_message(message)
            return
    except (requests.RequestException, OSError, ValueError):
        raise MailDeliveryError('Verification email delivery failed.') from None
    raise MailDeliveryError('Verification email provider is not configured.')
