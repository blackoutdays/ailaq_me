# telegram_bot.py

#пока еще не готов

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import asyncio
from django.conf import settings
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from ailaq.models import ClientProfile

class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.application = Application.builder().token(token).build()

    async def start(self, update: Update, context):
        await update.message.reply_text("Пришлите ваш email.")

    async def save_telegram_id(self, update: Update, context):
        user_email = update.message.text
        telegram_id = update.message.from_user.id

        profile = ClientProfile.objects.filter(email__email=user_email).first()
        # Здесь `email` поле OneToOne для CustomUser в ClientProfile

        if profile:
            profile.telegram_id = telegram_id
            profile.save()
            await update.message.reply_text("Telegram ID сохранён!")
        else:
            await update.message.reply_text("Пользователь с таким email не найден.")

    def register_handlers(self):
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.save_telegram_id)
        )

    async def run(self):
        self.register_handlers()
        await self.application.run_polling()

if __name__ == "__main__":
    bot = TelegramBot(token=settings.TELEGRAM_BOT_TOKEN)
    asyncio.run(bot.run())
