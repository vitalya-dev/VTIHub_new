import asyncio
import logging
import argparse
import json
import os # NEW: For deleting the temporary PDF file
from datetime import datetime # NEW: For getting current time

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, FSInputFile # NEW: FSInputFile for sending documents
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# NEW: Import our custom PDF generator module
import ticket_generator 

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

WEB_APP_URL = "https://vitalya-dev.github.io/VTIHub/ticket_app.html"

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
        "Привет! Нажми на кнопку ниже, чтобы открыть форму приема техники 🐶",
        reply_markup=keyboard
    )


@dp.message(F.web_app_data)
async def web_app_data_handler(message: Message):
    """
    Catches and processes the JSON data sent from the Web App.
    Generates a PDF ticket and sends it back to the user.
    """
    if not message.web_app_data or not message.from_user:
        logger.warning("Received a web app message, but web_app_data or from_user is None.")
        await message.answer("❌ Ошибка: не удалось получить данные формы или информацию о пользователе.")
        return

    # Send a temporary "Processing" message
    status_msg = await message.answer("<i>Обрабатываю данные и генерирую тикет... 🖨️</i>")

    try:
        # Extract and parse data
        raw_data = message.web_app_data.data
        parsed_data = json.loads(raw_data)
        
        phone = parsed_data.get('phone', 'N/A')
        description = parsed_data.get('description', 'Нет описания')
        operator_name = message.from_user.first_name or "Неизвестный оператор"
        
        # Get current time formatted as YYYY-MM-DD HH:MM
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Create a unique filename for this specific ticket to avoid conflicts
        unique_filename = f"ticket_{message.from_user.id}_{datetime.now().strftime('%H%M%S')}.pdf"
        
        logger.info(f"Generating PDF for {operator_name}...")
        
        # Call our generator module
        pdf_path = ticket_generator.create_multipage_label(
            filename=unique_filename,
            operator_name=operator_name,
            phone=phone,
            time_str=current_time,
            description=description
            # NOTE: logo_path="logo.png" is used by default inside the function
        )
        
       # NEW IMPORTS (add these to the top of main.py):
    # from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        if pdf_path and os.path.exists(pdf_path):
            document = FSInputFile(pdf_path)
            
            # 1. Create the beautiful caption matching your old bot
            caption_text = (
                f"✅ <b>Заявка создана!</b>\n\n"
                f"👤 Отправил(а): {operator_name}\n"
                f"🕒 Время: {current_time}\n"
                f"--- Детали заявки ---\n"
                f"📞 Телефон: <code>{phone}</code>\n"
                f"📝 Описание: {description}"
            )

            # 2. Create the Inline "Print" button
            # We use a simple callback_data string. Later we will catch it.
            print_btn = InlineKeyboardButton(
                text="🖨️ Print", 
                callback_data="print_ticket"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[print_btn]])
            
            # 3. Send the document with the caption and the button
            await message.answer_document(
                document=document,
                caption=caption_text,
                reply_markup=keyboard
            )
            
            # Clean up temporary file
            try:
                os.remove(pdf_path)
                logger.info(f"Deleted temporary file {pdf_path}")
            except Exception as e:
                logger.warning(f"Failed to delete temporary file {pdf_path}: {e}")
                
        else:
            await message.answer("❌ Произошла ошибка при создании PDF-документа.")

    except json.JSONDecodeError:
        logger.error("Failed to decode JSON from Web App")
        await message.answer("❌ Ошибка при чтении данных с формы.")
    except Exception as e:
        logger.error(f"Unexpected error in web_app_data_handler: {e}")
        await message.answer("❌ Произошла непредвиденная ошибка при обработке данных.")
    finally:
        # Delete the temporary "Processing" message to keep the chat clean
        try:
            await status_msg.delete()
        except Exception:
            pass # Ignore errors if the message couldn't be deleted

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