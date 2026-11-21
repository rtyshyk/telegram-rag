"""Telegram user login via QR code (Telethon)."""

from __future__ import annotations

import asyncio
import getpass
import logging

import qrcode
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from settings import settings

logger = logging.getLogger(__name__)


def print_qr_login_url(url: str) -> None:
    """Render a tg://login URL as ASCII QR in the terminal."""
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)
    print(
        f"\nLink (Telegram mobile → Settings → Devices → Link Desktop Device):\n{url}\n"
    )


async def _sign_in_2fa(client: TelegramClient) -> None:
    password = getpass.getpass("Telegram 2FA password: ")
    await client.sign_in(password=password)


async def authenticate_via_qr(client: TelegramClient) -> None:
    """Log in by scanning a QR code with an already authorized Telegram app."""
    await client.connect()
    if await client.is_user_authorized():
        logger.info("Telegram session already authorized")
        return

    timeout = settings.tg_qr_login_timeout_secs
    logger.info(
        "Scan the QR code in Telegram (Settings → Devices → Link Desktop Device)"
    )

    qr_login = await client.qr_login()
    while True:
        print_qr_login_url(qr_login.url)
        try:
            await qr_login.wait(timeout=timeout)
            break
        except asyncio.TimeoutError:
            logger.info("QR code expired; generating a new one")
            await qr_login.recreate()
        except SessionPasswordNeededError:
            await _sign_in_2fa(client)
            break

    me = await client.get_me()
    if me:
        try:
            display = me.first_name or me.username or str(me.id)
            logger.info("Signed in as %s", display)
        except UnicodeEncodeError:
            logger.info("Signed in successfully")
