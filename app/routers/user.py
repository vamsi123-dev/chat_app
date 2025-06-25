from fastapi import APIRouter, Depends, HTTPException, status, Form, Cookie, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
from app.schemas.user import UserRead, UserBase
from app.models.user import User, FriendRequest, UserContact
from app.core.deps import get_db, get_current_user
from app.core.security import decode_access_token
from sqlalchemy import or_, and_
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi import Request
import os
import shutil

router = APIRouter(prefix="/api/users", tags=["users"])

def get_current_user_id(access_token: str = None) -> int:
    if not access_token:
        return None
    payload = decode_access_token(access_token)
    if not payload or "sub" not in payload:
        return None
    return int(payload["sub"])

@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user

@router.get("/", response_model=List[UserRead])
def read_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    users = db.query(User).offset(skip).limit(limit).all()
    return users

@router.get("/profile", response_class=JSONResponse)
def get_profile(request: Request, db: Session = Depends(get_db), access_token: str = Cookie(None)):
    user_id = get_current_user_id(access_token)
    if not user_id:
        return JSONResponse({"error": "You must be logged in to view your profile."}, status_code=401)
    user = db.query(User).filter(User.id == user_id).first()
    return {"user": user_id, "profile": user.email if user else None}

@router.post("/profile", response_class=JSONResponse)
def update_profile(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(None), avatar: UploadFile = File(None), db: Session = Depends(get_db), access_token: str = Cookie(None)):
    user_id = get_current_user_id(access_token)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    user.name = name
    user.email = email
    if password:
        from app.core.security import get_password_hash
        user.password_hash = get_password_hash(password)
    if avatar:
        avatar_path = f"uploads/avatars/user_{user_id}_{avatar.filename}"
        with open(avatar_path, "wb") as buffer:
            shutil.copyfileobj(avatar.file, buffer)
        user.avatar = avatar_path
    db.commit()
    db.refresh(user)
    return {"detail": "Profile updated successfully!", "user": user_id}

@router.get("/{user_id}", response_model=UserRead)
def read_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"detail": "User deleted"}

# Friend Request Routes (separate from user routes to avoid conflicts)
@router.get("/friends/list", response_class=JSONResponse)
def get_friends_list(request: Request, db: Session = Depends(get_db), access_token: str = Cookie(None)):
    user_id = get_current_user_id(access_token)
    users = db.query(User).filter(User.id != user_id).all()
    contacts = db.query(UserContact).filter(
        or_(UserContact.user1_id == user_id, UserContact.user2_id == user_id)
    ).all()
    contact_ids = set()
    for contact in contacts:
        if contact.user1_id == user_id:
            contact_ids.add(contact.user2_id)
        else:
            contact_ids.add(contact.user1_id)
    pending_requests = db.query(FriendRequest).filter(
        and_(FriendRequest.sender_id == user_id, FriendRequest.status == "PENDING")
    ).all()
    pending_ids = {req.receiver_id for req in pending_requests}
    incoming_requests = db.query(FriendRequest).filter(
        and_(FriendRequest.receiver_id == user_id, FriendRequest.status == "PENDING")
    ).all()
    return {
        "users": [u.id for u in users],
        "contacts": [c.id for c in contacts],
        "contact_ids": list(contact_ids),
        "pending_requests": [r.id for r in pending_requests],
        "pending_ids": list(pending_ids),
        "incoming_requests": [r.id for r in incoming_requests],
        "user_id": user_id
    }

@router.post("/friends/send-request", response_class=HTMLResponse)
def send_friend_request(receiver_id: int = Form(...), db: Session = Depends(get_db), access_token: str = Cookie(None)):
    user_id = get_current_user_id(access_token)
    
    # Check if request already exists
    existing_request = db.query(FriendRequest).filter(
        and_(FriendRequest.sender_id == user_id, FriendRequest.receiver_id == receiver_id)
    ).first()
    
    if existing_request:
        return HTMLResponse('<div class="text-red-600">Friend request already sent!</div>')
    
    # Check if already contacts
    existing_contact = db.query(UserContact).filter(
        or_(
            and_(UserContact.user1_id == user_id, UserContact.user2_id == receiver_id),
            and_(UserContact.user1_id == receiver_id, UserContact.user2_id == user_id)
        )
    ).first()
    
    if existing_contact:
        return HTMLResponse('<div class="text-green-600">Already friends!</div>')
    
    # Create new request
    friend_request = FriendRequest(sender_id=user_id, receiver_id=receiver_id)
    db.add(friend_request)
    db.commit()
    
    return HTMLResponse('<div class="text-green-600">Friend request sent!</div>')

@router.post("/friends/accept-request", response_class=HTMLResponse)
def accept_friend_request(request_id: int = Form(...), db: Session = Depends(get_db), access_token: str = Cookie(None)):
    user_id = get_current_user_id(access_token)
    
    # Get the request
    friend_request = db.query(FriendRequest).filter(
        and_(FriendRequest.id == request_id, FriendRequest.receiver_id == user_id)
    ).first()
    
    if not friend_request:
        return HTMLResponse('<div class="text-red-600">Request not found!</div>')
    
    # Update request status
    friend_request.status = "ACCEPTED"
    
    # Create contact relationship
    contact = UserContact(user1_id=friend_request.sender_id, user2_id=friend_request.receiver_id)
    db.add(contact)
    db.commit()
    
    return HTMLResponse('<div class="text-green-600">Friend request accepted!</div>')

@router.post("/friends/reject-request", response_class=HTMLResponse)
def reject_friend_request(request_id: int = Form(...), db: Session = Depends(get_db), access_token: str = Cookie(None)):
    user_id = get_current_user_id(access_token)
    
    # Get the request
    friend_request = db.query(FriendRequest).filter(
        and_(FriendRequest.id == request_id, FriendRequest.receiver_id == user_id)
    ).first()
    
    if not friend_request:
        return HTMLResponse('<div class="text-red-600">Request not found!</div>')
    
    # Update request status
    friend_request.status = "REJECTED"
    db.commit()
    
    return HTMLResponse('<div class="text-green-600">Friend request rejected!</div>')

@router.get("/friends/contacts", response_class=JSONResponse)
def get_contacts(request: Request, db: Session = Depends(get_db), access_token: str = Cookie(None)):
    user_id = get_current_user_id(access_token)
    contacts = db.query(UserContact).filter(
        or_(UserContact.user1_id == user_id, UserContact.user2_id == user_id)
    ).all()
    contact_users = []
    for contact in contacts:
        if contact.user1_id == user_id:
            contact_users.append(contact.user2)
        else:
            contact_users.append(contact.user1)
    return {"contacts": [u.id for u in contact_users], "user_id": user_id} 