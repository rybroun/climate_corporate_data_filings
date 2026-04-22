"""
PyMuPDF wrapper for PDF parsing.

Extracts text and tables from each page, computes content hash,
and returns a structured ParsedPDF object.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PageContent:
    page_number: int
    text: str
    tables: list[list[list[str]]]  # list of tables, each table is rows of cells


@dataclass
class ParsedPDF:
    pages: list[PageContent]
    content_hash: str  # SHA-256
    page_count: int
    file_size_bytes: int


def parse_pdf(file_bytes: bytes) -> ParsedPDF:
    """Parse a PDF from raw bytes using PyMuPDF.

    Extracts text and tables from each page, computes a SHA-256 content hash,
    and returns a ParsedPDF with all pages, hash, count, and size.

    Parameters
    ----------
    file_bytes:
        Raw bytes of the PDF file.

    Returns
    -------
    ParsedPDF with extracted content.
    """
    import fitz  # PyMuPDF

    content_hash = hashlib.sha256(file_bytes).hexdigest()
    file_size_bytes = len(file_bytes)

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages: list[PageContent] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]

        # Extract text
        text = page.get_text()

        # Extract tables (PyMuPDF 1.23+ built-in table extraction)
        extracted_tables: list[list[list[str]]] = []
        try:
            tabs = page.find_tables()
            for tab in tabs:
                # tab.extract() returns a list of rows, each row is a list of cell strings
                table_data = tab.extract()
                # Normalize None cells to empty strings
                cleaned_rows = [
                    [cell if cell is not None else "" for cell in row]
                    for row in table_data
                ]
                extracted_tables.append(cleaned_rows)
        except Exception:
            # find_tables may not be available in older PyMuPDF versions
            logger.debug(
                "Table extraction failed for page %d, skipping tables",
                page_idx + 1,
            )

        pages.append(
            PageContent(
                page_number=page_idx + 1,
                text=text,
                tables=extracted_tables,
            )
        )

    page_count = len(doc)
    doc.close()

    logger.info(
        "Parsed PDF: %d pages, %d bytes, hash=%s",
        page_count,
        file_size_bytes,
        content_hash[:12],
    )

    return ParsedPDF(
        pages=pages,
        content_hash=content_hash,
        page_count=page_count,
        file_size_bytes=file_size_bytes,
    )
