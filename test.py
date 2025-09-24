import PyPDF2

with open('in/Notification of Ext 9-18-2025.pdf', 'rb') as f:
    reader = PyPDF2.PdfReader(f)
    page1_text = reader.pages[0].extract_text()
    print("PAGE 1 TEXT:")
    print(repr(page1_text[:1000]))
    print("\n\nSEARCHING FOR:")
    print("'Notification' found:", 'Notification' in page1_text)
    print("'106874' found:", '106874' in page1_text)
    