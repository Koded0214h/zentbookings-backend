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


def staff_invite(*, first_name: str | None, role: str, set_password_url: str) -> RenderedEmail:
    name = first_name or "there"
    body = (
        f"<h2>You've been added to Zent</h2><p>Hi {name}, an administrator has "
        f"created a Zent <strong>{role}</strong> account for you. Set your password "
        f'to get started — this link expires in one hour.</p>'
        f'<p><a href="{set_password_url}">Set my password</a></p>'
    )
    return RenderedEmail(
        subject="Your Zent staff account",
        html=_WRAP.format(body=body),
        text=f"Hi {name}, set your Zent {role} account password: {set_password_url}",
    )


def _when(scheduled_at) -> str:
    # scheduled_at is UTC; render simply and label it
    return scheduled_at.strftime("%A, %d %B %Y at %H:%M UTC")


def tour_requested(
    *, visitor_name: str, property_title: str, scheduled_at, confirmation_code: str
) -> RenderedEmail:
    when = _when(scheduled_at)
    body = (
        f"<h2>Tour request received</h2><p>Hi {visitor_name}, we've received your request "
        f"to tour <strong>{property_title}</strong> on <strong>{when}</strong>.</p>"
        f"<p>Your reference is <strong>{confirmation_code}</strong>. An advisor will "
        "confirm shortly — you'll get another email once it's locked in.</p>"
    )
    return RenderedEmail(
        subject=f"Tour request received — {confirmation_code}",
        html=_WRAP.format(body=body),
        text=(
            f"Hi {visitor_name}, tour request for {property_title} on {when} received. "
            f"Reference {confirmation_code}. An advisor will confirm shortly."
        ),
    )


def tour_confirmed(
    *, visitor_name: str, property_title: str, scheduled_at, confirmation_code: str
) -> RenderedEmail:
    when = _when(scheduled_at)
    body = (
        f"<h2>Your tour is confirmed</h2><p>Hi {visitor_name}, your tour of "
        f"<strong>{property_title}</strong> is confirmed for <strong>{when}</strong>.</p>"
        f"<p>Show this reference on arrival: <strong>{confirmation_code}</strong>.</p>"
    )
    return RenderedEmail(
        subject=f"Tour confirmed — {confirmation_code}",
        html=_WRAP.format(body=body),
        text=(
            f"Hi {visitor_name}, your tour of {property_title} is confirmed for {when}. "
            f"Reference {confirmation_code}."
        ),
    )


def tour_cancelled(
    *, visitor_name: str, property_title: str, scheduled_at, confirmation_code: str
) -> RenderedEmail:
    when = _when(scheduled_at)
    body = (
        f"<h2>Tour cancelled</h2><p>Hi {visitor_name}, your tour of "
        f"<strong>{property_title}</strong> scheduled for <strong>{when}</strong> "
        f"({confirmation_code}) has been cancelled.</p>"
        "<p>You're welcome to book another time whenever suits you.</p>"
    )
    return RenderedEmail(
        subject=f"Tour cancelled — {confirmation_code}",
        html=_WRAP.format(body=body),
        text=(
            f"Hi {visitor_name}, your tour of {property_title} on {when} "
            f"({confirmation_code}) has been cancelled."
        ),
    )
