import asyncio
import logging
import argparse
import json # NEW: For parsing JSON data from the Web App

from aiogram import Bot, Dispatcher, F # NEW: F is used for filtering message types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
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

# Initialize the Dispatcher
dp = Dispatcher()

# --- HANDLERS ---

@dp.message(CommandStart())
async def cmd_start(message: Message):
    """
    Handles the /start command.
    Shows a keyboard with a button to open the Web App.
    """
    web_app_btn = KeyboardButton(
        text="📄 Новая Заявка",
        web_app=WebAppInfo(url=WEB_APP_URL)
    )

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[web_app_btn]],
        resize_keyboard=True
    )

    await message.answer(
        "🐶",
        reply_markup=keyboard
    )

# NEW HANDLER FOR STEP 3:
# This filter catches any message that contains web_app_data
# NEW HANDLER FOR STEP 3 (UPDATED WITH NONE CHECKS):
@dp.message(F.web_app_data)
async def web_app_data_handler(message: Message):
    """
    Catches and processes the JSON data sent from the Web App.
    Safely handles potential None values for web_app_data and from_user.
    """
    # Defensive check: Ensure both the web app data and the user object exist
    if not message.web_app_data or not message.from_user:
        logger.warning("Received a web app message, but web_app_data or from_user is None.")
        await message.answer("❌ Ошибка: не удалось получить данные формы или информацию о пользователе.")
        return

    try:
        # 1. Extract the raw JSON string safely
        raw_data = message.web_app_data.data
        
        # 2. Parse the JSON string
        parsed_data = json.loads(raw_data)
        
        # 3. Extract fields with fallbacks
        phone = parsed_data.get('phone', 'N/A')
        description = parsed_data.get('description', 'Нет описания')
        
        # Safe extraction of operator name (fallback if first_name is empty string or None somehow)
        operator_name = message.from_user.first_name or "Неизвестный оператор"
        
        logger.info(f"Received Web App Data: Operator={operator_name}, Phone={phone}, Desc={description}")
        
        # 4. Send temporary acknowledgment
        await message.answer(
            f"✅ Данные успешно получены!\n\n"
            f"<b>Принял(а):</b> {operator_name}\n"
            f"<b>Телефон:</b> {phone}\n"
            f"<b>Описание:</b> {description}\n\n"
            f"<i>Генерирую тикет... 🖨️</i>"
        )
        
    except json.JSONDecodeError:
        logger.error("Failed to decode JSON from Web App")
        await message.answer("❌ Ошибка при чтении данных с формы. Пожалуйста, попробуй еще раз.")
    except Exception as e:
        logger.error(f"Unexpected error in web_app_data_handler: {e}")
        await message.answer("❌ Произошла непредвиденная ошибка при обработке данных.")

# --- MAIN RUNNER ---

async def main():
    parser = argparse.ArgumentParser(description="VTI Hub Ticket Bot on Aiogram 3")
    parser.add_argument('--token', required=True, help='Your Telegram Bot Token')
    args = parser.parse_args()

    bot = Bot(token=args.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    logger.info("Starting bot...")

    try:
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