import os
import streamlit as st
from PIL import Image
import cv2
import numpy as np
import json
import pandas as pd
import tempfile
import base64
from io import BytesIO
import re
from dotenv import load_dotenv
from groq import Groq
import easyocr
from pdf2image.exceptions import PDFPageCountError
import requests
import io
import fitz  # PyMuPDF
import docx2txt

# Load environment variables
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 50)) * 1024 * 1024

# Initialize EasyOCR reader
@st.cache_resource
def load_easyocr():
    return easyocr.Reader(['en'])


def enhance_image(image_array):
    """Apply image enhancement techniques."""
    try:
        # Convert to grayscale if image is colored
        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        else:
            gray = image_array

        # Apply adaptive thresholding
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # Denoise
        denoised = cv2.fastNlMeansDenoising(thresh)

        # Increase contrast
        contrast = cv2.convertScaleAbs(denoised, alpha=1.5, beta=0)

        return contrast

    except Exception as e:
        st.warning(f"Image enhancement warning: {str(e)}")
        return image_array


def process_with_easyocr(image_array):
    """Process image with EasyOCR."""
    try:
        # Load EasyOCR
        reader = load_easyocr()

        # Enhance image
        enhanced_image = enhance_image(image_array)

        # Perform OCR
        results = reader.readtext(enhanced_image)

        # Extract text
        text = ' '.join([result[1] for result in results])

        return text.strip()
    except Exception as e:
        st.error(f"EasyOCR Error: {str(e)}")
        return ""


def process_with_online_ocr(image_array):
    """Process image with OCR.space API (as a backup method)."""
    try:
        # Convert image array to bytes
        is_success, buffer = cv2.imencode(".jpg", image_array)
        if not is_success:
            return ""

        # Convert to base64
        img_bytes = base64.b64encode(buffer)

        # OCR.space API endpoint and parameters
        url = "https://api.ocr.space/parse/image"
        payload = {
            'apikey': os.getenv('OCR_SPACE_API_KEY', 'helloworld'),  # Free API key
            'language': 'eng',
            'base64Image': f'data:image/jpg;base64,{img_bytes.decode()}'
        }

        response = requests.post(url, data=payload)
        result = response.json()

        if result.get('ParsedResults'):
            return result['ParsedResults'][0]['ParsedText']
        return ""

    except Exception as e:
        st.warning(f"Online OCR warning: {str(e)}")
        return ""


def extract_text_from_pdf(pdf_bytes):
    """Extract text from PDF using PyMuPDF."""
    try:
        # Open PDF from bytes
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""

        # Extract text from each page
        for page_num in range(pdf_document.page_count):
            page = pdf_document[page_num]
            text += page.get_text()

        pdf_document.close()
        return text

    except Exception as e:
        st.warning(f"PDF text extraction warning: {str(e)}")
        return ""


def process_with_groq(text):
    """Process text with Groq API for information extraction."""
    try:
        prompt = """
        You will carefully analyze the invoice text and extract all relevant details. 
        The output should be in pure JSON and table format within a Python list. 
        Here is the extracted text from the invoice:

        {text}

        Extract the following fields:
        - Invoice Number
        - Date
        - Due Date
        - Total Amount
        - Vendor Name
        - Line Items (array with):
            * Description
            * Quantity
            * Unit Price
            * Total Price
        - Subtotal
        - Tax Amount
        - Payment Terms
        - Billing Address
        - Currency
        - Additional Notes (if any)

        Return only the JSON object with these fields. Format all numerical values appropriately.
        """

        completion = client.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=[
                {"role": "system",
                 "content": "You are an expert invoice analyzer. Extract information in clean JSON format."},
                {"role": "user", "content": prompt.format(text=text)}
            ],
            temperature=0.1,
            max_tokens=2000
        )

        response_text = completion.choices[0].message.content
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return {"error": "No valid JSON found in response"}

    except Exception as e:
        return {"error": f"Groq API Error: {str(e)}"}


def process_file(file):
    """Process uploaded file and extract invoice data."""
    try:
        if file.size > MAX_FILE_SIZE:
            return {"error": f"File size exceeds {MAX_FILE_SIZE / 1024 / 1024}MB limit"}

        # Read file content
        file_content = file.read()
        text = ""

        if file.type.startswith('image/'):
            # Convert bytes to numpy array
            nparr = np.frombuffer(file_content, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            # Try EasyOCR first
            text = process_with_easyocr(image)

            # If EasyOCR fails or returns empty text, try online OCR
            if not text.strip():
                text = process_with_online_ocr(image)

        elif file.type == 'application/pdf':
            # Try PyMuPDF first for text extraction
            text = extract_text_from_pdf(file_content)

            # If text extraction fails, try OCR methods
            if not text.strip():
                try:
                    # Convert first page to image
                    pdf = fitz.open(stream=file_content, filetype="pdf")
                    page = pdf[0]
                    pix = page.get_pixmap()
                    img_data = pix.tobytes()

                    # Convert to numpy array
                    nparr = np.frombuffer(img_data, np.uint8)
                    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

                    # Try OCR methods
                    text = process_with_easyocr(image)
                    if not text.strip():
                        text = process_with_online_ocr(image)

                except Exception as e:
                    st.warning(f"PDF processing warning: {str(e)}")

        elif file.type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
            # Process DOCX
            text = docx2txt.process(io.BytesIO(file_content))

        else:
            return {"error": "Unsupported file type"}

        if not text.strip():
            return {"error": "No text could be extracted from the file"}

        # Process with Groq
        return process_with_groq(text)

    except Exception as e:
        return {"error": f"Processing failed: {str(e)}"}


def create_editable_table(df, key_prefix):
    """Create an editable table view."""
    edited_df = df.copy()

    for idx, col in enumerate(df.columns):
        edited_df[col] = [st.text_input(f"Edit {col}",
                                        value=str(val),
                                        key=f"{key_prefix}_{idx}_{i}")
                          for i, val in enumerate(df[col])]

    return edited_df


def main():
    st.set_page_config(page_title="Invoice Data Extractor", layout="wide")

    # Custom CSS for UI
    st.markdown("""
    <style>
    .stTitle { 
        text-align: center; 
        color: #2E86C1; 
        font-weight: bold; 
    }
    .stButton>button { 
        background-color: #2E86C1; 
        color: white; 
    }
    .table-container { 
        margin: 20px 0; 
    }
    div[role="radiogroup"] > label > div {
        display: flex;
        flex-direction: row;
    }
    div[role="radiogroup"] > label > div > div {
        margin-right: 10px;
    }
    div[role="radiogroup"] {
        display: flex;
        flex-direction: row;
    }
    div[role="radiogroup"] > label {
        margin-right: 20px;
    }
    input[type="radio"]:div {
        background-color: white;
        border-color: lightblue;
    }
    </style>
    """, unsafe_allow_html=True)

    # Layout for logo and title
    col1, col2 = st.columns([1, 5])  # Adjust column widths as needed

    with col1:
        # Add logo
        logo = Image.open("logo.png")  # Replace with your logo path
        st.image(logo, width=100)  # Adjust the width as needed

    with col2:
        st.markdown(
            """
            <h1 class="stTitle">
                 Invoice Data Extractor
            </h1>
            """,
            unsafe_allow_html=True
        )

    # Initialize session state
    if 'results' not in st.session_state:
        st.session_state.results = []

  

    # File uploader
    uploaded_files = st.file_uploader(
        "Upload Invoices (Image/PDF/DOCX)",
        type=['png', 'jpg', 'jpeg', 'pdf', 'docx'],
        accept_multiple_files=True
    )

    if uploaded_files:
        for file in uploaded_files:
            with st.spinner(f"Processing {file.name}..."):
                st.write(f"Processing: {file.name}")

                # Process file
                result = process_file(file)

                if "error" in result:
                    st.error(f"Error processing {file.name}: {result['error']}")
                    continue

                st.session_state.results.append({
                    'filename': file.name,
                    'data': result
                })

    # Display results
    for idx, result in enumerate(st.session_state.results):
        st.subheader(f"Results for {result['filename']}")

        # Convert to DataFrames
        main_info = {k: v for k, v in result['data'].items() if k != 'Line Items'}
        main_df = pd.DataFrame([main_info])

        line_items = result['data'].get('Line Items', [])
        items_df = pd.DataFrame(line_items) if line_items else None

        # Create tabs
        tab1, tab2 = st.tabs(["View/Edit Data", "Raw JSON"])

        with tab1:
            st.write("Invoice Information:")
            edited_main_df = create_editable_table(main_df, f"main_{idx}")

            if items_df is not None:
                st.write("Line Items:")
                edited_items_df = create_editable_table(items_df, f"items_{idx}")

            # Save changes button
            if st.button(f"Save Changes for {result['filename']}", key=f"save_{idx}"):
                updated_data = edited_main_df.iloc[0].to_dict()
                if items_df is not None:
                    updated_data['Line Items'] = edited_items_df.to_dict('records')
                st.session_state.results[idx]['data'] = updated_data
                st.success("Changes saved successfully!")

        with tab2:
            st.json(result['data'])

        # Download options
        col1, col2 = st.columns(2)
        with col1:
            json_str = json.dumps(result['data'], indent=2)
            st.download_button(
                "Download JSON",
                json_str,
                f"{result['filename']}_data.json",
                "application/json",
                key=f"json_{idx}"
            )

        with col2:
            csv = pd.DataFrame([result['data']]).to_csv(index=False)
            st.download_button(
                "Download CSV",
                csv,
                f"{result['filename']}_data.csv",
                "text/csv",
                key=f"csv_{idx}"
            )

  # Clear button
    if st.button("Clear All Data"):
        st.session_state.results = []
        st.experimental_rerun()


if __name__ == "__main__":
    main()
