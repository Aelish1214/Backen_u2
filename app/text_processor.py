"""
Text Processor - Handles text formatting and processing for chat integration
Enhanced with selective PDF generation detection
"""

import re
from typing import Dict, List, Tuple, Optional


class TextProcessor:
    """Handles text processing and formatting for chat integration"""
    
    def __init__(self):
        self.max_chunk_size = 4000  # Max characters per chunk for chat
        
    def clean_extracted_text(self, text: str) -> str:
        """Clean and format extracted text from PDFs"""
        if not text or not text.strip():
            return ""
        
        # Remove excessive whitespace
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)  # Multiple newlines to double
        text = re.sub(r' +', ' ', text)  # Multiple spaces to single
        
        # Clean up page markers
        text = re.sub(r'--- Page \d+ ---\n?', '', text)
        
        # Remove common PDF artifacts
        text = re.sub(r'\f', '', text)  # Form feed characters
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]', '', text)  # Non-printable chars
        
        return text.strip()
    
    def format_for_chat(self, text: str, title: str = "Document Content") -> str:
        """Format extracted text for chat display"""
        if not text or not text.strip():
            return "No readable text found in the document."
        
        # Truncate if too long
        if len(text) > self.max_chunk_size:
            text = text[:self.max_chunk_size] + "..."
            truncated_note = f"\n\n*Note: Content truncated to {self.max_chunk_size} characters for display.*"
        else:
            truncated_note = ""
        
        formatted = f"📄 **{title}**\n\n{text}{truncated_note}"
        return formatted
    
    def chunk_text(self, text: str, chunk_size: int = None) -> List[str]:
        """Split long text into manageable chunks"""
        if chunk_size is None:
            chunk_size = self.max_chunk_size
            
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        paragraphs = text.split('\n\n')
        current_chunk = ""
        
        for paragraph in paragraphs:
            # If adding this paragraph would exceed chunk size
            if len(current_chunk) + len(paragraph) + 2 > chunk_size:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = paragraph
                else:
                    # Paragraph itself is too long, split it
                    words = paragraph.split()
                    temp_chunk = ""
                    for word in words:
                        if len(temp_chunk) + len(word) + 1 <= chunk_size:
                            temp_chunk += (" " + word) if temp_chunk else word
                        else:
                            if temp_chunk:
                                chunks.append(temp_chunk)
                            temp_chunk = word
                    current_chunk = temp_chunk
            else:
                current_chunk += ("\n\n" + paragraph) if current_chunk else paragraph
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def create_summary(self, text: str, max_length: int = 500) -> str:
        """Create a summary of the text"""
        if len(text) <= max_length:
            return text
        
        # Find good breaking points (sentences)
        sentences = re.split(r'[.!?]+', text)
        summary = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            if len(summary) + len(sentence) + 2 <= max_length:
                summary += (sentence + ". ") if summary else (sentence + ". ")
            else:
                break
        
        if not summary:
            # If no complete sentences fit, just truncate
            summary = text[:max_length] + "..."
        
        return summary.strip()


class MediaRequestDetector:
    """Detects requests for media generation (PDF, images, etc.) with enhanced selective PDF detection"""
    
    def __init__(self):
        # Explicit PDF keywords that clearly indicate PDF generation request
        self.explicit_pdf_keywords = [
            "generate pdf", "create pdf", "make pdf", "pdf report",
            "convert to pdf", "save as pdf", "download pdf", "export pdf",
            "pdf document", "make a pdf", "give me pdf", "give a pdf",
            "create document", "generate report", "make report"
        ]
        
        # Single word triggers for PDF
        self.single_word_pdf_triggers = ["pdf"]
        
        self.image_keywords = [
            "show me", "give me an image", "generate image", "create image",
            "diagram", "picture", "visual", "sketch", "draw", "illustration",
            "flowchart", "chart", "graph"
        ]
        
        # Enhanced PDF generation patterns with file context
        self.file_pdf_patterns = [
            r"(generate|create|make)\s+(pdf|document|report)\s+(about|on|regarding|for|with|answering|explaining)\s+(.+)",
            r"(pdf|document|report)\s+(about|on|regarding|for|with|answering|explaining)\s+(.+)",
            r"(answer|explain|analyze)\s+(.+)\s+(in|as)\s+(pdf|document|report)",
            r"(create|make|generate)\s+(pdf|document)\s+(.+)"
        ]
    
    def detect_request(self, message: str) -> Tuple[bool, str, str]:
        """
        Detect if message contains media generation request
        Returns: (is_media_request, media_type, media_subtype)
        """
        message_lower = message.lower().strip()
        
        # Simple PDF triggers (explicit single words or short phrases)
        simple_pdf_triggers = ["pdf", "give me pdf", "give a pdf", "last qa pdf", "create pdf"]
        if message_lower in simple_pdf_triggers:
            return True, "pdf", "last_qa"
        
        # Check for explicit PDF generation keywords
        if any(keyword in message_lower for keyword in self.explicit_pdf_keywords):
            if "code" in message_lower:
                return True, "pdf", "code"
            else:
                return True, "pdf", "report"
        
        # Check for file-based PDF patterns
        is_file_pdf, question = self.detect_file_pdf_request(message)
        if is_file_pdf:
            return True, "pdf", "file_question"
        
        # Check for image keywords
        if any(keyword in message_lower for keyword in self.image_keywords):
            if any(word in message_lower for word in ["diagram", "flowchart", "process", "chart"]):
                return True, "image", "diagram"
            else:
                return True, "image", "general"
        
        return False, None, None
    
    def detect_file_pdf_request(self, message: str) -> Tuple[bool, str]:
        """
        Enhanced detection for PDF generation requests about uploaded files
        Returns: (is_file_pdf_request, extracted_question)
        """
        message_lower = message.lower().strip()
        
        # Check against patterns
        for pattern in self.file_pdf_patterns:
            match = re.search(pattern, message_lower)
            if match:
                # Extract the question/topic part
                groups = match.groups()
                if len(groups) >= 2:
                    # The last group usually contains the question/topic
                    question = groups[-1].strip()
                    if question and len(question) > 3:  # Meaningful question
                        return True, question
        
        # Alternative approach: look for PDF keywords with question words
        pdf_indicators = ["pdf", "document", "report"]
        question_words = ["what", "how", "why", "when", "where", "who", "which", "explain", "analyze", "summarize", "tell me"]
        
        has_pdf_indicator = any(indicator in message_lower for indicator in pdf_indicators)
        has_question_word = any(word in message_lower for word in question_words)
        
        if has_pdf_indicator and has_question_word:
            # Try to extract the question part
            for word in question_words:
                if word in message_lower:
                    parts = message_lower.split(word, 1)
                    if len(parts) > 1:
                        question_part = (word + " " + parts[1]).strip()
                        # Clean up common PDF keywords from the question
                        for indicator in pdf_indicators:
                            question_part = question_part.replace(indicator, "").strip()
                        question_part = re.sub(r'\b(generate|create|make|about|on|regarding|for|with|answering|explaining|as|in)\b', '', question_part).strip()
                        if question_part and len(question_part) > 5:
                            return True, question_part
        
        return False, ""
    
    def is_pdf_request(self, message: str) -> bool:
        """Check if message is specifically requesting PDF generation"""
        is_media, media_type, _ = self.detect_request(message)
        return is_media and media_type == "pdf"
    
    def is_file_pdf_request(self, message: str) -> bool:
        """Check if message is requesting PDF generation about uploaded file"""
        is_file_pdf, _ = self.detect_file_pdf_request(message)
        return is_file_pdf
    
    def is_regular_conversation(self, message: str) -> bool:
        """Check if message is regular conversation (NOT a PDF request)"""
        return not self.is_pdf_request(message)


class ChatTextFormatter:
    """Formats text specifically for chat display"""
    
    @staticmethod
    def format_pdf_success(filename: str, download_url: str, file_size: int = None) -> str:
        """Format PDF generation success message"""
        size_info = f" ({file_size} bytes)" if file_size else ""
        return (
            f"📄 **PDF Generated Successfully!**\n"
            f"📋 **File:** {filename}{size_info}\n"
            f"⬇️ **Download:** <a href='{download_url}'>{download_url}</a>"
        )
    
    @staticmethod
    def format_pdf_error(error_message: str) -> str:
        """Format PDF generation error message"""
        return f"❌ **PDF Generation Failed:** {error_message}"
    
    @staticmethod
    def format_file_pdf_success(filename: str, download_url: str, question: str, file_size: int = None) -> str:
        """Format PDF generation success message for file-based questions"""
        size_info = f" ({file_size} bytes)" if file_size else ""
        return (
            f"📄 **PDF Generated Successfully!**\n"
            f"❓ **Question:** {question[:100]}{'...' if len(question) > 100 else ''}\n"
            f"📋 **File:** {filename}{size_info}\n"
            f"⬇️ **Download:** <a href='{download_url}'>{download_url}</a>\n\n"
            f"*The PDF contains a detailed answer to your question based on the uploaded file content.*"
        )
    
    @staticmethod
    def format_document_preview(title: str, content: str, show_full: bool = False) -> str:
        """Format document content for chat preview"""
        if not content or not content.strip():
            return f"📄 **{title}** - No readable content found."
        
        if not show_full and len(content) > 1000:
            preview = content[:1000] + "..."
            return (
                f"📄 **{title}**\n\n"
                f"{preview}\n\n"
                f"*Preview showing first 1000 characters. Full content available for processing.*"
            )
        
        return f"📄 **{title}**\n\n{content}"
    
    @staticmethod
    def format_file_uploaded_message(file_type: str, has_instruction: bool = False) -> str:
        """Format message when file is uploaded and processed"""
        if has_instruction:
            return f"📤 **{file_type.upper()} file uploaded and processed with your instructions.**\n\n*You can now ask questions about this file or request a PDF with specific questions.*"
        else:
            return f"📤 **{file_type.upper()} file uploaded and processed.**\n\n*You can now ask questions about this file or request a PDF with specific questions.*"