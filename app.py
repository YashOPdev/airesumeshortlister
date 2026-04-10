import os
import fitz
import json
import re
import time
from flask import Flask, request, render_template, jsonify, send_file
from groq import Groq
from dotenv import load_dotenv
from openpyxl import Workbook

# 🔑 Load env
load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# 🔥 GLOBAL VARIABLES
progress_data = {"total": 0, "processed": 0}
last_results = []

# 📄 Extract text (optimized)
def extract_text(file_path):
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()

    return text[:800]  # 🔥 LIMIT TEXT


# 🧠 Clean JSON
def clean_json(text):
    try:
        json_text = re.search(r'\{.*\}', text, re.DOTALL).group()
        return json.loads(json_text)
    except:
        return None


# 🔍 Keyword scoring
def keyword_score(text, job_desc):
    keywords = job_desc.lower().split()
    return sum(1 for word in keywords if word in text.lower())


# 🤖 AI Analysis
def analyze_resume(resume_text, job_desc):
    prompt = f"""
    Match resume with job.

    Job:
    {job_desc}

    Resume:
    {resume_text}

    Return JSON:
    {{
        "score": number,
        "skills_match": number,
        "experience_match": number,
        "final_verdict": "Select / Reject / Maybe"
    }}
    """

    response = client.chat.completions.create(
        model="groq/compound",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content


@app.route('/')
def index():
    return render_template('index.html')


# 🔥 PROGRESS API
@app.route('/progress')
def progress():
    return jsonify(progress_data)


# 🔥 MAIN UPLOAD ROUTE
@app.route('/upload', methods=['POST'])
def upload_files():
    global progress_data, last_results

    files = request.files.getlist('resumes')
    job_desc = request.form.get('job_desc')[:500]
    top_n = int(request.form.get('top_n'))

    if not job_desc.strip():
        return jsonify({"error": "Enter Job Description"})

    progress_data = {"total": len(files), "processed": 0}

    pre_filtered = []

    # STEP 1: Extract + keyword filter
    for file in files:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)

        text = extract_text(filepath)
        score = keyword_score(text, job_desc)

        pre_filtered.append((file.filename, text, score))

    # STEP 2: Keep top 20
    pre_filtered.sort(key=lambda x: x[2], reverse=True)
    pre_filtered = pre_filtered[:20]

    results = []

    # STEP 3: AI processing
    for name, text, _ in pre_filtered:
        try:
            analysis_text = analyze_resume(text, job_desc)
            analysis = clean_json(analysis_text)

            if not analysis:
                raise Exception("Invalid JSON")

        except Exception as e:
            print("ERROR:", e)

            # Retry once
            time.sleep(2)
            try:
                analysis_text = analyze_resume(text, job_desc)
                analysis = clean_json(analysis_text)
            except:
                analysis = {
                    "score": 0,
                    "skills_match": 0,
                    "experience_match": 0,
                    "final_verdict": "Error"
                }

        results.append({
            "name": name,
            "score": analysis.get("score", 0),
            "skills": analysis.get("skills_match", 0),
            "experience": analysis.get("experience_match", 0),
            "verdict": analysis.get("final_verdict", "Error")
        })

        # 🔥 UPDATE PROGRESS
        progress_data["processed"] += 1

        time.sleep(2)  # 🔥 Prevent rate limit

    # STEP 4: Sort results
    results.sort(key=lambda x: x["score"], reverse=True)

    # 🔥 STORE FOR EXCEL DOWNLOAD
    last_results = results

    return jsonify({
        "top_candidates": results[:top_n],
        "all_candidates": results
    })


# 📊 EXCEL DOWNLOAD
@app.route('/download')
def download_excel():
    global last_results

    wb = Workbook()
    ws = wb.active
    ws.title = "Candidates"

    # Headers
    ws.append(["Name", "Score", "Skills", "Experience", "Verdict"])

    for c in last_results:
        ws.append([
            c["name"],
            c["score"],
            c["skills"],
            c["experience"],
            c["verdict"]
        ])

    file_path = "results.xlsx"
    wb.save(file_path)

    return send_file(file_path, as_attachment=True)


if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    app.run(debug=True)