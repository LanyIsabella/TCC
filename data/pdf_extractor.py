from pathlib import Path

from docling.document_converter import DocumentConverter


def extract_pdf(
    converter: DocumentConverter,
    pdf_path: Path,
    output_path: Path,
) -> None:
    result = converter.convert(pdf_path)

    markdown = result.document.export_to_markdown()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")


def extract_pdfs(input_dir: Path, output_dir: Path) -> None:
    pdf_paths = sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )

    if not pdf_paths:
        raise FileNotFoundError(f"Nenhum arquivo PDF encontrado em: {input_dir}")

    converter = DocumentConverter()

    for pdf_path in pdf_paths:
        relative_path = pdf_path.relative_to(input_dir).with_suffix(".md")
        output_path = output_dir / relative_path
        print(f"Extraindo {pdf_path} -> {output_path}")
        extract_pdf(converter, pdf_path, output_path)


if __name__ == "__main__":
    extract_pdfs(
        input_dir=Path("data/raw"),
        output_dir=Path("data/processed"),
    )
