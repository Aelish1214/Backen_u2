import fitz
import pytesseract
from PIL import Image
import os
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as ReportLabImage, Preformatted
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from datetime import datetime
import re
import logging

# --------------------------
# Logger setup
logger = logging.getLogger("PDFBot")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# --------------------------
# PDF Extraction & Generation classes

class PDFExtractor:
    """Handles PDF text extraction"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def extract_text(self, file_path: str) -> str:
        text_parts = []
        try:
            with fitz.open(file_path) as pdf:
                for page_num, page in enumerate(pdf):
                    page_text = page.get_text()
                    if not page_text.strip():
                        self.logger.info(f"No text on page {page_num}, using OCR")
                        pix = page.get_pixmap()
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        page_text = pytesseract.image_to_string(img)
                    if page_text.strip():
                        text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")
        except Exception as e:
            self.logger.error(f"PDF text extraction failed: {e}")
            return f"Error extracting text from PDF: {str(e)}"
        full_text = "\n\n".join(text_parts).strip()
        self.logger.info(f"Extracted {len(full_text)} characters from PDF")
        return full_text

class PDFGenerator:
    """Handles PDF document generation"""
    
    def __init__(self, output_dir: str, logger):
        self.output_dir = output_dir
        self.logger = logger
        os.makedirs(self.output_dir, exist_ok=True)
    
    def _clean_text_for_pdf(self, text: str) -> str:
        cleaned = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        cleaned = re.sub(r'\*(.*?)\*', r'<i>\1</i>', cleaned)
        return cleaned
    
    def generate_report(self, title: str, content: str, user_id: str = None) -> dict:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            user_prefix = f"{user_id}_" if user_id else ""
            filename = f"report_{user_prefix}{timestamp}.pdf"
            filepath = os.path.join(self.output_dir, filename)
            
            doc = SimpleDocTemplate(filepath, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []
            
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                alignment=1,
                spaceAfter=20,
            )
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 20))
            
            content_paragraphs = content.split('\n\n')
            for para in content_paragraphs:
                if para.strip():
                    cleaned_para = self._clean_text_for_pdf(para)
                    story.append(Paragraph(cleaned_para, styles['Normal']))
                    story.append(Spacer(1, 12))
            
            doc.build(story)
            file_size = os.path.getsize(filepath)
            
            self.logger.info(f"Generated PDF report: {filepath} ({file_size} bytes)")
            
            return {
                "success": True,
                "filepath": filepath,
                "filename": filename,
                "download_url": f"/download/{filename}",
                "view_url": f"/view/{filename}",
                "size": file_size
            }
        except Exception as e:
            self.logger.error(f"PDF report generation failed: {e}")
            return {"success": False, "error": str(e), "filepath": None, "filename": None}
    
    def generate_code_document(self, code: str, title: str = "Generated Code", user_id: str = None) -> dict:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            user_prefix = f"{user_id}_" if user_id else ""
            filename = f"code_{user_prefix}{timestamp}.pdf"
            filepath = os.path.join(self.output_dir, filename)

            doc = SimpleDocTemplate(filepath, pagesize=A4)
            styles = getSampleStyleSheet()
            story = []

            title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=18, alignment=1, spaceAfter=20)
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 20))

            code_style = ParagraphStyle("CodeStyle", parent=styles["Normal"], fontName="Courier", fontSize=9, leading=11, leftIndent=10, rightIndent=10)
            story.append(Preformatted(code, code_style))

            doc.build(story)
            file_size = os.path.getsize(filepath)
            
            self.logger.info(f"Generated code PDF: {filepath} ({file_size} bytes)")
            
            return {"success": True, "filepath": filepath, "filename": filename, "download_url": f"/download/{filename}", "view_url": f"/view/{filename}", "size": file_size}
        except Exception as e:
            self.logger.error(f"Code PDF generation failed: {e}")
            return {"success": False, "error": str(e), "filepath": None, "filename": None}

    def generate_qa_document(self, question: str, answer: str, user_id: str = None) -> dict:
        content = f"Question:\n{question}\n\nAnswer:\n{answer}"
        return self.generate_report("Q&A Report", content, user_id)

class PDFManager:
    """Main PDF manager combining extraction and generation"""
    
    def __init__(self, output_dir: str = "generated_media", logger=None):
        self.logger = logger
        self.extractor = PDFExtractor(logger)
        self.generator = PDFGenerator(output_dir, logger)
    
    def extract_text_from_pdf(self, file_path: str) -> str:
        return self.extractor.extract_text(file_path)
    
    def create_report_pdf(self, title: str, content: str, user_id: str = None) -> dict:
        return self.generator.generate_report(title, content, user_id)
    
    def create_code_pdf(self, code: str, title: str = "Code Document", user_id: str = None) -> dict:
        return self.generator.generate_code_document(code, title, user_id)
    
    def create_qa_pdf(self, question: str, answer: str, user_id: str = None) -> dict:
        return self.generator.generate_qa_document(question, answer, user_id)

# --------------------------
# Chatbot PDF handler
pdf_manager = PDFManager(output_dir="generated_media", logger=logger)

def handle_user_message(user_message: str, user_id: str = "123"):
    pdf_keywords = ["generate pdf", "create pdf", "make pdf", "pdf report", "convert to pdf"]
    
    if any(keyword in user_message.lower() for keyword in pdf_keywords):
        content_for_pdf = f"User request: {user_message}"
        pdf_result = pdf_manager.create_report_pdf(title="ChatBot PDF Report", content=content_for_pdf, user_id=user_id)
        
        if pdf_result["success"]:
            return f"📄 Your PDF is ready: <a href='{pdf_result['download_url']}'>{pdf_result['filename']}</a>"
        else:
            return "❌ Failed to generate PDF."
    else:
        return f"🤖 You said: {user_message}"

# --------------------------
# Example usage
if __name__ == "__main__":
    user_input = "Please generate PDF of this chat"
    response = handle_user_message(user_input, user_id="456")
    print(response)
