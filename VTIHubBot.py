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

import subprocess
from aiogram.types import CallbackQuery

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
        "🐶",
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

    status_msg = await message.answer("<i>Обрабатываю данные и генерирую тикет... 🖨️</i>")

    try:
        raw_data = message.web_app_data.data
        parsed_data = json.loads(raw_data)
        
        # --- NEW: Format the phone number ---
        raw_phone = parsed_data.get('phone', 'N/A')
        formatted_phone = format_phone_number(raw_phone)
        
        description = parsed_data.get('description', 'Нет описания')
        
        # --- NEW: Use @username if available, otherwise fallback to first_name ---
        user = message.from_user
        if user.username:
            operator_name = f"@{user.username}"
        else:
            operator_name = user.first_name or "Неизвестный оператор"
            
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        unique_filename = f"ticket_{user.id}_{datetime.now().strftime('%H%M%S')}.pdf"
        
        logger.info(f"Generating PDF for {operator_name}...")
        
        # We pass the formatted_phone to the PDF generator so it looks nice on paper too!
        pdf_path = ticket_generator.create_multipage_label(
            filename=unique_filename,
            operator_name=operator_name,
            phone=formatted_phone, 
            time_str=current_time,
            description=description
        )
        
        if pdf_path and os.path.exists(pdf_path):
            document = FSInputFile(pdf_path)
            
            caption_text = (
                f"✅ <b>Заявка создана!</b>\n\n"
                f"👤 Отправил(а): {operator_name}\n"
                f"🕒 Время: {current_time}\n"
                f"--- Детали заявки ---\n"
                f"📞 Телефон: <code>{formatted_phone}</code>\n"
                f"📝 Описание: {description}"
            )

            print_btn = InlineKeyboardButton(
                text="🖨️ Print", 
                callback_data="print_ticket"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[print_btn]])
            
            await message.answer_document(
                document=document,
                caption=caption_text,
                reply_markup=keyboard
            )
            
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
        try:
            await status_msg.delete()
        except Exception:
            pass



# Убедись, что импортировал Message
from aiogram.types import CallbackQuery, Message
import os
import asyncio

@dp.callback_query(F.data == "print_ticket")
async def print_ticket_handler(callback: CallbackQuery, bot: Bot):
    """
    Handles the "Print" button click.
    Shows a temporary printer emoji, downloads the PDF, and then cleans up.
    """
    # Гасим "часики" на кнопке без всплывающего текста
    await callback.answer("Подготовка к печати... 🖨️")

    if not callback.message or not isinstance(callback.message, Message):
        logger.warning(f"Print callback from user {callback.from_user.id}: Message is missing or inaccessible.")
        try:
            await bot.send_message(
                chat_id=callback.from_user.id, 
                text="❌ Исходное сообщение недоступно для печати."
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
        return

    document = callback.message.document
    if not document:
        await callback.message.answer("❌ Документ не найден в сообщении.")
        return

    # --- Отправляем временное сообщение с эмодзи ---
    temp_msg = await callback.message.reply("🖨️")
    
    temp_pdf_path = f"temp_print_{document.file_id}.pdf"

    try:
        # Скачиваем файл
        await bot.download(document, destination=temp_pdf_path)
        logger.info(f"Successfully downloaded PDF for printing: {temp_pdf_path}")

        # --- ЗАГЛУШКА ПЕЧАТИ ---
        logger.info(">>> TODO: Insert actual print logic here. <<<")
        await asyncio.sleep(1.5) # Имитируем задержку печати, чтобы увидеть эмодзи
        # ------------------------

        # Мы убрали сообщение об успешном скачивании, чтобы не засорять чат

    except Exception as e:
        logger.error(f"Failed to process document for printing: {e}")
        # Ошибку все-таки лучше показать, если что-то пошло не так
        await callback.message.reply("❌ Произошла ошибка при подготовке к печати.")
    finally:
        # 1. Удаляем скачанный PDF-файл
        if os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
                logger.info(f"Cleaned up temporary print file: {temp_pdf_path}")
            except Exception as e:
                logger.warning(f"Failed to delete {temp_pdf_path}: {e}")
        # 2. Удаляем временное сообщение с эмодзи
        try:
            await temp_msg.delete()
        except Exception as e:
            logger.warning(f"Failed to delete temporary emoji message: {e}")

import re

def format_phone_number(phone_str: str) -> str:
    """
    Formats a raw phone number string into a readable format.
    e.g., "+71234567890" -> "+7 (123) 456-78-90"
    e.g., "81234567890" -> "8 (123) 456-78-90"
    """
    if not phone_str or phone_str == 'N/A':
        return 'N/A'

    # Remove all non-numeric characters except '+'
    cleaned_phone = re.sub(r'[^\d+]', '', phone_str)

    if cleaned_phone.startswith('+7') and len(cleaned_phone) == 12:
        return f"{cleaned_phone[:2]} ({cleaned_phone[2:5]}) {cleaned_phone[5:8]}-{cleaned_phone[8:10]}-{cleaned_phone[10:12]}"
    elif cleaned_phone.startswith('8') and len(cleaned_phone) == 11:
        return f"{cleaned_phone[0]} ({cleaned_phone[1:4]}) {cleaned_phone[4:7]}-{cleaned_phone[7:9]}-{cleaned_phone[9:11]}"
    else:
        # Return as is if it doesn't match standard RU formats
        return phone_str



# --- UPDATE MAIN RUNNER ---
async def main():
    parser = argparse.ArgumentParser(description="VTI Hub Ticket Bot on Aiogram 3")
    parser.add_argument('--token', required=True, help='Your Telegram Bot Token')
    # NEW ARGUMENT FOR PRINTER:
    parser.add_argument('--print', dest='printer_name', default=None, help='Printer name for IrfanView')
    args = parser.parse_args()

    bot = Bot(token=args.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    # Inject the printer_name into the dispatcher so our callback handler can use it
    dp["printer_name"] = args.printer_name
    
    logger.info("Starting bot...")
    if args.printer_name:
        logger.info(f"Printer configured: {args.printer_name}")

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