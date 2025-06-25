from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.schemas.message import MessageCreate, MessageRead
from app.models.message import Message
from app.core.deps import get_db, get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/messages", tags=["messages"])

@router.post("/", response_model=MessageRead)
def send_message(message_in: MessageCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db_message = Message(
        sender_id=current_user.id,
        receiver_id=message_in.receiver_id,
        ticket_id=message_in.ticket_id,
        content=message_in.content
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

@router.get("/ticket/{ticket_id}", response_model=List[MessageRead])
def list_ticket_messages(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Message).filter(Message.ticket_id == ticket_id).order_by(Message.timestamp).all()

@router.get("/user/{user_id}", response_model=List[MessageRead])
def list_user_messages(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Message).filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()

@router.post("/{message_id}/read")
def mark_message_read(message_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message.receiver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    message.read = True
    db.commit()
    return {"detail": "Message marked as read"} 