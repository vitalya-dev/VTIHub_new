import os
import logging
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
# Убрали импорты Table, TableStyle и Image, так как они больше не нужны
from reportlab.platypus import Paragraph, Frame, BaseDocTemplate, PageTemplate, Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT

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
            'HeaderTitle', fontName=font_name, fontSize=10, leading=11, alignment=TA_LEFT
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

        # --- ОТРИСОВКА ЛОГОТИПА ВРУЧНУЮ ---
        if os.path.exists(logo_path):
            # Рисуем логотип на координатах x=2mm, y=30.5mm
            canvas.drawImage(logo_path, 2*mm, 30.5*mm, width=8*mm, height=8*mm, mask='auto')
        else:
            logger.warning(f"Логотип не найден по пути {logo_path}, пропускаем.")

        # --- ФРЕЙМ ТОЛЬКО ДЛЯ ТЕКСТА ШАПКИ ---
        # Начинается по X с 11 мм (чтобы пропустить логотип), по Y с 29 мм
        header_frame = Frame(
            12*mm, 29*mm, width - 11*mm, 11*mm, 
            leftPadding=1*mm, bottomPadding=0, rightPadding=2*mm, topPadding=1*mm,
            showBoundary=0 # Поставь 1, чтобы увидеть границы текста шапки
        )
        
        # Добавляем текст во фрейм и рисуем на холсте
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
        showBoundary=0 
    )
    
    template = PageTemplate(id='LabelTemplate', frames=[frame], onPage=draw_header)
    doc.addPageTemplates([template])

    # --- 3. СТИЛИ И ТЕКСТ ОСНОВНОГО БЛОКА ---
    style_phone = ParagraphStyle(
        'PhoneStyle', fontName=font_name, fontSize=14, alignment=TA_CENTER, spaceAfter=3*mm      
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
    logger.info("Запуск тестовой генерации этикетки...")
    
    test_description = (
        "Ноутбук не включается. При нажатии на кнопку питания мигает индикатор 3 раза. "
        "Клиент просит сохранить все данные с диска D:, особенно папку с фотографиями. "
        "Также нужно почистить систему охлаждения и заменить термопасту."
    )
    
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
    else:
        logger.error("Тест провален. Файл не был создан. Проверь наличие шрифтов!")