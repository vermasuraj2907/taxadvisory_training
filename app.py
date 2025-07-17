import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import PyPDF2
import pytesseract
from pdf2image import convert_from_path
import re
import google.generativeai as genai
import tax_calculator
import psycopg2
from psycopg2.extras import RealDictCursor
import json

load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
AI_LOG_FILE = 'ai_conversation_log.json'

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = os.getenv('SECRET_KEY', 'dev')

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(pdf_path):
    # Try text extraction with PyPDF2
    text = ""
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text += page.extract_text() or ""
    except Exception:
        pass
    # If text is insufficient, use OCR
    if len(text.strip()) < 100:
        images = convert_from_path(pdf_path)
        for image in images:
            text += pytesseract.image_to_string(image)
    print("[DEBUG] Extracted raw_text from PDF:\n", text)
    return text

def extract_structured_data(raw_text):
    # Try Gemini LLM extraction first
    if GEMINI_API_KEY:
        prompt = (
            "Extract the following fields from this payslip text and return as JSON: "
            "name, gross_salary, basic_salary, hra_received, rent_paid, deduction_80c, deduction_80d, "
            "standard_deduction, professional_tax, tds.\nText: " + raw_text
        )
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            import json
            import re as _re
            match = _re.search(r'\{[\s\S]*\}', response.text)
            if match:
                data = json.loads(match.group(0))
                for key in ['name','gross_salary','basic_salary','hra_received','rent_paid','deduction_80c','deduction_80d','standard_deduction','professional_tax','tds']:
                    val = data.get(key, '')
                    if key == 'name':
                        data['username'] = val.strip() if isinstance(val, str) else ''
                        continue
                    if not isinstance(val, (str, int, float)):
                        val = ''
                    val = str(val).replace(',', '').strip()
                    data[key] = val if val and val.replace('.', '', 1).isdigit() else '0'
                data['tax_regime'] = 'new'
                # Salary slip vs Form 16 logic
                doc_type = 'unknown'
                annualize_fields = ['gross_salary','basic_salary','hra_received','rent_paid','deduction_80c','deduction_80d','standard_deduction','professional_tax','tds']
                if 'salary slip' in raw_text.lower():
                    doc_type = 'salary slip'
                    for field in annualize_fields:
                        try:
                            val = float(data[field])
                            data[field] = str(int(val * 12))
                            print(f'[DEBUG] Detected Salary Slip: {field} multiplied by 12')
                        except Exception as e:
                            print(f'[DEBUG] Salary Slip detected but {field} not numeric:', e)
                elif 'form 16' in raw_text.lower():
                    doc_type = 'form 16'
                    print('[DEBUG] Detected Form 16: values used as is')
                else:
                    print('[DEBUG] Document type could not be determined')
                data['doc_type'] = doc_type
                print("[DEBUG] Gemini extracted data:", data)
                return data
        except Exception as e:
            print(f"Gemini extraction failed: {e}")
    # Fallback to regex-based extraction
    def extract(pattern):
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            val = match.group(1).replace(',', '').strip()
            return val if val and val.replace('.', '', 1).isdigit() else '0'
        return '0'
    def extract_name(pattern):
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ''
    data = {
        'username': extract_name(r'Name[:\s]+([A-Za-z .]+)'),
        'gross_salary': extract(r'Gross\s*Salary[:\s]+([\d,]+\.?\d*)'),
        'basic_salary': extract(r'Basic\s*Salary[:\s]+([\d,]+\.?\d*)'),
        'hra_received': extract(r'HRA(?:\s*Received)?[:\s]+([\d,]+\.?\d*)'),
        'rent_paid': extract(r'Rent\s*Paid[:\s]+([\d,]+\.?\d*)'),
        'deduction_80c': extract(r'80C(?:\s*Investments)?[:\s]+([\d,]+\.?\d*)'),
        'deduction_80d': extract(r'80D(?:\s*Medical\s*Insurance)?[:\s]+([\d,]+\.?\d*)'),
        'standard_deduction': extract(r'Standard\s*Deduction[:\s]+([\d,]+\.?\d*)'),
        'professional_tax': extract(r'Professional\s*Tax[:\s]+([\d,]+\.?\d*)'),
        'tds': extract(r'TDS[:\s]+([\d,]+\.?\d*)'),
        'tax_regime': 'new',
    }
    # Salary slip vs Form 16 logic for regex fallback
    doc_type = 'unknown'
    annualize_fields = ['gross_salary','basic_salary','hra_received','rent_paid','deduction_80c','deduction_80d','standard_deduction','professional_tax','tds']
    if 'salary slip' in raw_text.lower():
        doc_type = 'salary slip'
        for field in annualize_fields:
            try:
                val = float(data[field])
                data[field] = str(int(val * 12))
                print(f'[DEBUG] Detected Salary Slip: {field} multiplied by 12')
            except Exception as e:
                print(f'[DEBUG] Salary Slip detected but {field} not numeric:', e)
    elif 'form 16' in raw_text.lower():
        doc_type = 'form 16'
        print('[DEBUG] Detected Form 16: values used as is')
    else:
        print('[DEBUG] Document type could not be determined')
    data['doc_type'] = doc_type
    print("[DEBUG] Regex extracted data:", data)
    return data

# Helper to append to conversation log
def log_ai_conversation(session_id, entry):
    log_entry = {'session_id': session_id, **entry}
    try:
        if os.path.exists(AI_LOG_FILE):
            with open(AI_LOG_FILE, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        else:
            logs = []
        logs.append(log_entry)
        with open(AI_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        print(f'[DEBUG] Failed to log AI conversation: {e}')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['pdf_file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            session_id = str(uuid.uuid4())
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], session_id + '_' + filename)
            file.save(save_path)
            # Extract text and structured data
            raw_text = extract_text_from_pdf(save_path)
            data = extract_structured_data(raw_text)
            # Delete the file after extraction
            os.remove(save_path)
            return render_template('form.html', data=data)
        else:
            flash('Invalid file type. Please upload a PDF.')
            return redirect(request.url)
    return '''
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Upload PDF</title>
        <link href="https://fonts.googleapis.com/css2?family=Aptos+Display:wght@400;700&display=swap" rel="stylesheet">
        <style>
            body { font-family: 'Aptos Display', Arial, sans-serif; background: #f8fbff; color: #1a237e; margin: 0; padding: 0; }
            .center-container { min-height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; }
            .upload-box { background: #fff; border-radius: 16px; box-shadow: 0 2px 12px rgba(21,101,192,0.08); padding: 40px 32px; }
            h2 { color: #1565c0; margin-bottom: 1.2em; text-align: center; }
            .upload-btn {
                background: linear-gradient(90deg, #1976d2 0%, #64b5f6 100%);
                color: #fff;
                font-size: 1.1rem;
                font-weight: 600;
                padding: 0.8em 2.2em;
                border: none;
                border-radius: 30px;
                cursor: pointer;
                box-shadow: 0 2px 8px rgba(25, 118, 210, 0.08);
                transition: background 0.2s, box-shadow 0.2s;
                margin-top: 1.2em;
            }
            .upload-btn:hover {
                background: linear-gradient(90deg, #1565c0 0%, #42a5f5 100%);
                box-shadow: 0 4px 16px rgba(25, 118, 210, 0.15);
            }
            input[type="file"] {
                margin-top: 1em;
                font-size: 1rem;
            }
        </style>
    </head>
    <body>
        <div class="center-container">
            <div class="upload-box">
                <h2>Upload Pay Slip or Form 16 (PDF)</h2>
                <form method="post" enctype="multipart/form-data" style="text-align:center;">
                    <input type="file" name="pdf_file" accept="application/pdf" required><br>
                    <button class="upload-btn" type="submit">Upload</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    '''

@app.route('/review', methods=['POST'])
def review():
    # Get form data
    data = {k: request.form.get(k, '') for k in [
        'gross_salary','basic_salary','hra_received','rent_paid','deduction_80c','deduction_80d','standard_deduction','professional_tax','tds','tax_regime']}
    username = request.form.get('username', '')
    print("[DEBUG] Form data received in /review:", data)
    session_id = str(uuid.uuid4())
    # Calculate tax for both regimes
    tax_old = tax_calculator.calculate_tax_old_regime(data)
    tax_new = tax_calculator.calculate_tax_new_regime(data)
    # Save to Supabase (PostgreSQL)
    DB_URL = os.getenv('DB_URL')
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Insert into UserFinancials
        cur.execute('''
            INSERT INTO UserFinancials (session_id, gross_salary, basic_salary, hra_received, rent_paid, deduction_80c, deduction_80d, standard_deduction, professional_tax, tds)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ''', [session_id, data['gross_salary'], data['basic_salary'], data['hra_received'], data['rent_paid'], data['deduction_80c'], data['deduction_80d'], data['standard_deduction'], data['professional_tax'], data['tds']])
        # Insert into TaxComparison
        best_regime = 'old' if tax_old < tax_new else 'new'
        cur.execute('''
            INSERT INTO TaxComparison (session_id, tax_old_regime, tax_new_regime, best_regime, selected_regime)
            VALUES (%s,%s,%s,%s,%s)
        ''', [session_id, tax_old, tax_new, best_regime, data['tax_regime']])
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")
    # Render results.html
    return render_template('results.html', tax_old_regime=tax_old, tax_new_regime=tax_new, selected_regime=data['tax_regime'], session_id=session_id, username=username)

@app.route('/advisor/<session_id>', methods=['GET', 'POST'])
def advisor(session_id):
    # Load user data from DB for context
    DB_URL = os.getenv('DB_URL')
    user_data = {}
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM UserFinancials WHERE session_id = %s', (session_id,))
        user_data = cur.fetchone() or {}
        cur.close()
        conn.close()
    except Exception as e:
        print(f'[DEBUG] Could not load user data for advisor: {e}')
    username = request.args.get('username', '')
    # Step 1: Ask follow-up question
    if request.method == 'GET':
        # Use Gemini to generate a follow-up question
        prompt = (
            'Given the following user financial data, ask a smart, contextual follow-up question to help optimize their tax savings.\n'
            f'User Data: {user_data}\n'
            'Ask only one question.'
        )
        question = 'What is your current investment in tax-saving instruments?' # fallback
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            question = response.text.strip().split('\n')[0]
        except Exception as e:
            print(f'[DEBUG] Gemini follow-up question failed: {e}')
        log_ai_conversation(session_id, {'role': 'gemini', 'type': 'question', 'content': question})
        gross_salary = user_data.get('gross_salary', '') if user_data else ''
        return render_template('ask.html', question=question, suggestions=None, gross_salary=gross_salary, username=username)
    # Step 2: User answers, Gemini gives suggestions
    if request.method == 'POST':
        user_answer = request.form.get('user_answer', '')
        log_ai_conversation(session_id, {'role': 'user', 'type': 'answer', 'content': user_answer})
        # Use Gemini to generate personalized suggestions
        prompt = (
            'Given the following user financial data and their answer to your previous question, provide personalized, actionable investment and tax-saving suggestions in a clear, readable format.\n'
            f'User Data: {user_data}\n'
            f'User Answer: {user_answer}\n'
            'Respond in HTML bullet points.'
        )
        suggestions = 'Could not generate suggestions.'
        try:
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            suggestions = response.text.strip()
        except Exception as e:
            print(f'[DEBUG] Gemini suggestions failed: {e}')
        log_ai_conversation(session_id, {'role': 'gemini', 'type': 'suggestions', 'content': suggestions})
        gross_salary = user_data.get('gross_salary', '') if user_data else ''
        return render_template('ask.html', question=None, suggestions=suggestions, gross_salary=gross_salary, username=username)

if __name__ == '__main__':
    app.run(debug=True) 