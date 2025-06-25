from app.models.ai_response import AIResponse
from sqlalchemy.orm import Session
from datetime import datetime

def generate_ai_response(ticket_id: int, message: str, db: Session) -> AIResponse:
    # Placeholder: In production, call OpenAI/Ollama here
    ai_content = f"[AI Suggestion] You said: '{message}'. Here is a helpful reply."
    ai_response = AIResponse(
        source_type="ticket",
        source_id=ticket_id,
        content=ai_content,
        confidence_score=0.9,
        created_at=datetime.utcnow()
    )
    db.add(ai_response)
    db.commit()
    db.refresh(ai_response)
    return ai_response

def summarize_chat(ticket_id: int, messages: list) -> str:
    # Placeholder: In production, call OpenAI/Ollama here
    if not messages:
        return "No messages to summarize."
    summary = f"Summary: This chat has {len(messages)} messages. "
    summary += f"First message: '{messages[0].content}'"
    if len(messages) > 1:
        summary += f" | Last message: '{messages[-1].content}'"
    return summary

def semantic_search(query: str, user_id: int, db) -> list:
    # Placeholder: In production, use vector embeddings and FAISS or similar
    # For now, do a simple case-insensitive substring search over messages and tickets
    from app.models.message import Message
    from app.models.ticket import Ticket
    message_results = db.query(Message).filter(Message.sender_id == user_id, Message.content.ilike(f"%{query}%")).all()
    ticket_results = db.query(Ticket).filter(Ticket.creator_id == user_id, Ticket.title.ilike(f"%{query}%")).all()
    return message_results, ticket_results 