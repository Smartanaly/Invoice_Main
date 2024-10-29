import aspose.words as aw
from io import BytesIO
import streamlit as st
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from PIL import Image, ImageDraw, ImageFont
import os, fitz
import json, time
import pandas as pd
from docx import Document

os.environ["GOOGLE_API_KEY"] = 'AIzaSyDBYwT1atq4es0NST5mk10BASONgj1FFqQ'

# Initialize the ChatGoogleGenerativeAI model
llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro-latest")

st.markdown("""<style>
        .stButton > button {
            display: block;
            margin: 0 auto;}</style>
        """, unsafe_allow_html=True)

# Custom CSS to display radio options
st.markdown("""
    <style>
    div[role="radiogroup"] > label > div {
        display: flex;
        flex-direction: row;
    }
    div[role="radiogroup"] > label > div > div {
        margin-right: 10px;
    }
    </style>
    <style>
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


def process_invoice(image_path):
    message = HumanMessage(
        content=[
            {
                "type": "text",
                "text": """You will carefully analyze the invoice only and get the output in pure json within a python list format with relevant details
                with invoice id as default ino [{}], your response shall not contain ' ```python ' and ' ``` '
                        """,
            },
            {"type": "image_url", "image_url": image_path}
        ]
    )
    response = llm.invoke([message])
    return response.content


def convert_pdf_to_images_with_pymupdf(pdf_path, output_folder, zoom_x=2.0, zoom_y=2.0):
    """Convert PDF pages to images with high resolution."""
    doc = fitz.open(pdf_path)
    image_paths = []
    for page_number in range(len(doc)):
        page = doc.load_page(page_number)
        mat = fitz.Matrix(zoom_x, zoom_y)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        unique_name = f'output_image_{int(time.time())}_{page_number + 1}.png'
        image_path = os.path.join(output_folder, unique_name)
        pix.save(image_path)
        image_paths.append(image_path)
        print(f'Generated image: {image_path}')
    return image_paths


def convert_docx_to_images(docx_file, invoice_dir):
    """Convert DOCX file pages to high-quality images."""
    doc = aw.Document(docx_file)
    images = []

    for i in range(doc.page_count):
        options = aw.saving.ImageSaveOptions(aw.SaveFormat.JPEG)
        options.page_set = aw.saving.PageSet(i)
        options.horizontal_resolution = 300
        options.vertical_resolution = 300

        # Save the page image to a BytesIO buffer
        buffer = BytesIO()
        doc.save(buffer, options)
        buffer.seek(0)

        # Open the image from the buffer
        image = Image.open(buffer)
        images.append(image)

    # Get the width and height of the combined image
    total_width = max(image.width for image in images)
    total_height = sum(image.height for image in images)

    # Create a new blank image with the combined size
    combined_image = Image.new('RGB', (total_width, total_height))

    # Paste each page image into the combined image
    y_offset = 0
    for image in images:
        combined_image.paste(image, (0, y_offset))
        y_offset += image.height

    # Save the combined image with the same name as the DOCX file
    docx_filename = os.path.splitext(os.path.basename(docx_file))[0]
    combined_image_file = os.path.join(invoice_dir, f"{docx_filename}.jpg")
    combined_image.save(combined_image_file, quality=100)

    return combined_image_file


def txt_to_image(txt_file, invoice_dir, custom_font_path=None):
    """Convert text file to a high-resolution image."""
    with open(txt_file, 'r') as f:
        text = f.read()

    # Create a new image with higher resolution
    image = Image.new('RGB', (1600, 1200), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)

    # Use the custom font if provided, else fallback to default
    if custom_font_path:
        try:
            font = ImageFont.truetype(custom_font_path, 24)
        except IOError:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()

    # Draw the text on the image
    draw.text((10, 10), text, font=font, fill=(0, 0, 0))

    # Save the image with high quality
    txt_image_path = os.path.join(invoice_dir, f"{os.path.splitext(os.path.basename(txt_file))[0]}.png")
    image.save(txt_image_path, quality=100)

    return txt_image_path


def clear_invoice_dir(invoice_dir):
    """Clear all files in the specified directory."""
    for filename in os.listdir(invoice_dir):
        file_path = os.path.join(invoice_dir, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)  # Remove file
            elif os.path.isdir(file_path):
                os.rmdir(file_path)  # Remove directory if it's empty
        except Exception as e:
            print(f'Failed to delete {file_path}. Reason: {e}')


def main():
    logo_path = "logo.png"  # Replace with your logo path
    logo = Image.open(logo_path)

    # Layout for logo and title
    col1, col2 = st.columns([1, 5])  # Adjust column widths as needed

    with col1:
        st.image(logo, width=100)  # Adjust the width as needed
    with col2:
        st.markdown(
            """
            <h1 style="font-family:Georgia, serif; color:#4CAF50; font-size:36px;">
                Invoice Data Analyzer
            </h1>
            """,
            unsafe_allow_html=True
        )
    option = st.radio(
        "Select an option:",
        ("Upload Invoice Images, PDFs, TXT Files", "Select Existing Images"))

    use_custom_font = st.checkbox('Use custom font for txt to image')

    custom_font_path = None

    if use_custom_font:
        font_dir = '/tmp/fonts/'
        if not os.path.exists(font_dir):
            os.makedirs(font_dir)

        existing_fonts = [f for f in os.listdir(font_dir) if f.endswith('.ttf')]

        if existing_fonts:
            font_choice = st.radio("Choose a font", existing_fonts)
            custom_font_path = os.path.join(font_dir, font_choice)
            st.write(f"Now using font: {font_choice}")

        uploaded_font = st.file_uploader("Upload .ttf for custom font", type=["ttf"])
        if uploaded_font:
            custom_font_path = os.path.join(font_dir, uploaded_font.name)
            with open(custom_font_path, "wb") as f:
                f.write(uploaded_font.getbuffer())
            st.write(f"Now using font: {uploaded_font.name}")

    if 'json_outputs' not in st.session_state:
        st.session_state.json_outputs = {}

    invoice_dir = '/tmp/invoices/'

    # Create the directory if it doesn't exist
    if not os.path.exists(invoice_dir):
        os.makedirs(invoice_dir)

    # Button to clear the invoice directory
    if st.button("Clear Invoice Directory"):
        clear_invoice_dir(invoice_dir)
        st.success("Invoice directory cleared!")

    if option == "Upload Invoice Images, PDFs, TXT Files":
        uploaded_files = st.file_uploader("Choose images, PDFs, TXT files...",
                                          type=["jpg", "jpeg", "png", "pdf", "txt", "docx"], accept_multiple_files=True)
        if uploaded_files:
            for uploaded_file in uploaded_files:
                if uploaded_file.name.endswith('.pdf'):
                    pdf_path = os.path.join(invoice_dir, uploaded_file.name)
                    with open(pdf_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    image_paths = convert_pdf_to_images_with_pymupdf(pdf_path, invoice_dir)
                    for image_path in image_paths:
                        image = Image.open(image_path)
                        st.image(image, caption=os.path.basename(image_path), use_column_width=True)
                elif uploaded_file.name.endswith('.txt'):
                    txt_path = os.path.join(invoice_dir, uploaded_file.name)
                    with open(txt_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    image_path = txt_to_image(txt_path, invoice_dir, custom_font_path)
                    st.image(image_path, caption=os.path.basename(image_path), use_column_width=True)
                elif uploaded_file.name.endswith('.docx'):
                    docx_path = os.path.join(invoice_dir, uploaded_file.name)
                    with open(docx_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    image_path = convert_docx_to_images(docx_path, invoice_dir)
                    st.image(image_path, caption=os.path.basename(image_path), use_column_width=True)
                else:
                    image = Image.open(uploaded_file)
                    st.image(image, caption=uploaded_file.name, use_column_width=True)
                    with open(os.path.join(invoice_dir, uploaded_file.name), "wb") as f:
                        f.write(uploaded_file.getbuffer())

            if st.button("Process All Uploaded Files"):
                for uploaded_file in uploaded_files:
                    if uploaded_file.name.endswith('.pdf'):
                        pdf_path = os.path.join(invoice_dir, uploaded_file.name)
                        image_paths = convert_pdf_to_images_with_pymupdf(pdf_path, invoice_dir)
                        for image_path in image_paths:
                            output = process_invoice(image_path)
                            json_output = json.loads(output)
                            st.session_state.json_outputs[os.path.basename(image_path)] = json_output
                    elif uploaded_file.name.endswith('.txt'):
                        txt_path = os.path.join(invoice_dir, uploaded_file.name)
                        image_path = txt_to_image(txt_path, invoice_dir, custom_font_path)
                        output = process_invoice(image_path)
                        json_output = json.loads(output)
                        st.session_state.json_outputs[os.path.basename(image_path)] = json_output
                    elif uploaded_file.name.endswith('.docx'):
                        docx_path = os.path.join(invoice_dir, uploaded_file.name)
                        image_path = convert_docx_to_images(docx_path, invoice_dir)
                        output = process_invoice(image_path)
                        json_output = json.loads(output)
                        st.session_state.json_outputs[os.path.basename(image_path)] = json_output
                    else:
                        image_path = os.path.join(invoice_dir, uploaded_file.name)
                        output = process_invoice(image_path)
                        json_output = json.loads(output)
                        st.session_state.json_outputs[uploaded_file.name] = json_output

    elif option == "Select Existing Images":
        image_files = [f for f in os.listdir(invoice_dir) if f.endswith(('.jpg', '.jpeg', '.png'))]
        selected_images = st.multiselect("Select images", image_files)

        if selected_images:
            for selected_image in selected_images:
                image_path = os.path.join(invoice_dir, selected_image)
                image = Image.open(image_path)
                st.image(image, caption=selected_image, use_column_width=True)

            if st.button("Process All Selected Images"):
                for selected_image in selected_images:
                    image_path = os.path.join(invoice_dir, selected_image)
                    output = process_invoice(image_path)
                    json_output = json.loads(output)
                    st.session_state.json_outputs[selected_image] = json_output

    # Display JSON outputs with expanders and individual download buttons
    if st.session_state.json_outputs:
        for image_name, json_output in st.session_state.json_outputs.items():
            with st.expander(f"JSON Output for {image_name}"):
                st.json(json_output)

                # Convert JSON to tabular format for CSV download
                if "Products/Services" in json_output:
                    products_df = pd.json_normalize(json_output["Products/Services"])
                    other_info = {key: json_output[key] for key in json_output if key != "Products/Services"}
                    other_info_df = pd.DataFrame([other_info])
                    final_df = other_info_df.join(products_df)
                else:
                    final_df = pd.DataFrame([json_output])

                # Convert DataFrame to CSV
                csv_data = final_df.to_csv(index=False)

                st.download_button(
                    label=f"Download CSV for {image_name}",
                    data=csv_data,
                    file_name=f"{image_name}_output.csv",
                    mime="text/csv",
                    key=f"download-{image_name}"  # Ensure unique key for each download button
                )
if __name__ == "__main__":
    main()
