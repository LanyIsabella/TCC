import os
from pathlib import Path

from glmocr import GlmOcr

DEFAULT_GLMOCR_CONFIG = Path(
    os.getenv("GLMOCR_CONFIG", "config/glmocr.yaml")
)


def extract_pdf(
    docling_converter: object,
    glmocr_parser: GlmOcr,
    pdf_path: Path,
    docling_output_path: Path,
    glmocr_output_path: Path,
) -> None:
    docling_result = docling_converter.convert(pdf_path)
    docling_output_path.parent.mkdir(parents=True, exist_ok=True)
    docling_output_path.write_text(
        docling_result.document.export_to_markdown(), encoding="utf-8"
    )

    glmocr_result = glmocr_parser.parse(
        pdf_path, save_layout_visualization=False
    )
    glmocr_output_path.parent.mkdir(parents=True, exist_ok=True)
    glmocr_output_path.write_text(glmocr_result.markdown_result, encoding="utf-8")


def extract_pdfs(
    input_dir: Path,
    output_dir: Path,
    config_path: Path = DEFAULT_GLMOCR_CONFIG,
) -> None:
    pdf_paths = sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )

    if not pdf_paths:
        raise FileNotFoundError(f"Nenhum arquivo PDF encontrado em: {input_dir}")

    from docling.document_converter import DocumentConverter

    docling_converter = DocumentConverter()
    glmocr_parser = GlmOcr(config_path=str(config_path))

    for pdf_path in pdf_paths:
        relative_path = pdf_path.relative_to(input_dir).with_suffix(".md")
        docling_output_path = output_dir / "docling" / relative_path
        glmocr_output_path = output_dir / "glmocr" / relative_path
        print(f"Extraindo com Docling: {pdf_path} -> {docling_output_path}")
        print(f"Extraindo com GLM-OCR: {pdf_path} -> {glmocr_output_path}")
        extract_pdf(
            docling_converter,
            glmocr_parser,
            pdf_path,
            docling_output_path,
            glmocr_output_path,
        )


if __name__ == "__main__":
    extract_pdfs(
        input_dir=Path("data/raw"),
        output_dir=Path("data/processed"),
    )
