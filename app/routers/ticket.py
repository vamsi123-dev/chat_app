from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.schemas.ticket import TicketCreate, TicketRead, TicketUpdate
from app.models.ticket import Ticket, TicketStatus, TicketPriority
from app.core.deps import get_db, get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

@router.post("/", response_model=TicketRead)
def create_ticket(ticket_in: TicketCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db_ticket = Ticket(
        title=ticket_in.title,
        description=ticket_in.description,
        status=ticket_in.status or TicketStatus.OPEN,
        priority=ticket_in.priority or TicketPriority.NORMAL,
        creator_id=current_user.id,
        assignee_id=ticket_in.assignee_id
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)
    return db_ticket

@router.get("/", response_model=List[TicketRead])
def list_tickets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == "admin":
        return db.query(Ticket).all()
    return db.query(Ticket).filter(Ticket.creator_id == current_user.id).all()

@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role != "admin" and ticket.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return ticket

@router.put("/{ticket_id}", response_model=TicketRead)
def update_ticket(ticket_id: int, ticket_in: TicketUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    # Only admin or assignee or creator can update
    if current_user.role != "admin" and ticket.creator_id != current_user.id and ticket.assignee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    for field, value in ticket_in.dict(exclude_unset=True).items():
        setattr(ticket, field, value)
    db.commit()
    db.refresh(ticket)
    return ticket

@router.delete("/{ticket_id}")
def delete_ticket(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    db.delete(ticket)
    db.commit()
    return {"detail": "Ticket deleted"} 