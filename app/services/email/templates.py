from __future__ import annotations

from dataclasses import dataclass

_WRAP = (
    '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;'
    'margin:0 auto;color:#1a1a1a">{body}'
    '<hr style="border:none;border-top:1px solid #eee;margin:32px 0">'
    '<p style="font-size:12px;color:#888">Zent — Crafted for the discerning.</p></div>'
)


@dataclass
class RenderedEmail:
    subject: str
    html: str
    text: str


def account_confirmation(*, first_name: str | None, verify_url: str) -> RenderedEmail:
    name = first_name or "there"
    body = (
        f"<h2>Welcome to Zent, {name}.</h2>"
        "<p>Your account is ready. You can confirm your email address any time using "
        f'the link below.</p><p><a href="{verify_url}">Confirm my email</a></p>'
    )
    return RenderedEmail(
        subject="Welcome to Zent",
        html=_WRAP.format(body=body),
        text=f"Welcome to Zent, {name}. Confirm your email: {verify_url}",
    )


def password_reset(*, first_name: str | None, reset_url: str) -> RenderedEmail:
    name = first_name or "there"
    body = (
        f"<h2>Reset your password</h2><p>Hi {name}, we received a request to reset your "
        "Zent password. This link expires in one hour.</p>"
        f'<p><a href="{reset_url}">Choose a new password</a></p>'
        "<p style=\"font-size:13px;color:#888\">If you didn't ask for this, you can ignore "
        "this email.</p>"
    )
    return RenderedEmail(
        subject="Reset your Zent password",
        html=_WRAP.format(body=body),
        text=f"Reset your Zent password: {reset_url}",
    )
