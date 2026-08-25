import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from agent_service import BIAgentService
from monday_client import MondayClient, required_board_id
from leadership_updater import generate_leadership_update
from bi_engine import get_pipeline_summary, get_revenue_summary, get_sector_performance, get_operational_metrics
from data_normalizer import audit_data_quality

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_server")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    agent_service.client.close()


app = FastAPI(
    title="Skylark Drones - Monday.com BI Agent API",
    description="Founder-level Business Intelligence Agent integrated dynamically with Monday.com boards.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

agent_service = BIAgentService()


class QueryRequest(BaseModel):
    query: str
    force_refresh: Optional[bool] = False


class QueryResponse(BaseModel):
    query: str
    intent: Optional[str] = None
    interpretation: Optional[str] = None
    is_ambiguous: Optional[bool] = False
    answer: str
    explanation: Optional[str] = None
    clarifying_questions: Optional[list[str]] = None
    data: Optional[Any] = None
    caveats: Optional[list[str]] = None
    suggested_followups: Optional[list[str]] = None


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "Skylark Monday BI Agent"}


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(Path(__file__).with_name("favicon.svg"), media_type="image/svg+xml")


@app.get("/api/boards/status")
def get_boards_status() -> dict[str, Any]:
    """Check Monday.com connection health and return record counts."""
    try:
        user = agent_service.client.who_am_i()
        deals_df, wo_df = agent_service.get_dataframes(force_refresh=False)
        return {
            "status": "connected",
            "authenticated_user": user.get("name"),
            "email": user.get("email"),
            "deals_board_id": agent_service.deals_board_id,
            "deals_records_count": len(deals_df),
            "work_orders_board_id": agent_service.wo_board_id,
            "work_orders_records_count": len(wo_df),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/query", response_model=QueryResponse)
def execute_query(req: QueryRequest) -> QueryResponse:
    """Natural language query endpoint for founders and executives."""
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="Query string must not be empty.")
    
    try:
        result = agent_service.answer_query(req.query, force_refresh=req.force_refresh or False)
        intent = result.get("intent")
        interpretation = {
            "PIPELINE": "Interpreted as a sales pipeline question.",
            "REVENUE": "Interpreted as a revenue, collections, or receivables question.",
            "OPERATIONS": "Interpreted as a Work Orders execution question.",
            "DEAL_LOOKUP": "Interpreted as a specific deal lookup.",
            "WORK_ORDER_LOOKUP": "Interpreted as a specific Work Order serial lookup.",
            "DATA_QUALITY": "Interpreted as a data completeness and quality question.",
            "LEADERSHIP_UPDATE": "Interpreted as a founder or leadership briefing request.",
            "SECTOR_SYNTHESIS": "Interpreted as a cross-board sector performance question.",
            "TOTAL_DEAL_VALUE": "Interpreted as a direct Deals metric request.",
        }.get(intent)
        return QueryResponse(
            query=result.get("query", req.query),
            intent=intent,
            interpretation=interpretation,
            is_ambiguous=result.get("is_ambiguous", False),
            answer=result.get("answer", ""),
            explanation=result.get("explanation"),
            clarifying_questions=result.get("clarifying_questions"),
            data=result.get("data"),
            caveats=result.get("caveats"),
            suggested_followups=result.get("suggested_followups"),
        )
    except Exception as exc:
        logger.error("Error executing query: %s", exc)
        raise HTTPException(status_code=500, detail=f"Query execution failed: {exc}")


@app.get("/api/leadership-update")
def get_leadership_update(force_refresh: bool = False) -> dict[str, Any]:
    """Dedicated leadership update workflow endpoint."""
    try:
        deals_df, wo_df = agent_service.get_dataframes(force_refresh=force_refresh)
        return generate_leadership_update(deals_df, wo_df)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/metrics/summary")
def get_metrics_summary(force_refresh: bool = False) -> dict[str, Any]:
    """High-level consolidated KPI scorecard."""
    try:
        deals_df, wo_df = agent_service.get_dataframes(force_refresh=force_refresh)
        pipeline = get_pipeline_summary(deals_df)
        revenue = get_revenue_summary(wo_df)
        return {
            "pipeline": pipeline,
            "revenue": revenue,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/data-quality")
def get_data_quality(force_refresh: bool = False) -> dict[str, Any]:
    """Data resilience and audit caveats."""
    try:
        deals_df, wo_df = agent_service.get_dataframes(force_refresh=force_refresh)
        return audit_data_quality(deals_df, wo_df)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Rich interactive web console for the BI Agent."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BI Agent</title>
        <link rel="icon" type="image/svg+xml" href="/favicon.svg">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg: #050506;
                --surface: #111016;
                --surface-hover: #241936;
                --surface-card: #17131f;
                --border: #30243f;
                --primary: #9b6cff;
                --primary-glow: rgba(155, 108, 255, 0.28);
                --accent: #c08bff;
                --accent-purple: #7544d8;
                --success: #10b981;
                --warning: #f59e0b;
                --danger: #ef4444;
                --text: #f8fafc;
                --text-muted: #94a3b8;
            }
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: 'Plus Jakarta Sans', sans-serif;
                background: radial-gradient(circle at 70% 10%, #1d1232 0%, var(--bg) 42%);
                color: var(--text);
                min-height: 100vh;
                display: flex;
                flex-direction: column;
            }
            header {
                background: rgba(5, 5, 6, 0.88);
                border-bottom: 1px solid var(--border);
                padding: 1rem 2rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
                backdrop-filter: blur(12px);
                position: sticky;
                top: 0;
                z-index: 50;
            }
            .brand { display: flex; align-items: center; gap: 0.75rem; }
            .brand-badge {
                background: linear-gradient(135deg, var(--primary), var(--accent));
                color: white;
                font-weight: 800;
                font-size: 0.85rem;
                padding: 0.35rem 0.65rem;
                border-radius: 8px;
                letter-spacing: 0.5px;
            }
            .brand h1 { font-size: 1.15rem; font-weight: 700; color: #f5efff; }
            main {
                flex: 1;
                max-width: 1280px;
                width: 100%;
                margin: 0 auto;
                padding: 1.5rem;
            }
            .chat-container {
                background-color: var(--surface);
                border: 1px solid var(--border);
                border-radius: 16px;
                display: flex;
                flex-direction: column;
                height: calc(100vh - 120px);
                overflow: hidden;
            }
            .messages {
                flex: 1;
                overflow-y: auto;
                padding: 1.5rem;
                display: flex;
                flex-direction: column;
                gap: 1.25rem;
                scrollbar-color: #4a3864 #0b0a0e;
                scrollbar-width: thin;
            }
            .messages::-webkit-scrollbar { width: 10px; }
            .messages::-webkit-scrollbar-track { background: #0b0a0e; border-radius: 999px; }
            .messages::-webkit-scrollbar-thumb { background: #4a3864; border: 2px solid #0b0a0e; border-radius: 999px; }
            .messages::-webkit-scrollbar-thumb:hover { background: #8f5ee8; }
            .message {
                display: flex;
                flex-direction: column;
                max-width: 90%;
                animation: fadeIn 0.25s ease-out;
            }
            @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
            .message.user { align-self: flex-end; }
            .message.agent { align-self: flex-start; width: 100%; max-width: 100%; }
            .msg-bubble {
                padding: 1rem 1.25rem;
                border-radius: 14px;
                font-size: 0.95rem;
                line-height: 1.55;
            }
            .message.user .msg-bubble {
                background: linear-gradient(135deg, var(--primary), #2563eb);
                color: white;
                border-bottom-right-radius: 4px;
            }
            .message.agent .msg-bubble {
                background: linear-gradient(145deg, #1a1325, #121019);
                border: 1px solid var(--border);
                color: var(--text);
                border-bottom-left-radius: 4px;
                padding: 1.35rem 1.5rem;
                line-height: 1.7;
            }
            .msg-bubble h3 { margin-bottom: 1rem; padding-bottom: 0.7rem; border-bottom: 1px solid var(--border); color: var(--accent); font-size: 1.2rem; }
            .msg-bubble table { width: 100%; border-collapse: collapse; margin: 0.8rem 0; font-size: 0.88rem; }
            .msg-bubble th, .msg-bubble td { padding: 0.5rem 0.75rem; border: 1px solid var(--border); text-align: left; }
            .msg-bubble th { background: rgba(255,255,255,0.05); color: var(--text-muted); }
            .msg-bubble ul { margin-left: 1.25rem; margin-top: 0.4rem; }
            .msg-bubble li { margin-bottom: 0.25rem; }
            .data-row { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 0.5rem; padding: 0.4rem 0; border-bottom: 1px solid var(--border); }
            .data-row span { min-width: 0; overflow-wrap: anywhere; }
            .data-bullet { margin: 0.3rem 0; }
            .answer-gap { height: 0.6rem; }
            .section-label { display: block; margin-top: 1.15rem; margin-bottom: 0.25rem; padding-top: 0.65rem; border-top: 1px solid var(--border); color: var(--accent); font-weight: 700; }
            .section-label:first-child { margin-top: 0; padding-top: 0; border-top: 0; }
            .explanation { margin-top: 0.9rem; border-top: 1px solid var(--border); padding-top: 0.7rem; color: var(--text-muted); }
            .explanation summary { color: var(--accent); cursor: pointer; font-weight: 600; }
            .explanation-content { padding-top: 0.7rem; color: var(--text); }
            .answer-split { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; align-items: stretch; }
            .answer-primary, .answer-ai { min-width: 0; }
            .answer-ai { padding: 1rem; border: 1px solid rgba(192, 139, 255, 0.35); border-radius: 10px; background: rgba(117, 68, 216, 0.08); font-size: 0.92rem; }
            .answer-ai .section-label { margin-top: 0; padding-top: 0; border-top: 0; }
            @media (max-width: 760px) { .answer-split { grid-template-columns: 1fr; } }
            .request-pipeline { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 0.85rem; padding-top: 0.75rem; border-top: 1px solid var(--border); color: var(--text-muted); font-size: 0.78rem; }
            .pipeline-stage { padding: 0.35rem 0.55rem; border: 1px solid var(--border); border-radius: 999px; }
            .pipeline-stage.active { color: var(--accent); border-color: var(--accent); animation: activeGlow 1.1s ease-in-out infinite; }
            .pipeline-stage.active::after { content: ''; display: inline-block; width: 0.3rem; height: 0.3rem; margin-left: 0.35rem; border-radius: 50%; background: currentColor; animation: activeDot 1.1s ease-in-out infinite; }
            .pipeline-stage.done { color: #b9f6d3; border-color: #287b55; }
            .pipeline-stage:not(.active):not(.done) { animation: idleGlow 2.4s ease-in-out infinite; }
            @keyframes activeGlow { 0%, 100% { box-shadow: 0 0 0 rgba(192, 139, 255, 0); } 50% { box-shadow: 0 0 14px rgba(192, 139, 255, 0.28); } }
            @keyframes activeDot { 0%, 100% { opacity: 0.35; } 50% { opacity: 1; } }
            @keyframes idleGlow { 0%, 100% { opacity: 0.58; } 50% { opacity: 0.86; } }
            .caveat-box {
                margin-top: 1.2rem;
                padding: 0.9rem 1rem;
                background: rgba(245, 158, 11, 0.08);
                border: 1px solid rgba(245, 158, 11, 0.35);
                border-left: 4px solid var(--warning);
                border-radius: 6px;
                font-size: 0.9rem;
                line-height: 1.65;
                color: #fde68a;
            }
            .caveat-box strong { display: block; margin-bottom: 0.35rem; color: #fcd34d; }
            .clarify-btn {
                display: inline-block;
                margin: 0.35rem 0.35rem 0 0;
                padding: 0.4rem 0.8rem;
                background: rgba(59, 130, 246, 0.15);
                border: 1px solid var(--primary);
                color: #93c5fd;
                border-radius: 8px;
                font-size: 0.82rem;
                cursor: pointer;
                transition: all 0.2s;
            }
            .clarify-btn:hover { background: var(--primary); color: white; }
            .input-area {
                padding: 1rem 1.25rem 1.1rem;
                border-top: 1px solid var(--border);
                background: linear-gradient(180deg, rgba(15, 12, 23, 0.96), rgba(9, 13, 22, 0.98));
            }
            .query-label {
                display: block;
                margin: 0 0 0.55rem 0.15rem;
                color: var(--text-muted);
                font-family: 'JetBrains Mono', monospace;
                font-size: 0.68rem;
                font-weight: 500;
                letter-spacing: 0.08em;
                text-transform: uppercase;
            }
            .query-composer {
                display: flex;
                align-items: stretch;
                gap: 0.7rem;
            }
            .input-area input {
                flex: 1;
                min-width: 0;
                background: rgba(5, 5, 6, 0.7);
                border: 1px solid #59417c;
                color: var(--text);
                padding: 0.9rem 1.05rem;
                border-radius: 12px;
                font-size: 0.94rem;
                outline: none;
                box-shadow: inset 0 0 0 1px rgba(155, 108, 255, 0.08);
                transition: border-color 0.2s, box-shadow 0.2s, background 0.2s;
            }
            .input-area input::placeholder { color: #7f748f; }
            .input-area input:focus {
                background: rgba(17, 16, 22, 0.95);
                border-color: var(--primary);
                box-shadow: 0 0 0 3px var(--primary-glow);
            }
            .input-area button {
                background: linear-gradient(135deg, #a06cff, #6d3dc8);
                border: 1px solid #b88cff;
                color: white;
                min-width: 88px;
                padding: 0 1.15rem;
                border-radius: 12px;
                font-weight: 600;
                cursor: pointer;
                box-shadow: 0 5px 18px rgba(117, 68, 216, 0.25);
                transition: transform 0.2s, box-shadow 0.2s, opacity 0.2s;
            }
            .input-area button:hover { transform: translateY(-1px); box-shadow: 0 8px 22px rgba(117, 68, 216, 0.38); }
            .input-area button:disabled { cursor: wait; opacity: 0.6; transform: none; }
            @media (max-width: 560px) {
                .input-area { padding: 0.85rem; }
                .query-composer { gap: 0.5rem; }
                .input-area button { min-width: 72px; padding: 0 0.85rem; }
            }
        </style>
    </head>
    <body>
        <header>
            <div class="brand">
                <h1>BI Agent</h1>
            </div>
        </header>

        <main>
            <div class="chat-container">
                <div class="messages" id="chatBox">
                    <div class="message agent">
                        <div class="msg-bubble">
                            <h3>Welcome to BI Agent</h3>
                            <p>Ask questions about the live Deals and Work Orders data.</p>
                            <p style="margin-top: 0.4rem; color: var(--text-muted);">Ask a question to see the live processing stages.</p>
                        </div>
                    </div>
                </div>
                <div class="input-area">
                    <label class="query-label" for="queryInput">Live data query</label>
                    <div class="query-composer">
                        <input type="text" id="queryInput" placeholder="Which sectors contribute most to the current pipeline?" />
                        <button onclick="sendQuery()">Send &gt;</button>
                    </div>
                </div>
            </div>

        </main>

        <script>
            async function sendQuery(customText) {
                const input = document.getElementById('queryInput');
                const query = customText || input.value.trim();
                if (!query) return;
                input.value = '';

                const chatBox = document.getElementById('chatBox');
                const sendButton = document.querySelector('.input-area button');
                chatBox.innerHTML += `
                    <div class="message user">
                        <div class="msg-bubble">${query}</div>
                    </div>
                `;
                chatBox.scrollTop = chatBox.scrollHeight;
                const progressId = 'progress-' + Date.now();
                chatBox.innerHTML += `
                    <div class="message agent" id="${progressId}">
                        <div class="msg-bubble">
                            <strong>Processing request</strong>
                            <div class="request-pipeline">
                                <span class="pipeline-stage active">Prompt received</span>
                                <span class="pipeline-stage">Monday API</span>
                                <span class="pipeline-stage">Normalize</span>
                                <span class="pipeline-stage">Calculate</span>
                                <span class="pipeline-stage">Groq explanation</span>
                                <span class="pipeline-stage">Answer</span>
                            </div>
                        </div>
                    </div>
                `;
                const progress = document.getElementById(progressId);
                const stages = progress.querySelectorAll('.pipeline-stage');
                const advance = (index) => {
                    stages.forEach((stage, position) => {
                        stage.classList.toggle('done', position < index);
                        stage.classList.toggle('active', position === index);
                    });
                };
                sendButton.disabled = true;
                advance(1);
                chatBox.scrollTop = chatBox.scrollHeight;

                try {
                    const res = await fetch('/api/query', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: query })
                    });
                    const data = await res.json();
                    advance(5);
                    
                    let extraHtml = '';
                    if (data.is_ambiguous && data.clarifying_questions) {
                        extraHtml += '<div style="margin-top: 0.6rem;"><strong>Clarification Options:</strong><br>';
                        data.clarifying_questions.forEach(q => {
                            extraHtml += `<button class="clarify-btn" onclick="askPreset('${q.replace(/'/g, "\\'")}')">${q}</button>`;
                        });
                        extraHtml += '</div>';
                    }

                    if (data.caveats && data.caveats.length > 0) {
                        extraHtml += '<div class="caveat-box"><strong>Data handling and remaining caveats:</strong><br>' + data.caveats.slice(0, 2).map(c => `- ${c}`).join('<br>') + '</div>';
                    }

                    if (data.suggested_followups && data.suggested_followups.length > 0) {
                        extraHtml += '<div style="margin-top: 0.6rem;"><strong>Suggested Follow-ups:</strong><br>';
                        data.suggested_followups.forEach(f => {
                            extraHtml += `<button class="clarify-btn" onclick="askPreset('${f.replace(/'/g, "\\'")}')">${f}</button>`;
                        });
                        extraHtml += '</div>';
                    }

                    if (data.explanation) {
                        extraHtml += '<details class="explanation"><summary>Explanation</summary><div class="explanation-content">' + formatMarkdown(data.explanation) + '</div></details>';
                    }
                    const answerParts = splitAnswer(data.answer);
                    const formattedAnswer = `
                        <div class="answer-split">
                            <div class="answer-primary">${formatMarkdown(answerParts.primary)}</div>
                            ${answerParts.ai ? `<div class="answer-ai">${formatMarkdown(answerParts.ai)}</div>` : ''}
                        </div>
                    `;
                    advance(5);
                    progress.remove();
                    chatBox.innerHTML += `
                        <div class="message agent">
                            <div class="msg-bubble">
                                ${formattedAnswer}
                                ${extraHtml}
                            </div>
                        </div>
                    `;
                    chatBox.scrollTop = chatBox.scrollHeight;
                } catch (err) {
                    progress.remove();
                    chatBox.innerHTML += `
                        <div class="message agent">
                            <div class="msg-bubble" style="color: var(--danger);">
                                Error retrieving insight: ${err.message}
                            </div>
                        </div>
                    `;
                } finally {
                    sendButton.disabled = false;
                    input.focus();
                }
            }

            function askPreset(text) {
                sendQuery(text);
            }

            function formatMarkdown(markdown) {
                const escaped = markdown.replace(/[&<>]/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[character]));
                return escaped
                    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
                    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
                    .replace(/\\*\\*(Interpretation|Evidence|Insight|Caveats|Founder Insight|AI Strategic Synthesis[^*]*):\\*\\*/g, '<div class="section-label">$1</div>')
                    .replace(/^(Interpretation|Evidence|Insight|Caveats):\\s*/gm, '<div class="section-label">$1</div>')
                    .replace(/^# (.+)$/gm, '<h3>$1</h3>')
                    .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
                    .replace(/^\\|(.+)\\|$/gm, (_, row) => {
                        if (/^[-| :]+$/.test(row)) return '';
                        return '<div class="data-row">' + row.split('|').map(cell => '<span>' + cell.trim() + '</span>').join('') + '</div>';
                    })
                    .replace(/^[-*] (.+)$/gm, '<div class="data-bullet">$1</div>')
                    .replace(/\\n\\n/g, '<div class="answer-gap"></div>')
                    .replace(/\\n/g, '<br>');
            }

            function splitAnswer(answer) {
                const marker = /\\*\\*(AI Strategic Synthesis \\(Groq LLM\\)|AI explanation):\\*\\*/i;
                const match = answer.match(marker);
                if (!match || match.index === undefined) {
                    return { primary: answer, ai: '' };
                }
                return {
                    primary: answer.slice(0, match.index).trim(),
                    ai: '**' + match[1] + ':**\\n\\n' + answer.slice(match.index + match[0].length).trim()
                };
            }

            document.getElementById('queryInput').addEventListener('keypress', function (e) {
                if (e.key === 'Enter') sendQuery();
            });
        </script>
    </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("UVICORN_RELOAD", "false").lower() == "true",
    )

