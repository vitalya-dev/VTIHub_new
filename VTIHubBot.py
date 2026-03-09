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

@dp.message(F.text)
async def handle_plain_text(message: Message):
    """
    Catches any plain text message and routes it to the start command.
    DRY principle in action!
    """
    await cmd_start(message)


@dp.message(F.web_app_data)
async def web_app_data_handler(message: Message, bot: Bot, channel_id: str = ""):
    """
    Catches and processes the JSON data sent from the Web App.
    Generates a PDF ticket, sends it to the channel, and sends it back to the user.
    """
    # 1. Delete the gray system message "Data from the Web App..."
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete web_app_data system message: {e}")
        
    # 2. Defensive check
    if not message.web_app_data or not message.from_user:
        logger.warning("Received a web app message, but web_app_data or from_user is None.")
        await message.answer("❌ Ошибка: не удалось получить данные формы или информацию о пользователе.")
        return

    status_msg = await message.answer("<i>Обрабатываю данные и генерирую тикет... 🖨️</i>")

    try:
        # 3. Parse data
        raw_data = message.web_app_data.data
        parsed_data = json.loads(raw_data)
        
        raw_phone = parsed_data.get('phone', 'N/A')
        formatted_phone = format_phone_number(raw_phone)
        description = parsed_data.get('description', 'Нет описания')
        
        user = message.from_user
        if user.username:
            operator_name = f"@{user.username}"
        else:
            operator_name = user.first_name or "Неизвестный оператор"
            
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        unique_filename = f"ticket_{user.id}_{datetime.now().strftime('%H%M%S')}.pdf"
        
        logger.info(f"Generating PDF for {operator_name}...")
        
        # 4. Generate PDF
        pdf_path = ticket_generator.create_multipage_label(
            filename=unique_filename,
            operator_name=operator_name,
            phone=formatted_phone, 
            time_str=current_time,
            description=description
        )
        
        if pdf_path and os.path.exists(pdf_path):
            # Base caption
            caption_text = (
                f"✅ <b>Заявка создана!</b>\n\n"
                f"👤 Отправил(а): {operator_name}\n"
                f"🕒 Время: {current_time}\n"
                f"--- Детали заявки ---\n"
                f"📞 Телефон: <code>{formatted_phone}</code>\n"
                f"📝 Описание: {description}"
            )

            # --- 5. SEND TO CHANNEL ---
            channel_link = ""
            if channel_id:
                try:
                    # We need a fresh FSInputFile for each send operation
                    channel_doc = FSInputFile(pdf_path)
                    sent_msg = await bot.send_document(
                        chat_id=channel_id,
                        document=channel_doc,
                        caption=caption_text
                    )
                    logger.info(f"Successfully sent ticket to channel {channel_id}")
                    
                    # Generate the link to the channel message if it's a supergroup/channel (-100...)
                    if str(channel_id).startswith("-100"):
                        clean_channel_id = str(channel_id)[4:]
                        channel_link = f"\n\n🔗 <a href='https://t.me/c/{clean_channel_id}/{sent_msg.message_id}'>Посмотреть вашу заявку в канале</a>"
                except Exception as e:
                    logger.error(f"Failed to send to channel {channel_id}: {e}")

            # --- 6. SEND TO USER ---
            user_caption = caption_text + channel_link

            print_btn = InlineKeyboardButton(
                text="🖨️ Print", 
                callback_data="print_ticket"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[print_btn]])
            
            # Second fresh FSInputFile for the user
            user_doc = FSInputFile(pdf_path)
            
            await message.answer_document(
                document=user_doc,
                caption=user_caption,
                reply_markup=keyboard
            )
            
            # 7. Clean up
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
        # Delete the temporary "Processing..." message
        try:
            await status_msg.delete()
        except Exception:
            pass



@dp.callback_query(F.data == "print_ticket")
async def print_ticket_handler(callback: CallbackQuery, bot: Bot, printer_name: str = ""):
    """
    Обрабатывает нажатие на кнопку печати.
    Скачивает PDF, отправляет в PDFXCview и убивает процесс, если он завис.
    """
    await callback.answer("Подготовка к печати... 🖨️")

    if not callback.message or not isinstance(callback.message, Message):
        logger.warning(f"Print callback from user {callback.from_user.id}: Message is missing.")
        try:
            await bot.send_message(callback.from_user.id, "❌ Исходное сообщение недоступно.")
        except Exception:
            pass
        return

    document = callback.message.document
    if not document:
        await callback.message.answer("❌ Документ не найден.")
        return

    if not printer_name:
        await callback.message.answer("❌ Внимание: Принтер не настроен. Запустите бота с флагом --print.")
        return

    temp_msg = await callback.message.reply("🖨️ Отправляю на принтер...")
    temp_pdf_path = os.path.abspath(f"temp_print_{document.file_id}.pdf")
    
    # Настраиваем время ожидания в секундах
    PRINT_TIMEOUT = 10.0 

    try:
        await bot.download(document, destination=temp_pdf_path)
        logger.info(f"Downloaded PDF: {temp_pdf_path}")
        
        # Запускаем PDFXCview асинхронно
        process = await asyncio.create_subprocess_exec(
            "PDFXCview", 
            "/printto", 
            printer_name, 
            temp_pdf_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            # Ждем выполнения команды с ограничением по времени
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=PRINT_TIMEOUT)
            
            if process.returncode == 0:
                logger.info("Успешно отправлено на печать.")
                # Опционально: можно написать "Печать завершена" вместо эмодзи
            else:
                error_msg = stderr.decode('utf-8', errors='ignore') or "Неизвестная ошибка программы"
                logger.error(f"Ошибка печати (код {process.returncode}): {error_msg}")
                await callback.message.reply("❌ Произошла ошибка при отправке на принтер.")
                
        except asyncio.TimeoutError:
            # Если время вышло, принудительно убиваем процесс PDFXCview
            logger.error(f"Процесс печати завис (превышен таймаут {PRINT_TIMEOUT}с). Убиваем процесс...")
            try:
                process.kill()
                await process.communicate() # Позволяем asyncio очистить ресурсы убитого процесса
            except ProcessLookupError:
                pass # Процесс уже успел завершиться сам
            
            await callback.message.reply(f"❌ Принтер или программа не отвечают (таймаут {PRINT_TIMEOUT} сек).")

    except Exception as e:
        logger.error(f"Непредвиденная ошибка при подготовке к печати: {e}")
        await callback.message.reply("❌ Произошла непредвиденная ошибка.")
    finally:
        # Убираем за собой файл и сообщение с эмодзи
        if os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
            except Exception as e:
                logger.warning(f"Не удалось удалить файл {temp_pdf_path}: {e}")
                
        try:
            await temp_msg.delete()
        except Exception:
            pass

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
    parser.add_argument('--print', dest='printer_name', default="", help='Printer name for PDFXCview')
    parser.add_argument('--channel', dest='channel_id', default="", help='Target Channel ID')
    args = parser.parse_args()

    bot = Bot(token=args.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    # Inject args into the dispatcher so our callback handler can use it
    dp["printer_name"] = args.printer_name
    dp["channel_id"] = args.channel_id
    
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