import os
import logging
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Frame, BaseDocTemplate, PageTemplate, Flowable, Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# --- НОВЫЕ ИМПОРТЫ ДЛЯ QR-КОДА ---
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode import qr

# Инициализация логгера для этого модуля
logger = logging.getLogger(__name__)

def create_multipage_label(
    filename="label_output.pdf", 
    logo_path="logo.png", 
    operator_name="Unknown", 
    phone="N/A", 
    time_str="N/A", 
    description="No description"
) -> str | None:
    """
    Генерирует PDF этикетку и возвращает путь к файлу.
    Возвращает None, если произошла ошибка.
    """
    width = 57 * mm
    height = 40 * mm
    
    # --- НАСТРОЙКА ШРИФТОВ ---
    font_name = 'Consolas'
    try:
        pdfmetrics.registerFont(TTFont(font_name, 'consola.ttf'))
        pdfmetrics.registerFont(TTFont('Consolas-Bold', 'consolab.ttf'))
        pdfmetrics.registerFontFamily(font_name, normal=font_name, bold='Consolas-Bold')
    except Exception as e:
        logger.error(f"ОШИБКА: Файлы шрифтов 'consola.ttf' или 'consolab.ttf' не найдены! Детали: {e}")
        return None

    # --- 1. ФУНКЦИЯ ШАПКИ (вызывается на КАЖДОЙ странице) ---
    def draw_header(canvas, doc):
        canvas.saveState()
        
        # Стили для шапки
        style_header_title = ParagraphStyle(
            'HeaderTitle', fontName=font_name, fontSize=11, leading=11, alignment=TA_LEFT
        )
        style_header_text = ParagraphStyle(
            'HeaderText', fontName=font_name, fontSize=7, leading=7.5, alignment=TA_LEFT
        )

        # Текстовая часть шапки
        header_text_elements: list[Flowable] = [
            Paragraph("<b>ООО «ВТИ»</b>", style_header_title),
            Paragraph("ул Советская 26, г. Керчь", style_header_text),
            Paragraph("8 (978) 762-89-67", style_header_text)
        ]

        # --- ФРЕЙМ ДЛЯ QR-КОДА (вместо логотипа) ---
        # Возвращаем на одну линию с текстом (Y=29 мм)
        # Устанавливаем topPadding=1*mm для идеального выравнивания с текстом
        qr_frame = Frame(
            0*mm, 29*mm, 12*mm, 11*mm, 
            leftPadding=2*mm, bottomPadding=0, rightPadding=0, topPadding=1*mm,
            showBoundary=0 # Включено для дебага
        )

        # Очищаем телефон от лишних символов (оставляем только цифры и плюс)
        clean_phone = "".join(c for c in phone if c.isdigit() or c == '+')
        if not clean_phone:
            clean_phone = phone # Резервный вариант, если номер пустой
            
        # Создаем виджет QR-кода только с очищенным номером телефона
        qr_code = qr.QrCodeWidget(clean_phone)
        
        # Получаем исходные габариты QR-кода для правильного масштабирования
        bounds = qr_code.getBounds()
        qr_w = bounds[2] - bounds[0]
        qr_h = bounds[3] - bounds[1]
        
        # Наш целевой размер под QR-код — 10x10 мм
        target_size = 10 * mm
        
        # Рассчитываем матрицу трансформации, чтобы сжать/растянуть код до 10 мм
        transform = [target_size / qr_w, 0, 0, target_size / qr_h, 0, 0]
        
        # Оборачиваем в Drawing для совместимости с элементами ReportLab
        d = Drawing(target_size, target_size, transform=transform)
        d.add(qr_code)
        
        # Добавляем рисунок во фрейм
        qr_frame.addFromList([d], canvas)

        # --- ФРЕЙМ ТОЛЬКО ДЛЯ ТЕКСТА ШАПКИ ---
        header_frame = Frame(
            12*mm, 29*mm, width - 12*mm, 11*mm, 
            leftPadding=2*mm, bottomPadding=0, rightPadding=2*mm, topPadding=1*mm,
            showBoundary=0 # Включено для дебага
        )
        
        # Добавляем текст во фрейм
        header_frame.addFromList(header_text_elements, canvas)

        # Разделительная линия на 29 мм
        canvas.setLineWidth(0.5)
        canvas.line(0*mm, 29*mm, width, 29*mm)
        
        canvas.restoreState()

    # --- 2. НАСТРОЙКА ДОКУМЕНТА И ШАБЛОНА ---
    
    doc = BaseDocTemplate(filename, pagesize=(width, height))
    
    # Главный фрейм
    frame = Frame(
        0, 0, width, 29*mm, 
        leftPadding=2*mm, bottomPadding=1*mm, rightPadding=2*mm, topPadding=1*mm,
        showBoundary=0 # Включено для дебага
    )
    
    template = PageTemplate(id='LabelTemplate', frames=[frame], onPage=draw_header)
    doc.addPageTemplates([template])

    # --- 3. СТИЛИ И ТЕКСТ ОСНОВНОГО БЛОКА ---
    style_phone = ParagraphStyle(
        'PhoneStyle', fontName=font_name, fontSize=14, alignment=TA_CENTER, spaceAfter=2*mm      
    )
    style_info = ParagraphStyle(
        'InfoStyle', fontName=font_name, fontSize=9, leading=9            
    )

    story: list[Flowable] = [
        Paragraph(f"<b>{phone}</b>", style_phone),
        Paragraph(f"<b>Принял(а):</b> {operator_name}", style_info),
        Paragraph(f"<b>Время:</b> {time_str}", style_info),
        Paragraph(f"<b>Описание:</b> {description}", style_info)
    ]
    
    # --- 4. СБОРКА ДОКУМЕНТА ---
    try:
        doc.build(story)
        logger.info(f"Успех! Многостраничная этикетка сохранена как {filename}")
        return filename
    except Exception as e:
        logger.error(f"Ошибка при создании PDF: {e}")
        return None
        
# ==========================================
# БЛОК ДЛЯ ОТЛАДКИ (DEBUG)
# ==========================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger.info("Запуск тестовой генерации этикетки с QR-кодом...")
    
    test_description = (
        "Ноутбук не включается. При нажатии на кнопку питания мигает индикатор 3 раза. "
        "Клиент просит сохранить все данные с диска D:, особенно папку с фотографиями. "
        "Также нужно почистить систему охлаждения и заменить термопасту."
    )
    
    # Аргумент logo_path оставляем для проверки обратной совместимости
    result_file = create_multipage_label(
        filename="test_label.pdf",
        logo_path="logo.png", 
        operator_name="Иван Иванов",
        phone="+7 (999) 123-45-67",
        time_str="14:30 15.05.2024",
        description=test_description
    )
    
    if result_file:
        logger.info(f"Тест пройден! Файл успешно создан: {os.path.abspath(result_file)}")
        logger.info("Открой PDF и проверь: в левом верхнем углу должен быть QR-код.")
        logger.info("Попробуй отсканировать его камерой телефона — должен появиться номер +79991234567.")
    else:
        logger.error("Тест провален. Файл не был создан. Проверь наличие шрифтов!")