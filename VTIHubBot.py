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
from aiogram.exceptions import TelegramBadRequest
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

CACHE_DIR = "pdf_cache"
os.makedirs(CACHE_DIR, exist_ok=True) # Создаст папку, если её нет

import sqlite3
import hashlib
from typing import Optional

# --- КОНСТАНТЫ ДЛЯ БД ---
# Секретный ключ для защиты файла с последним ID от ручного изменения
ID_STORAGE_SECRET_KEY = "your_very_secret_and_unique_key_here" # Замени на любую сложную строку
ID_STORAGE_DIR = "bot_data" # Папка, где бот будет хранить файл памяти
os.makedirs(ID_STORAGE_DIR, exist_ok=True)

# --- ФУНКЦИИ ДЛЯ РАБОТЫ С БД И ПАМЯТЬЮ ---

def connect_db(db_path: str) -> Optional[sqlite3.Connection]:
    """Устанавливает безопасное (только для чтения) подключение к SQLite."""
    try:
        # uri=True и ?mode=ro гарантируют, что мы случайно ничего не удалим из базы
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        # Позволяет обращаться к колонкам по их названию (например, row['case_number'])
        conn.row_factory = sqlite3.Row 
        return conn
    except sqlite3.Error as e:
        logger.error(f"Ошибка подключения к БД {db_path}: {e}")
        return None

def load_last_known_id_from_file(file_path: str) -> Optional[int]:
    """Загружает последний обработанный ID из файла памяти и проверяет его хеш."""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                data_from_file = json.load(f)
                
            stored_id = data_from_file.get("last_id")
            stored_hash = data_from_file.get("hash")

            if stored_id is None or stored_hash is None or not isinstance(stored_id, int):
                logger.warning(f"Неверный формат данных в файле памяти: {file_path}")
                return None

            # Создаем проверочный хеш
            data_to_verify = f"{stored_id}{ID_STORAGE_SECRET_KEY}"
            expected_hash = hashlib.sha256(data_to_verify.encode('utf-8')).hexdigest()

            if expected_hash == stored_hash:
                return stored_id
            else:
                logger.critical(f"ВНИМАНИЕ: Файл памяти {file_path} поврежден! Хеши не совпадают.")
                return None
        else:
            return None
    except Exception as e:
        logger.error(f"Ошибка чтения ID из файла {file_path}: {e}")
        return None

def save_last_known_id_to_file(file_path: str, last_id: int) -> None:
    """Сохраняет текущий ID и его защитный хеш в файл памяти."""
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Генерируем хеш
        data_to_hash = f"{last_id}{ID_STORAGE_SECRET_KEY}"
        current_hash = hashlib.sha256(data_to_hash.encode('utf-8')).hexdigest()
        
        data_to_store = {
            "last_id": last_id,
            "hash": current_hash
        }
        
        with open(file_path, 'w') as f:
            json.dump(data_to_store, f)
            
    except Exception as e:
        logger.error(f"Ошибка сохранения ID {last_id} в файл {file_path}: {e}")


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
        
        # НОВОЕ: Добавляем путь к папке кеша в имя файла
        unique_filename = os.path.join(CACHE_DIR, f"ticket_{user.id}_{datetime.now().strftime('%H%M%S')}.pdf")
        
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

            reusable_file_id = None 
            channel_link = ""

            # --- 5. SEND TO CHANNEL ---
            if channel_id:
                try:
                    channel_doc = FSInputFile(pdf_path)
                    sent_msg = await bot.send_document(
                        chat_id=channel_id,
                        document=channel_doc,
                        caption=caption_text,
                        reply_markup=keyboard
                    )
                    logger.info(f"Successfully sent ticket to channel {channel_id}")
                    
                    if sent_msg.document:
                        reusable_file_id = sent_msg.document.file_id
                    
                    if str(channel_id).startswith("-100"):
                        clean_channel_id = str(channel_id)[4:]
                        channel_link = f"\n\n🔗 <a href='https://t.me/c/{clean_channel_id}/{sent_msg.message_id}'>Посмотреть вашу заявку в канале</a>"
                except Exception as e:
                    logger.error(f"Failed to send to channel {channel_id}: {e}")

            # --- 6. SEND TO USER ---
            user_caption = caption_text + channel_link
            
            user_doc = reusable_file_id if reusable_file_id else FSInputFile(pdf_path)
            
            await message.answer_document(
                document=user_doc,
                caption=user_caption,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
            # НОВОЕ: Блок с os.remove(pdf_path) УДАЛЕН. Файл остается в кеше!
            logger.info(f"File {pdf_path} saved in cache.")
                
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



@dp.callback_query(F.data == "print_ticket")
async def print_ticket_handler(callback: CallbackQuery, bot: Bot, printer_name: str = ""):
    """
    Обрабатывает нажатие на кнопку печати.
    Ищет PDF в локальном кеше. Если нет - скачивает. Отправляет в PDFXCview.
    """
    user_id = callback.from_user.id

    # --- НОВОЕ: Безопасный ответ на нажатие ---
    try:
        await callback.answer("Подготовка к печати... 🖨️")
    except TelegramBadRequest:
        logger.warning(f"Клик от {user_id} устарел, пропускаем всплывающее уведомление.")
    except Exception as e:
        logger.error(f"Не удалось ответить на callback: {e}")
    # ------------------------------------------

    if not callback.message or not isinstance(callback.message, Message):
        logger.warning(f"Print callback from user {user_id}: Message is missing.")
        try:
            await bot.send_message(user_id, "❌ Исходное сообщение недоступно.")
        except Exception:
            pass
        return

    document = callback.message.document
    if not document:
        await bot.send_message(user_id, "❌ Документ не найден.")
        return

    if not printer_name:
        await bot.send_message(user_id, "❌ Внимание: Принтер не настроен. Запустите бота с флагом --print.")
        return

    try:
        temp_msg = await bot.send_message(user_id, "🖨️")
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        return

    # --- НОВОЕ: ЛОГИКА КЕШИРОВАНИЯ ---
    # Получаем оригинальное имя файла (или генерируем запасное из file_id)
    file_name = document.file_name or f"ticket_recovered_{document.file_id}.pdf"
    
    # Строим полный путь к файлу в нашей папке кеша
    cached_pdf_path = os.path.abspath(os.path.join(CACHE_DIR, file_name))
    
    PRINT_TIMEOUT = 10.0 

    try:
        # Проверяем, есть ли файл на диске
        if not os.path.exists(cached_pdf_path):
            logger.info(f"Файл {file_name} не найден в кеше. Скачиваем из Telegram...")
            await bot.download(document, destination=cached_pdf_path)
        else:
            logger.info(f"Файл {file_name} найден в кеше! Пропускаем скачивание.")

        # Запускаем PDFXCview асинхронно
        process = await asyncio.create_subprocess_exec(
            "PDFXCview",
            "/printto:pages=1", 
            printer_name, 
            cached_pdf_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=PRINT_TIMEOUT)
            if stdout:
                # Декодируем сырые байты в строку. errors='replace' защитит от падения, если кодировка системная (например, Windows CP866)
                program_output = stdout.decode('utf-8', errors='replace').strip()
                if program_output:
                    logger.info(f"PDFXCview stdout:\n{program_output}")
            if process.returncode == 0:
                logger.info(f"Успешно отправлено на печать пользователем {user_id}.")
            else:
                error_msg = stderr.decode('utf-8', errors='ignore') or "Неизвестная ошибка программы"
                logger.error(f"Ошибка печати (код {process.returncode}): {error_msg}")
                await bot.send_message(user_id, "❌ Произошла ошибка при отправке на принтер.")
                
        except asyncio.TimeoutError:
            logger.error(f"Процесс печати завис (превышен таймаут {PRINT_TIMEOUT}с). Убиваем процесс...")
            try:
                process.kill()
                await process.communicate()
            except ProcessLookupError:
                pass 
            
            await bot.send_message(user_id, f"❌ Принтер или программа не отвечают (таймаут {PRINT_TIMEOUT} сек).")

    except Exception as e:
        logger.error(f"Непредвиденная ошибка при подготовке к печати: {e}")
        await bot.send_message(user_id, "❌ Произошла непредвиденная ошибка.")
    finally:
        # НОВОЕ: Мы больше НЕ удаляем pdf-файл (os.remove убран)
        # Удаляем только статусное сообщение с эмодзи
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

async def monitor_database(db_path: str):
    """
    Фоновая асинхронная задача: проверяет изменение файла БД.
    """
    if not os.path.exists(db_path):
        logger.error(f"Файл БД не найден по пути: {db_path}. Мониторинг остановлен.")
        return

    logger.info(f"Начинаем мониторинг базы данных: {db_path}")
    
    last_mtime = os.path.getmtime(db_path)

    while True:
        try:
            await asyncio.sleep(5)
            
            current_mtime = os.path.getmtime(db_path)
            
            if current_mtime != last_mtime:
                logger.info("🚨 ВНИМАНИЕ: ФАЙЛ БАЗЫ ДАННЫХ БЫЛ ИЗМЕНЕН! 🚨")
                last_mtime = current_mtime
                
                # TODO: Логика обработки новых записей
                
        except FileNotFoundError:
            logger.warning(f"Потерян доступ к файлу БД ({db_path}). Проверяю снова через 5 секунд...")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при мониторинге БД: {e}")

@dp.startup()
async def on_startup(bot: Bot, dispatcher: Dispatcher):
    """
    Выполняется один раз при старте бота.
    """
    # Достаем путь к БД, который мы передадим при запуске
    db_path = dispatcher.get("db_path")
    
    if db_path:
        logger.info("Запускаем фоновые задачи...")
        asyncio.create_task(monitor_database(db_path))
    else:
        logger.info("Путь к БД не указан (--db). Мониторинг отключен.")


# --- UPDATE MAIN RUNNER ---
async def main():
    parser = argparse.ArgumentParser(description="VTI Hub Ticket Bot on Aiogram 3")
    parser.add_argument('--token', required=True, help='Your Telegram Bot Token')
    parser.add_argument('--print', dest='printer_name', default="", help='Printer name for PDFXCview')
    parser.add_argument('--channel', dest='channel_id', default="", help='Target Channel ID (e.g., -1001234567890)')
    parser.add_argument('--db', dest='db_path', default="", help='Path to the SQLite database on Samba share')
    
    args = parser.parse_args()

    # Инициализируем бота с дефолтным парсингом HTML
    bot = Bot(token=args.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    # Прокидываем все настройки в диспетчер, чтобы они были доступны в хэндлерах и при старте
    dp["printer_name"] = args.printer_name
    dp["channel_id"] = args.channel_id
    dp["db_path"] = args.db_path
    
    logger.info("Starting bot...")
    
    # Красиво выводим в консоль, какие модули у нас сейчас активны
    if args.printer_name:
        logger.info(f"🖨️ Printer configured: {args.printer_name}")
    if args.channel_id:
        logger.info(f"📢 Channel configured: {args.channel_id}")
    if args.db_path:
        logger.info(f"🗄️ Database configured: {args.db_path}")

    try:
        # Пропускаем старые апдейты, чтобы бот не начал отвечать на кнопки, нажатые пока он спал
        await bot.delete_webhook(drop_pending_updates=True)
        # Запускаем поллинг (и попутно триггерим @dp.startup)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ An error occurred during polling: {e}")
    finally:
        logger.info("🛑 Bot has been stopped.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt).")