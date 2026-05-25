import os
import uuid
import logging
from typing import Dict

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pypdf import PdfReader
from groq import Groq
from duckduckgo_search import DDGS
import edge_tts

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise Exception("GROQ_API_KEY not found")

groq_client = Groq(api_key=GROQ_API_KEY)

TEMP_DIR = "temp_audio"

os.makedirs(TEMP_DIR, exist_ok=True)

active_sessions: Dict[str, dict] = {}


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {
        "status": "running"
    }


def search_interview_questions(company: str, role: str):

    query = f"{company} {role} interview questions 2025"

    try:

        results = DDGS().text(query, max_results=5)

        context = ""

        for r in results:

            context += f"""
Source: {r.get("title", "")}

Snippet:
{r.get("body", "")}

"""

        return context

    except Exception:

        return ""


def parse_resume(file_path: str):

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


async def generate_audio(text: str):

    filename = f"{uuid.uuid4()}.mp3"

    path = os.path.join(TEMP_DIR, filename)

    communicate = edge_tts.Communicate(
        text=text,
        voice="en-US-BrianNeural"
    )

    await communicate.save(path)

    return filename


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

        temp_resume_path = os.path.join(
            TEMP_DIR,
            f"{uuid.uuid4()}_{resume.filename}"
        )

        with open(temp_resume_path, "wb") as f:
            f.write(await resume.read())

        resume_text = parse_resume(temp_resume_path)

        os.remove(temp_resume_path)

    web_context = search_interview_questions(company, role)

    system_prompt = f"""
You are an expert interviewer for {company}.

Candidate Name: {name}
Role: {role}
Experience: {experience}

Interview Context:
{web_context}

Job Description:
{jd[:1000]}

Resume:
{resume_text[:1500]}

Instructions:
- Ask realistic interview questions
- Ask one question at a time
- Keep questions short
- Be conversational
- Ask exactly {num_questions} questions
"""

    active_sessions[session_id] = {
        "company": company,
        "role": role,
        "conversation_history": [],
        "system_prompt": system_prompt,
        "question_count": 0,
        "max_questions": num_questions
    }

    completion = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": system_prompt
            }
        ],
        temperature=0.7
    )

    ai_message = completion.choices[0].message.content

    active_sessions[session_id]["conversation_history"].append(
        {
            "role": "assistant",
            "content": ai_message
        }
    )

    audio_filename = await generate_audio(ai_message)

    return {
        "session_id": session_id,
        "text": ai_message,
        "audio_url": f"/audio/{audio_filename}",
        "current_question": 1,
        "total_questions": num_questions
    }


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

    temp_audio_path = os.path.join(
        TEMP_DIR,
        f"{uuid.uuid4()}.webm"
    )

    with open(temp_audio_path, "wb") as f:
        f.write(await audio.read())

    with open(temp_audio_path, "rb") as audio_file:

        transcription = groq_client.audio.transcriptions.create(
            file=(temp_audio_path, audio_file.read()),
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

        return {
            "status": "COMPLETED"
        }

    messages = [
        {
            "role": "system",
            "content": session["system_prompt"]
        }
    ] + session["conversation_history"][-6:]

    completion = groq_client.chat.completions.create(
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

    audio_filename = await generate_audio(ai_response)

    return {
        "status": "IN_PROGRESS",
        "text": ai_response,
        "audio_url": f"/audio/{audio_filename}",
        "current_question": session["question_count"] + 1
    }


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

Analyze this interview strictly.

Transcript:
{session['conversation_history']}

Generate:

# Executive Summary

# Technical Accuracy

# Communication

# Critical Thinking

# Strengths

# Weaknesses

# Final Decision
"""

    completion = groq_client.chat.completions.create(
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


@app.get("/audio/{filename}")
async def get_audio(filename: str):

    file_path = os.path.join(TEMP_DIR, filename)

    if not os.path.exists(file_path):

        raise HTTPException(
            status_code=404,
            detail="Audio not found"
        )

    return FileResponse(file_path)