from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.models.ticket import Ticket
from app.models.user import User
from app.core.database import SessionLocal
from pydantic import BaseModel

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

class TicketCreate(BaseModel):
    title: str
    description: str
    priority: str = "NORMAL"
    assignee_id: int = None

class TicketRead(BaseModel):
    id: int
    title: str
    description: str
    priority: str
    status: str
    creator_id: int
    assignee_id: int = None

    class Config:
        orm_mode = True

@router.get("/", response_model=List[TicketRead])
def list_tickets():
    db = SessionLocal()
    tickets = db.query(Ticket).all()
    db.close()
    return tickets

@router.post("/", response_model=TicketRead)
def create_ticket(ticket_in: TicketCreate):
    db = SessionLocal()
    ticket = Ticket(
        title=ticket_in.title,
        description=ticket_in.description,
        priority=ticket_in.priority,
        creator_id=1,  # Replace with actual user ID from auth if needed
        assignee_id=ticket_in.assignee_id
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    db.close()
    return ticket

@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: int):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    db.close()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket 