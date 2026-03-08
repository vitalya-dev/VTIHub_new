import asyncio
import logging
import argparse
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# NEW IMPORTS FOR STEP 2:
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# URL of your web application
WEB_APP_URL = "https://vitalya-dev.github.io/VTIHub/ticket_app.html"

# Initialize the Dispatcher (it routes incoming updates to handlers)
dp = Dispatcher()

# --- HANDLERS ---

# This decorator tells the bot to run this function when it sees the /start command
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """
    Handles the /start command.
    Shows a keyboard with a button to open the Web App.
    """
    # 1. Create a button that opens the Web App
    web_app_btn = KeyboardButton(
        text="📄 Новая Заявка",
        web_app=WebAppInfo(url=WEB_APP_URL)
    )

    # 2. Create the keyboard layout (a list of lists of buttons)
    # resize_keyboard=True makes the buttons fit nicely on the screen
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[web_app_btn]],
        resize_keyboard=True,
        one_time_keyboard=False
    )

    # 3. Send a welcoming message with the keyboard attached
    await message.answer(
        "🐶",
        reply_markup=keyboard
    )

# --- MAIN RUNNER ---

async def main():
    # Set up argument parser to securely receive the Telegram token
    parser = argparse.ArgumentParser(description="VTI Hub Ticket Bot on Aiogram 3")
    parser.add_argument('--token', required=True, help='Your Telegram Bot Token')
    args = parser.parse_args()

    # Initialize the Bot instance
    bot = Bot(token=args.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    logger.info("Starting bot...")

    try:
        # Drop pending updates and start polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"An error occurred during polling: {e}")
    finally:
        logger.info("Bot has been stopped.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt).")