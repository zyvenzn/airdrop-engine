import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
router = Router()


def mini_app_url() -> str:
    url = os.getenv("MINI_APP_URL", "").strip()
    if not url.startswith("https://"):
        raise RuntimeError("MINI_APP_URL must be a public HTTPS URL")
    return url.rstrip("/")


@router.message(CommandStart())
async def start(message: Message) -> None:
    app_url = mini_app_url()
    command = (message.text or "").split(maxsplit=1)
    payload = command[1].strip() if len(command) > 1 else ""
    if payload.startswith("ref_"):
        referrer_id = payload[4:]
        if referrer_id and len(referrer_id) <= 64 and all(c.isalnum() or c in "-_" for c in referrer_id):
            app_url = app_url + "?ref=" + referrer_id
    text = (
        "⚡ <b>Airdrop Engine</b>\n\n"
        "Welcome to your points hub. Start a farming cycle, complete missions, "
        "and invite your crew.\n\n"
        "Points are an in-app score and do not guarantee token allocation or monetary value."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Play Game", web_app=WebAppInfo(url=app_url))],
            [InlineKeyboardButton(text="🚀 Open Mini App", url=app_url)],
        ]
    )
    await message.answer(text, reply_markup=keyboard)


@router.message()
async def fallback(message: Message) -> None:
    await start(message)


async def health_server() -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readline()
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b"Content-Length: 14\r\nConnection: close\r\n\r\n"
                b'{"status":"ok"}'
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "0.0.0.0", int(os.getenv("PORT", "8000")))
    async with server:
        await server.serve_forever()


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    app_url = mini_app_url()
    bot = Bot(token=token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    await bot.set_my_commands([BotCommand(command="start", description="Open Airdrop Engine")])
    # Telegram bot identity is fetched at startup to validate the configured token.
    me = await bot.get_me()
    logging.info("Starting Airdrop Engine bot as @%s; Mini App URL configured", me.username)
    await asyncio.gather(health_server(), dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types()))


if __name__ == "__main__":
    asyncio.run(main())
