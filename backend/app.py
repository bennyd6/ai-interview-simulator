import os
import uuid
import logging
from typing import Dict

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pypdf import PdfReader
from groq import Groq
import edge_tts
from duckduckgo_search import DDGS
import uvicorn

load_dotenv()

app = FastAPI(title="AI Interview Backend")

logging.basicConfig(level=logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is missing")

GROQ_CLIENT = Groq(api_key=GROQ_API_KEY)

TEMP_DIR = "temp_audio"
os.makedirs(TEMP_DIR, exist_ok=True)

active_sessions: Dict[str, dict] = {}


@app.get("/")
async def health_check():
    return {
        "status": "running",
        "message": "AI Interview Backend Live"
    }


def mcp_search_interview_questions(company: str, role: str) -> str:

    query = f"{company} {role} interview questions 2025"

    try:
        results = DDGS().text(query, max_results=5)

        context = "REAL INTERVIEW DATA FROM WEB:\n\n"

        for r in results:
            context += f"""
Source: {r.get("title", "")}
Snippet: {r.get("body", "")}

"""

        return context

    except Exception:
        return "Could not fetch interview data from the web."


def parse_resume(file_path: str) -> str:

    try:
        reader = PdfReader(file_path)

        text = ""

        for page in reader.pages:
            extracted = page.extract_text()

            if extracted:
                text += extracted

        return text[:3000]

    except Exception:
        return ""


async def text_to_speech_file(text: str) -> str:

    output_file = f"{TEMP_DIR}/{uuid.uuid4()}.mp3"

    communicate = edge_tts.Communicate(
        text=text,
        voice="en-US-BrianNeural"
    )

    await communicate.save(output_file)

    return output_file


@app.post("/start_interview")
async def start_interview(
    name: str = Form(...),
    company: str = Form(...),
    role: str = Form(...),
    experience: str = Form(...),
    num_questions: int = Form(...),
    jd: str = Form(""),
    resume: UploadFile = File(None)
):

    session_id = str(uuid.uuid4())

    resume_text = ""

    if resume:

        temp_pdf_path = f"{TEMP_DIR}/{uuid.uuid4()}_{resume.filename}"

        with open(temp_pdf_path, "wb") as f:
            f.write(await resume.read())

        resume_text = parse_resume(temp_pdf_path)

        os.remove(temp_pdf_path)

    search_context = mcp_search_interview_questions(company, role)

    system_prompt = f"""
You are an expert interviewer for {company}.

Candidate Name: {name}
Role: {role}
Experience: {experience} years

WEB SEARCH CONTEXT:
{search_context}

JOB DESCRIPTION:
{jd[:1000]}

RESUME:
{resume_text[:1500]}

RULES:
- Ask realistic interview questions
- Keep questions short
- Be conversational
- Ask exactly {num_questions} questions
- Start with a welcome message and first question
- Ask one question at a time
"""

    active_sessions[session_id] = {
        "candidate_name": name,
        "company": company,
        "role": role,
        "system_prompt": system_prompt,
        "conversation_history": [],
        "question_count": 0,
        "max_questions": num_questions
    }

    completion = GROQ_CLIENT.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": system_prompt
            }
        ],
        temperature=0.7
    )

    initial_text = completion.choices[0].message.content

    active_sessions[session_id]["conversation_history"].append(
        {
            "role": "assistant",
            "content": initial_text
        }
    )

    audio_path = await text_to_speech_file(initial_text)

    return JSONResponse(
        {
            "session_id": session_id,
            "text": initial_text,
            "audio_url": f"/get_audio/{os.path.basename(audio_path)}",
            "current_question": 1,
            "total_questions": num_questions
        }
    )


@app.post("/process_response")
async def process_response(
    session_id: str = Form(...),
    audio: UploadFile = File(...)
):

    if session_id not in active_sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    session = active_sessions[session_id]

    temp_audio_path = f"{TEMP_DIR}/{uuid.uuid4()}.webm"

    with open(temp_audio_path, "wb") as f:
        f.write(await audio.read())

    with open(temp_audio_path, "rb") as file:

        transcription = GROQ_CLIENT.audio.transcriptions.create(
            file=(temp_audio_path, file.read()),
            model="whisper-large-v3",
            response_format="text"
        )

    os.remove(temp_audio_path)

    user_text = transcription

    session["conversation_history"].append(
        {
            "role": "user",
            "content": user_text
        }
    )

    session["question_count"] += 1

    if session["question_count"] >= session["max_questions"]:

        return JSONResponse(
            {
                "status": "COMPLETED"
            }
        )

    messages = [
        {
            "role": "system",
            "content": session["system_prompt"]
        }
    ] + session["conversation_history"][-6:]

    completion = GROQ_CLIENT.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        temperature=0.6
    )

    ai_response = completion.choices[0].message.content

    session["conversation_history"].append(
        {
            "role": "assistant",
            "content": ai_response
        }
    )

    audio_path = await text_to_speech_file(ai_response)

    return JSONResponse(
        {
            "status": "IN_PROGRESS",
            "text": ai_response,
            "audio_url": f"/get_audio/{os.path.basename(audio_path)}",
            "current_question": session["question_count"] + 1
        }
    )


@app.post("/generate_feedback")
async def generate_feedback(
    session_id: str = Form(...)
):

    if session_id not in active_sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    session = active_sessions[session_id]

    prompt = f"""
You are a senior interviewer at {session['company']}.

Analyze the interview transcript strictly.

TRANSCRIPT:
{session['conversation_history']}

Generate a markdown report with:

# Executive Summary

# Detailed Metrics
- Technical Accuracy
- Communication
- Critical Thinking
- Culture Fit

# Strengths

# Areas for Improvement

# Final Decision
(HIRE / NO HIRE)
"""

    completion = GROQ_CLIENT.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return {
        "report": completion.choices[0].message.content
    }


@app.get("/get_audio/{filename}")
async def get_audio(filename: str):

    file_path = f"{TEMP_DIR}/{filename}"

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Audio file not found"
        )

    return FileResponse(file_path)


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8000))

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port
    )