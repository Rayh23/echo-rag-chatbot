from pathlib import Path
import pdfplumber
import docx


def parse_pdf(path: str) -> str:
    text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            content = page.extract_text()
            if content:
                text.append(content)
    return "\n".join(text)


def parse_docx(path: str) -> str:
    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def parse_txt(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def parse_file(path: str) -> str:
    """Dispatch to the correct parser based on file extension."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(path)
    elif ext == ".docx":
        return parse_docx(path)
    elif ext == ".txt":
        return parse_txt(path)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
