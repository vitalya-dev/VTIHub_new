import os
import logging
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Frame, BaseDocTemplate, PageTemplate, Flowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER

# Initialize logger for this module
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
    Generates a PDF label and returns the file path.
    Returns None if an error occurs.
    """
    width = 57 * mm
    height = 40 * mm
    
    # --- FONT SETUP ---
    font_name = 'Consolas'
    try:
        # Register regular Consolas
        pdfmetrics.registerFont(TTFont(font_name, 'consola.ttf'))
        # Register bold Consolas
        pdfmetrics.registerFont(TTFont('Consolas-Bold', 'consolab.ttf'))
        
        pdfmetrics.registerFontFamily(font_name, normal=font_name, bold='Consolas-Bold')
    except Exception as e:
        logger.error(f"ERROR: Font files 'consola.ttf' or 'consolab.ttf' not found! Details: {e}")
        return None

    # --- 1. HEADER FUNCTION (called on EVERY page) ---
    def draw_header(canvas, doc):
        canvas.saveState()
        
        # Check if logo exists before drawing to prevent crashes
        if os.path.exists(logo_path):
            canvas.drawImage(logo_path, 2*mm, 31*mm, width=8*mm, height=8*mm, mask='auto')
        else:
            logger.warning(f"Logo not found at {logo_path}, skipping logo drawing.")

        canvas.setFont(font_name, 9)
        canvas.drawString(12*mm, 35.5*mm, "ООО «ВТИ»")
        
        canvas.setFont(font_name, 4)
        canvas.drawString(12*mm, 33.5*mm, "ул Советская 26, г. Керчь")
        
        canvas.setFont(font_name, 4)
        canvas.drawString(12*mm, 31.5*mm, "8 (978) 762-89-67 | 8 (978) 010-49-49")

        # Divider line
        canvas.setLineWidth(0.5)
        canvas.line(0*mm, 29*mm, width, 29*mm)
        
        canvas.restoreState()

    # --- 2. DOCUMENT AND TEMPLATE SETUP ---
    
    # Create the base document
    doc = BaseDocTemplate(filename, pagesize=(width, height))
    
    # The Frame (occupies space strictly under the line)
    frame = Frame(
        0, 0, width, 29*mm, 
        leftPadding=2*mm, bottomPadding=1*mm, rightPadding=2*mm, topPadding=1*mm,
        showBoundary=0 
    )
    
    # Create the template: link our Frame and the draw_header function
    template = PageTemplate(id='LabelTemplate', frames=[frame], onPage=draw_header)
    doc.addPageTemplates([template])

    # --- 3. STYLES AND TEXT SETUP ---
    style_phone = ParagraphStyle(
        'PhoneStyle', fontName=font_name, fontSize=16, alignment=TA_CENTER, spaceAfter=5*mm      
    )
    style_info = ParagraphStyle(
        'InfoStyle', fontName=font_name, fontSize=6, leading=9            
    )

    # Build the story
    story: list[Flowable] = [
        Paragraph(f"<b>{phone}</b>", style_phone),
        Paragraph(f"<b>Принял(а):</b> {operator_name}", style_info),
        Paragraph(f"<b>Время:</b> {time_str}", style_info),
        Paragraph(f"<b>Описание:</b> {description}", style_info)
    ]
    
    # --- 4. RUN THE MAGIC ---
    try:
        # The build command will automatically split the story across pages!
        doc.build(story)
        logger.info(f"Success! Multipage label saved as {filename}")
        return filename
    except Exception as e:
        logger.error(f"Error building PDF: {e}")
        return None