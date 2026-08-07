import os
from PIL import Image
from pdf2image import convert_from_path

def convert_png_to_pdf(image_path):
    """
    Converts a PNG or JPG image into a single-page PDF so it can be uploaded
    to the Bot Builder API. Returns the path to the generated PDF.
    """
    pdf_path = os.path.splitext(image_path)[0] + "_temp.pdf"
    img = Image.open(image_path).convert('RGB')
    img.save(pdf_path)
    return pdf_path

def pdf_to_png(pdf_path, output_folder):
    """
    Converts a PDF file into PNG images per page.
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
        
    pages = convert_from_path(pdf_path, dpi=300)
    
    generated_files = []
    for i, page in enumerate(pages):
        image_name = f"page_{i + 1}.png"
        image_path = os.path.join(output_folder, image_name)
        page.save(image_path, "PNG")
        generated_files.append(image_path)
        
    return generated_files