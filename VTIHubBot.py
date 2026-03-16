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


def get_initial_max_case_id(db_path: str) -> int:
    """
    Получает максимальный ID заявки при первом запуске. 
    Это нужно, чтобы бот не начал печатать все старые заявки, которые уже есть в базе.
    """
    conn = connect_db(db_path)
    max_id = 0
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(primkey_case) FROM cases")
            result = cursor.fetchone()
            if result and result[0] is not None:
                max_id = int(result[0])
                logger.info(f"Начальный максимальный ID в БД: {max_id}")
            else:
                logger.info("БД пуста или заявок нет, начинаем с ID 0.")
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении максимального ID: {e}")
        finally:
            conn.close()
    return max_id

def get_new_cases_from_db(db_path: str, last_id: int) -> list[sqlite3.Row]:
    """
    Запрашивает из базы все новые заявки, у которых ID строго больше, чем last_id.
    """
    conn = connect_db(db_path)
    new_cases = []
    if conn:
        try:
            cursor = conn.cursor()
            # Берем нужные поля из таблицы заявок (cases) 
            # и подтягиваем имя сотрудника из таблицы (fellows) через LEFT JOIN
            query = """
                SELECT 
                    c.primkey_case, c.case_number, c.department, c.type, c.manufacturer, 
                    c.model, c.serial, c.reason, c.equipment, c.defects, c.condition, 
                    c.fellow, c.client, c.phone, c.dp_phone, c.date_input, 
                    c.note_output, c.client_text,
                    f.fellow_nickname, f.fellow_name 
                FROM cases c
                LEFT JOIN fellows f ON c.fellow = f.primkey_fellow
                WHERE c.primkey_case > ?
                ORDER BY c.primkey_case ASC
            """
            cursor.execute(query, (last_id,))
            new_cases = cursor.fetchall()
            if new_cases:
                logger.info(f"Найдено {len(new_cases)} новых заявок в БД (после ID {last_id}).")
        except sqlite3.Error as e:
            logger.error(f"Ошибка при получении новых заявок: {e}")
        finally:
            conn.close()
    return new_cases


async def process_and_send_db_case(case_data: sqlite3.Row, bot: Bot, channel_id: str = "") -> None:
    """
    Обрабатывает заявку из БД: генерирует PDF и отправляет в канал (если указан).
    """
    case_id = case_data['primkey_case']
    logger.info(f"--- НАЧАЛО ОБРАБОТКИ ЗАЯВКИ ИЗ БД (ID: {case_id}) ---")

    # 1. Кто принял заявку
    submitter_id = case_data['fellow']
    fellow_nickname = case_data['fellow_nickname']
    fellow_name = case_data['fellow_name']
    
    operator_name = "Сотрудник из БД"
    if fellow_nickname:
        operator_name = fellow_nickname
    elif fellow_name:
        operator_name = fellow_name
    elif submitter_id:
        operator_name = f"ID сотрудника: {submitter_id}"

    # 2. Время (конвертируем Unix timestamp из базы)
    ts = case_data['date_input']
    formatted_time = "Неизвестно"
    if ts:
        try:
            formatted_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            formatted_time = str(ts)

    # 3. Телефон
    raw_phone_db = case_data['phone'] if case_data['phone'] else case_data['dp_phone']
    raw_phone_str = str(raw_phone_db) if raw_phone_db is not None else 'N/A'
    formatted_phone = format_phone_number(raw_phone_str)

    # 4. Собираем описание из разных полей
    db_device_model_parts = []
    if case_data['type']: db_device_model_parts.append(case_data['type'])
    if case_data['manufacturer']: db_device_model_parts.append(case_data['manufacturer'])
    if case_data['model']: db_device_model_parts.append(case_data['model'])
    if case_data['serial']: db_device_model_parts.append(f"(S/N: {case_data['serial']})")
    
    device_model = " ".join(filter(None, db_device_model_parts)).strip() or "Модель не указана"
    issue_desc = case_data['reason'] or "Неисправность не указана"
    accessories = case_data['equipment'] or ""

    description = f"{device_model}. {issue_desc}"
    if accessories:
        description += f". Комплект: {accessories}"

    # 5. Генерация PDF
    unique_filename = os.path.join(CACHE_DIR, f"ticket_db_{case_id}_{datetime.now().strftime('%H%M%S')}.pdf")
    
    logger.info(f"Генерация PDF для заявки из БД (ID: {case_id})...")
    
    pdf_path = ticket_generator.create_multipage_label(
        filename=unique_filename,
        operator_name=operator_name,
        phone=formatted_phone, 
        time_str=formatted_time,
        description=description
    )

    if not pdf_path or not os.path.exists(pdf_path):
        logger.error(f"❌ Ошибка: PDF для заявки из БД (ID: {case_id}) не был создан.")
        return

    # 6. Отправка в канал
    if channel_id:
        # Генерируем хештег
        phone_hashtag = get_phone_hashtag(raw_phone_str)
        hashtag_line = f"\n\n{phone_hashtag}" if phone_hashtag else ""

        caption_text = (
            f"✅ <b>Новая заявка из БД (№ {case_data['case_number'] or case_id})</b>\n\n"
            f"👤 Отправил(а): {operator_name}\n"
            f"🕒 Время: {formatted_time}\n"
            f"--- Детали заявки ---\n"
            f"📞 Телефон: <code>{formatted_phone}</code>\n"
            f"📝 Описание: {description}"
            f"{hashtag_line}\n"
            f"^^^^^^^^" # <-- Визуальный разделитель под чек для канала
        )

        print_btn = InlineKeyboardButton(
            text="🖨️ Print", 
            callback_data="print_ticket"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[print_btn]])

        try:
            channel_doc = FSInputFile(pdf_path)
            await bot.send_document(
                chat_id=channel_id,
                document=channel_doc,
                caption=caption_text,
                reply_markup=keyboard
            )
            logger.info(f"Успешно отправлено в канал {channel_id} (Заявка ID: {case_id})")
        except Exception as e:
            logger.error(f"Ошибка при отправке в канал {channel_id}: {e}")
    else:
        logger.info(f"PDF сгенерирован ({pdf_path}), но channel_id не указан. Отправка в канал пропущена.")

    logger.info(f"--- КОНЕЦ ОБРАБОТКИ ЗАЯВКИ (ID: {case_id}) ---")

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
            # Генерируем хештег
            phone_hashtag = get_phone_hashtag(raw_phone)
            hashtag_line = f"\n\n{phone_hashtag}" if phone_hashtag else ""

            # Базовый текст, который общий для всех
            caption_text = (
                f"✅ <b>Заявка создана!</b>\n\n"
                f"👤 Отправил(а): {operator_name}\n"
                f"🕒 Время: {current_time}\n"
                f"--- Детали заявки ---\n"
                f"📞 Телефон: <code>{formatted_phone}</code>\n"
                f"📝 Описание: {description}"
                f"{hashtag_line}"
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
                # Добавляем "отрывную" линию чека ТОЛЬКО для канала
                channel_caption = caption_text + "\n^^^^^^^^" 
                
                try:
                    channel_doc = FSInputFile(pdf_path)
                    sent_msg = await bot.send_document(
                        chat_id=channel_id,
                        document=channel_doc,
                        caption=channel_caption, # Отправляем текст с линией чека
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
            user_caption = caption_text + channel_link # Линию чека сюда НЕ добавляем
            
            user_doc = reusable_file_id if reusable_file_id else FSInputFile(pdf_path)
            
            await message.answer_document(
                document=user_doc,
                caption=user_caption,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
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

def get_phone_hashtag(phone_str: str) -> str:
    """
    Извлекает последние 4, 3 и 2 цифры из номера телефона для создания нескольких хештегов.
    Добавляет букву 't', так как Telegram не делает хештеги только из цифр кликабельными.
    Разносит хештеги широкими отступами для удобного нажатия с телефона.
    """
    if not phone_str or phone_str == 'N/A':
        return "" # Если номера нет, хештеги не делаем

    # Удаляем всё, кроме цифр
    digits_only = re.sub(r'\D', '', phone_str)

    if not digits_only:
        return ""

    tags = []
    
    # Если цифр 4 или больше, добавляем тег из 4 цифр
    if len(digits_only) >= 4:
        tags.append(f"#t{digits_only[-4:]}")
        
    # Если цифр 3 или больше, добавляем тег из 3 цифр
    if len(digits_only) >= 3:
        tags.append(f"#t{digits_only[-3:]}")
        
    # Если цифр 2 или больше, добавляем тег из 2 цифр
    if len(digits_only) >= 2:
        tags.append(f"#t{digits_only[-2:]}")
        
    # Если ввели какую-то ошибку и там всего 1 цифра
    if len(digits_only) == 1:
        tags.append(f"#t{digits_only}")

    # Соединяем теги широким пробелом и разделителем, чтобы увеличить зону клика
    return "  |  ".join(tags)

async def monitor_database(db_path: str, bot: Bot, channel_id: str = ""):
    """
    Фоновая асинхронная задача: проверяет изменение файла БД и обрабатывает новые заявки.
    """
    if not os.path.exists(db_path):
        logger.error(f"Файл БД не найден по пути: {db_path}. Мониторинг остановлен.")
        return

    logger.info(f"Начинаем мониторинг базы данных: {db_path}")
    
    # Формируем путь к файлу памяти для этой конкретной базы
    db_name = os.path.splitext(os.path.basename(db_path))[0]
    db_id_storage_file_path = os.path.join(ID_STORAGE_DIR, f"last_processed_id_{db_name}.json")

    # Инициализация последнего известного ID
    last_known_id = load_last_known_id_from_file(db_id_storage_file_path)
    
    if last_known_id is None:
        logger.info(f"Файл памяти не найден или пуст. Ищем максимальный ID в базе...")
        last_known_id = await asyncio.to_thread(get_initial_max_case_id, db_path)
        save_last_known_id_to_file(db_id_storage_file_path, last_known_id)
        logger.info(f"Начинаем работу с ID: {last_known_id}")
    else:
        logger.info(f"Загружен последний обработанный ID из памяти: {last_known_id}")

    # --- ПЕРВИЧНАЯ ПРОВЕРКА ПРИ СТАРТЕ ---
    logger.info("Проверяем, не накопились ли новые заявки пока бот спал...")
    initial_cases = await asyncio.to_thread(get_new_cases_from_db, db_path, last_known_id)
    
    if initial_cases:
        logger.info(f"Найдено {len(initial_cases)} пропущенных заявок! Начинаем обработку.")
        max_id_in_batch = last_known_id
        
        for case_row in initial_cases:
            # Передаем bot и channel_id
            await process_and_send_db_case(case_row, bot, channel_id)
            if case_row['primkey_case'] > max_id_in_batch:
                max_id_in_batch = case_row['primkey_case']
                
        if max_id_in_batch > last_known_id:
            last_known_id = max_id_in_batch
            save_last_known_id_to_file(db_id_storage_file_path, last_known_id)
            logger.info(f"Пропущенные заявки обработаны. Новый последний ID: {last_known_id}")
    else:
        logger.info("Пропущенных заявок нет. База актуальна.")
    # --- КОНЕЦ ПЕРВИЧНОЙ ПРОВЕРКИ ---

    last_mtime = os.path.getmtime(db_path)

    while True:
        try:
            # Проверяем файл каждые 3 секунды
            await asyncio.sleep(3) 
            
            current_mtime = os.path.getmtime(db_path)
            
            if current_mtime != last_mtime:
                logger.info("🚨 Обнаружено изменение файла БД! Ждем завершения записи...")
                last_mtime = current_mtime
                
                # Ждем пару секунд, чтобы внешняя программа успела полностью записать данные
                await asyncio.sleep(2) 
                
                # Запрашиваем новые заявки
                new_cases = await asyncio.to_thread(get_new_cases_from_db, db_path, last_known_id)
                
                if new_cases:
                    max_id_in_batch = last_known_id
                    
                    for case_row in new_cases:
                        # Передаем bot и channel_id
                        await process_and_send_db_case(case_row, bot, channel_id)
                        
                        if case_row['primkey_case'] > max_id_in_batch:
                            max_id_in_batch = case_row['primkey_case']
                    
                    if max_id_in_batch > last_known_id:
                        last_known_id = max_id_in_batch
                        save_last_known_id_to_file(db_id_storage_file_path, last_known_id)
                        logger.info(f"Память обновлена. Новый последний ID: {last_known_id}")
                else:
                    logger.info("Изменения в БД есть, но новых заявок (с бóльшим ID) не найдено.")
                
        except FileNotFoundError:
            logger.warning(f"Потерян доступ к файлу БД ({db_path}). Проверяю снова через 5 секунд...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при мониторинге БД: {e}", exc_info=True)
            await asyncio.sleep(5)

@dp.startup()
async def on_startup(bot: Bot, dispatcher: Dispatcher):
    """
    Выполняется один раз при старте бота.
    """
    # Достаем путь к БД и ID канала, которые мы передали в диспетчер при запуске.
    # Явно приводим к str(), чтобы анализаторы типов понимали, с чем работают, и не выдавали Any | None.
    db_path = str(dispatcher.get("db_path", ""))
    channel_id = str(dispatcher.get("channel_id", ""))
    
    if db_path:
        logger.info("Запускаем фоновые задачи...")
        # Передаем bot и channel_id в функцию мониторинга
        asyncio.create_task(monitor_database(db_path, bot, channel_id))
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