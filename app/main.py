from fastapi import FastAPI, Request, Form, status, Depends, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.routers import auth, user, ticket, message, ws_chat, ws_status
from app.core.security import verify_password, create_access_token, decode_access_token, get_password_hash
from app.core.database import SessionLocal
from app.models.user import User
from app.models.ticket import Ticket, TicketStatus
from sqlalchemy.orm import Session, joinedload
from app.models.message import Message
from app.models.ai_response import AIResponse
import os
from app.core.ai import generate_ai_response, summarize_chat, semantic_search
from sqlalchemy import or_
from app.routers.ws_chat import send_notification_to_user
from fastapi.staticfiles import StaticFiles

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.include_router(auth.router)
app.include_router(user.router)
app.include_router(ticket.router)
app.include_router(message.router)
app.include_router(ws_chat.router)
app.include_router(ws_status.router)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=JSONResponse)
def read_root(request: Request):
    return {"message": "Welcome to the backend API. No frontend available."}

@app.post("/login", response_class=JSONResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, user.password_hash):
        return JSONResponse({"error": "Invalid email or password"}, status_code=401)
    access_token = create_access_token({"sub": str(user.id)})
    db.close()
    return {"access_token": access_token}

@app.get("/dashboard", response_class=JSONResponse)
def dashboard(request: Request, access_token: str = Cookie(None)):
    if not access_token:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    db = SessionLocal()
    payload = decode_access_token(access_token)
    user = None
    tickets = []
    contacts = []
    pending_requests = []
    find_users = []
    debug_tickets = []
    debug_users = {}
    if payload and "sub" in payload:
        user = db.query(User).filter(User.id == int(payload["sub"])).first()
        if user:
            tickets = db.query(Ticket).options(
                joinedload(Ticket.assignee),
                joinedload(Ticket.creator)
            ).filter(
                or_(Ticket.creator_id == user.id, Ticket.assignee_id == user.id)
            ).all()
            from app.models.user import UserContact, FriendRequest
            contacts = db.query(UserContact).filter(
                or_(UserContact.user1_id == user.id, UserContact.user2_id == user.id)
            ).all()
            pending_requests = db.query(FriendRequest).options(joinedload(FriendRequest.receiver)).filter(
                (FriendRequest.sender_id == user.id) & (FriendRequest.status == "PENDING")
            ).all()
            contact_ids = set()
            for contact in contacts:
                if contact.user1_id == user.id:
                    contact_ids.add(contact.user2_id)
                else:
                    contact_ids.add(contact.user1_id)
            contact_ids.add(user.id)
            find_users = db.query(User).filter(~User.id.in_(contact_ids)).all()
            debug_tickets = db.query(Ticket).all()
            for u in db.query(User).all():
                debug_users[u.id] = u.email
    db.close()
    return {"user": user.id if user else None, "tickets": [t.id for t in tickets], "contacts": [c.id for c in contacts], "pending_requests": [r.id for r in pending_requests], "find_users": [u.id for u in find_users], "debug_tickets": [t.id for t in debug_tickets], "debug_users": debug_users, "access_token": access_token}

@app.get("/dashboard/tickets", response_class=HTMLResponse)
def dashboard_tickets(request: Request, access_token: str = Cookie(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    user_id = None
    payload = decode_access_token(access_token)
    if payload and "sub" in payload:
        user_id = int(payload["sub"])
    if not user_id:
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    tickets = db.query(Ticket).filter(or_(Ticket.creator_id == user_id, Ticket.assignee_id == user_id)).all()
    db.close()
    html = "".join([
        f'<div class="p-4 mb-2 bg-white rounded shadow cursor-pointer hover:bg-blue-50" ' +
        f'hx-get="/dashboard/chat/{t.id}" hx-target="#chat-history" hx-swap="innerHTML">' +
        f'<div class="font-semibold">{t.title}</div>' +
        f'<div class="text-sm text-gray-600">Status: {t.status} | Priority: {t.priority}</div>' +
        f'</div>' for t in tickets
    ])
    return HTMLResponse(html)

@app.get("/dashboard/tickets/filter", response_class=HTMLResponse)
def dashboard_ticket_filter(request: Request, access_token: str = Cookie(None), status: str = "all"): 
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    user_id = None
    payload = decode_access_token(access_token)
    if payload and "sub" in payload:
        user_id = int(payload["sub"])
    if not user_id:
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    from app.models.ticket import Ticket
    query = db.query(Ticket).filter(or_(Ticket.creator_id == user_id, Ticket.assignee_id == user_id))
    if status != "all":
        query = query.filter(Ticket.status == status.upper())
    tickets = query.order_by(Ticket.created_at.desc()).all()
    db.close()
    html = ""
    for t in tickets:
        status_label = t.status.lower().replace('_', ' ')
        if t.status == 'OPEN':
            status_color = 'green-600'
        elif t.status == 'IN_PROGRESS':
            status_color = 'orange-500'
        elif t.status == 'WAITING_USER':
            status_color = 'blue-600'
        else:
            status_color = 'red-500'
        # Red alert for high/critical priority
        card_bg = 'bg-white'
        card_border = 'border-l-4 border-blue-400'
        card_hover = 'hover:bg-blue-50'
        if t.priority in ['HIGH', 'CRITICAL']:
            card_bg = 'bg-red-100'
            card_border = 'border-l-4 border-red-600 animate-pulse'
            card_hover = 'hover:bg-red-200'
        html += f'''<div class=\"p-4 {card_bg} rounded shadow cursor-pointer {card_hover} {card_border}\"
            hx-get=\"/dashboard/chat/{t.id}\" hx-target=\"#main-area\" hx-swap=\"innerHTML\">
            <div class=\"flex items-center justify-between\">
                <span class=\"font-semibold truncate w-40\">{t.title}</span>
                <span class=\"text-xs bg-orange-100 text-orange-700 px-2 py-1 rounded\">{t.priority.lower()}</span>
            </div>
            <div class=\"text-xs text-gray-500 truncate\">{t.description}</div>
            <div class=\"flex items-center gap-2 mt-1\">
                <span class=\"text-{status_color} text-xs font-bold\">{status_label}</span>
                <span class=\"text-xs text-gray-400\">• {t.created_at.strftime('%I:%M %p')}</span>
            </div>
        </div>'''
    if not tickets:
        html = '<div class=\"text-gray-400 text-center\">No tickets found.</div>'
    return HTMLResponse(html)

@app.get("/dashboard/tickets/search", response_class=HTMLResponse)
def dashboard_ticket_search(request: Request, access_token: str = Cookie(None), q: str = ""): 
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    user_id = None
    payload = decode_access_token(access_token)
    if payload and "sub" in payload:
        user_id = int(payload["sub"])
    if not user_id:
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    from app.models.ticket import Ticket
    query = db.query(Ticket).filter(or_(Ticket.creator_id == user_id, Ticket.assignee_id == user_id))
    if q:
        query = query.filter(Ticket.title.ilike(f"%{q}%"))
    tickets = query.order_by(Ticket.created_at.desc()).all()
    db.close()
    html = ""
    for t in tickets:
        status_label = t.status.lower().replace('_', ' ')
        if t.status == 'OPEN':
            status_color = 'green-600'
        elif t.status == 'IN_PROGRESS':
            status_color = 'orange-500'
        elif t.status == 'WAITING_USER':
            status_color = 'blue-600'
        else:
            status_color = 'red-500'
        card_bg = 'bg-white'
        card_border = 'border-l-4 border-blue-400'
        card_hover = 'hover:bg-blue-50'
        if t.priority in ['HIGH', 'CRITICAL']:
            card_bg = 'bg-red-100'
            card_border = 'border-l-4 border-red-600 animate-pulse'
            card_hover = 'hover:bg-red-200'
        html += f'''<div class="p-4 {card_bg} rounded shadow cursor-pointer {card_hover} {card_border}"
            hx-get="/dashboard/chat/{t.id}" hx-target="#main-area" hx-swap="innerHTML">
            <div class="flex items-center justify-between">
                <span class="font-semibold truncate w-40">{t.title}</span>
                <span class="text-xs bg-orange-100 text-orange-700 px-2 py-1 rounded">{t.priority.lower()}</span>
            </div>
            <div class="text-xs text-gray-500 truncate">{t.description}</div>
            <div class="flex items-center gap-2 mt-1">
                <span class="text-{status_color} text-xs font-bold">{status_label}</span>
                <span class="text-xs text-gray-400">• {t.created_at.strftime('%I:%M %p')}</span>
            </div>
        </div>'''
    if not tickets:
        html = '<div class="text-gray-400 text-center">No tickets found.</div>'
    return HTMLResponse(html)

@app.get("/dashboard/chat/{ticket_id}", response_class=HTMLResponse)
def dashboard_chat(ticket_id: int, request: Request, access_token: str = Cookie(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    user_id = None
    payload = decode_access_token(access_token)
    if payload and "sub" in payload:
        user_id = int(payload["sub"])
    if not user_id:
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    
    # Add joinedload for assignee relationship
    ticket = db.query(Ticket).options(joinedload(Ticket.assignee)).filter(Ticket.id == ticket_id).first()
    messages = db.query(Message).filter(Message.ticket_id == ticket_id).order_by(Message.timestamp).all()
    ai_suggestion = db.query(AIResponse).filter(AIResponse.source_type == "ticket", AIResponse.source_id == ticket_id).order_by(AIResponse.created_at.desc()).first()
    
    # No need to query assignee separately since we used joinedload
    creator = db.query(User).filter(User.id == ticket.creator_id).first() if ticket else None
    
    # Build chat header with menu, then format with variables
    assignment_info = ""
    if ticket:
        if user_id == ticket.creator_id and ticket.assignee:
            assignment_info = f"<span class='text-blue-100 text-xs'>Assigned to: {ticket.assignee.name}</span>"
        elif user_id == ticket.assignee_id:
            creator = db.query(User).filter(User.id == ticket.creator_id).first()
            if creator:
                assignment_info = f"<span class='text-blue-100 text-xs'>Assigned by: {creator.name}</span>"
    chat_header = f"""
      <div class='flex-none flex items-center gap-3 px-4 py-3 border-b bg-gradient-to-r from-blue-600 to-blue-400 rounded-t-lg sticky top-0 z-10 relative'>
        <div class='w-10 h-10 rounded-full bg-white flex items-center justify-center text-blue-700 font-bold text-lg shadow'>
          <img src='https://ui-avatars.com/api/?name={ticket.assignee.name if ticket.assignee else creator.name}&background=0D8ABC&color=fff' class='w-10 h-10 rounded-full' />
        </div>
        <div class='flex flex-col flex-1'>
          <span class='text-white font-semibold'>{ticket.title if ticket else 'Chat'}</span>
          {assignment_info}
        </div>
"""
    if ticket and ticket.status != "CLOSED" and (user_id == ticket.creator_id or user_id == ticket.assignee_id):
        chat_header += f"""
        <div class='relative flex items-center gap-2'>
          <button id='audio-call-btn' class='bg-green-500 text-white px-3 py-1 rounded hover:bg-green-600'>Audio Call</button>
          <button id='video-call-btn' class='bg-blue-500 text-white px-3 py-1 rounded hover:bg-blue-600'>Video Call</button>
          <div class="relative inline-flex items-center">
              <span class="w-3 h-3 rounded-full bg-red-500" data-user-status="{ticket.assignee_id if ticket.assignee else ''}" 
                    title="User status"></span>
          </div>
          <button id='menu-btn' class='text-white hover:bg-blue-700 rounded-full p-2 focus:outline-none' onclick='toggleMenu(event)'>
            <svg xmlns='http://www.w3.org/2000/svg' class='h-6 w-6' fill='none' viewBox='0 0 24 24' stroke='currentColor'><circle cx='12' cy='6' r='1.5'/><circle cx='12' cy='12' r='1.5'/><circle cx='12' cy='18' r='1.5'/></svg>
          </button>
          <div id='menu-dropdown' class='hidden absolute right-0 mt-2 w-40 bg-white rounded shadow-lg z-50'>
            <button hx-post='/dashboard/ticket/{ticket_id}/close' hx-target='#main-area' hx-swap='innerHTML' class='w-full text-left px-4 py-2 text-red-600 hover:bg-red-50 flex items-center gap-2'>
              <svg xmlns='http://www.w3.org/2000/svg' class='h-5 w-5' fill='none' viewBox='0 0 24 24' stroke='currentColor'><path stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M6 18L18 6M6 6l12 12'/></svg>
              Close Ticket
            </button>
          </div>
        </div>
        """
    chat_header += "</div>"
    html = f"""
    <div id='main-area' class='flex flex-col w-full max-w-2xl mx-auto bg-white rounded-lg shadow-lg border border-gray-200 h-full min-h-0'>
    {chat_header}
      <div id='chat-area' data-ticket-id='{ticket_id}' data-user-id='{user_id}' data-token='{access_token}' class='flex flex-col flex-1 h-full w-full min-h-0'>
        <div id='chat-messages' class='flex-1 overflow-y-auto p-4 space-y-2 bg-gray-50 min-h-0' style='min-height:0;'>
""".format(
        avatar_name=(ticket.assignee.name if ticket.assignee else creator.name),
        ticket_title=(ticket.title if ticket else 'Chat'),
        assignee_name=(ticket.assignee.name if ticket.assignee else 'Unassigned'),
        ticket_id=ticket_id,
        user_id=user_id,
        access_token=access_token
    )
    for m in messages:
        is_me = m.sender_id == user_id
        align = "justify-end" if is_me else "justify-start"
        bubble = "bg-blue-500 text-white" if is_me else "bg-gray-100 text-gray-900"
        tail = "rounded-br-2xl rounded-tl-2xl rounded-bl-md" if is_me else "rounded-bl-2xl rounded-tr-2xl rounded-br-md"
        avatar_url = "https://ui-avatars.com/api/?name={}&background=0D8ABC&color=fff".format('Me' if is_me else (ticket.assignee.name if m.sender_id == (ticket.assignee.id if ticket.assignee else -1) else creator.name))
        sender_name = 'You' if is_me else (ticket.assignee.name if m.sender_id == (ticket.assignee.id if ticket.assignee else -1) else creator.name)
        html += """
        <div class='flex {align} items-end gap-2'>
          {avatar}
          <div class='rounded-2xl px-4 py-2 {bubble} {tail} max-w-xs shadow text-sm'>
            <div class='font-semibold text-xs mb-1'>{sender_name}</div>
            <div>{content}</div>
            <div class='text-xs text-right text-gray-400 mt-1'>{timestamp}</div>
          </div>
          {right_avatar}
        </div>
        """.format(
            align=align,
            avatar=("<div class='w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center'><img src='{}' class='w-8 h-8 rounded-full'/></div>".format(avatar_url) if not is_me else ''),
            bubble=bubble,
            tail=tail,
            sender_name=sender_name,
            content=m.content,
            timestamp=m.timestamp.strftime('%I:%M %p'),
            right_avatar=("<div class='w-8 h-8'></div>" if is_me else '')
        )
    html += "</div>"
    if ai_suggestion:
        html += "<div class='mt-2 p-3 bg-yellow-100 border-l-4 border-yellow-400 text-yellow-800 rounded'><b>AI Suggestion:</b> {}</div>".format(ai_suggestion.content)
    if ticket and ticket.status == "CLOSED":
        html += """
        <div class='flex-none w-full flex items-center justify-center bg-gray-100 border-t p-4 text-red-600 font-semibold rounded-b-lg'>
            This ticket is closed. You can no longer send messages.
        </div>
        """
    else:
        html += """
        <form id='send-message-form' class='flex-none w-full flex bg-white border-t p-2 sticky bottom-0 z-10' onsubmit='return sendChatMessage(event);'>
          <button type='button' id='emoji-btn' class='mr-2 text-2xl'>😊</button>
          <input type='text' id='chat-input' name='content' class='flex-1 border rounded-l px-3 py-2 focus:outline-none' placeholder='Type a message...' required autocomplete='off'>
          <button type='submit' class='bg-blue-600 text-white px-4 py-2 rounded-r ml-2'>Send</button>
        </form>
        <emoji-picker id='emoji-picker' style='display:none;position:absolute;bottom:60px;left:20px;z-index:50;'></emoji-picker>
        """
    html += "</div>"
    if ai_suggestion:
        html += "<div class='mt-2 p-3 bg-yellow-100 border-l-4 border-yellow-400 text-yellow-800 rounded'><b>AI Suggestion:</b> {}</div>".format(ai_suggestion.content)
    html += """
    <script src="https://cdn.jsdelivr.net/npm/emoji-picker-element@^1/index.js" type="module"></script>
    <script>
      function sendChatMessage(e) {
        e.preventDefault();
        var input = document.getElementById('chat-input');
        var msg = input.value.trim();
        if (!msg || !window.ticketSocket || window.ticketSocket.readyState !== 1) return false;
        window.ticketSocket.send(msg);
        input.value = '';
        return false;
      }
      setTimeout(function(){var chat=document.getElementById('chat-messages');if(chat){chat.scrollTop=chat.scrollHeight;}},100);
    </script>
    """
    # Append the JS block after formatting to avoid KeyError
    if ticket and ticket.status != "CLOSED" and (user_id == ticket.creator_id or user_id == ticket.assignee_id):
        html += """
        <script>
        function toggleMenu(e) {
          e.stopPropagation();
          var menu = document.getElementById('menu-dropdown');
          if (menu) menu.classList.toggle('hidden');
        }
        document.addEventListener('click', function() {
          var menu = document.getElementById('menu-dropdown');
          if (menu) menu.classList.add('hidden');
        });
        </script>
        """
    db.close()  # Close the database session
    return HTMLResponse(html)

@app.post("/dashboard/chat/{ticket_id}/send", response_class=HTMLResponse)
def dashboard_send_message(ticket_id: int, request: Request, content: str = Form(...), access_token: str = Cookie(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    user_id = None
    payload = decode_access_token(access_token)
    if payload and "sub" in payload:
        user_id = int(payload["sub"])
    if not user_id:
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    db_message = Message(sender_id=user_id, ticket_id=ticket_id, content=content)
    db.add(db_message)
    # Set ticket to IN_PROGRESS if it was OPEN
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if ticket and ticket.status == TicketStatus.OPEN:
        ticket.status = TicketStatus.IN_PROGRESS
    db.commit()
    db.refresh(db_message)
    # Generate AI response
    ai_response = generate_ai_response(ticket_id, content, db)
    db.close()
    # Reload chat area into #main-area
    return dashboard_chat(ticket_id, request, access_token)

@app.post("/dashboard/chat/{ticket_id}/summarize", response_class=HTMLResponse)
def dashboard_chat_summarize(ticket_id: int, request: Request, access_token: str = Cookie(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    payload = decode_access_token(access_token)
    if not payload or "sub" not in payload:
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    messages = db.query(Message).filter(Message.ticket_id == ticket_id).order_by(Message.timestamp).all()
    summary = summarize_chat(ticket_id, messages)
    db.close()
    html = f"<div class='mt-2 p-3 bg-blue-100 border-l-4 border-blue-400 text-blue-800 rounded'><b>Chat Summary:</b> {summary}</div>"
    return HTMLResponse(html)

@app.post("/dashboard/search", response_class=HTMLResponse)
def dashboard_search(request: Request, query: str = Form(...), access_token: str = Cookie(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    payload = decode_access_token(access_token)
    if not payload or "sub" not in payload:
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    user_id = int(payload["sub"])
    message_results, ticket_results = semantic_search(query, user_id, db)
    db.close()
    html = "<div class='mb-2 font-bold'>Ticket Results:</div>"
    for t in ticket_results:
        html += f'<div class="p-2 bg-white rounded shadow mb-2"><b>{t.title}</b> <span class="text-xs text-gray-500">Status: {t.status}</span></div>'
    html += "<div class='mb-2 font-bold'>Message Results:</div>"
    for m in message_results:
        html += f'<div class="p-2 bg-gray-100 rounded mb-2">{m.content} <span class="text-xs text-gray-500">[{m.timestamp:%Y-%m-%d %H:%M}]</span></div>'
    if not ticket_results and not message_results:
        html += "<div class='text-gray-500'>No results found.</div>"
    return HTMLResponse(html)

@app.get("/api/dashboard/stats", response_class=JSONResponse)
def dashboard_stats(access_token: str = Cookie(None)):
    if not access_token:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    db = SessionLocal()
    payload = decode_access_token(access_token)
    if not payload or "sub" not in payload:
        return JSONResponse({"error": "Invalid token"}, status_code=401)
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user or user.role != "admin":
        return JSONResponse({"error": "Not authorized"}, status_code=403)
    user_count = db.query(User).count()
    ticket_count = db.query(Ticket).count()
    open_tickets = db.query(Ticket).filter(Ticket.status == "OPEN").count()
    closed_tickets = db.query(Ticket).filter(Ticket.status == "CLOSED").count()
    message_count = db.query(Message).count()
    db.close()
    return {
        "user_count": user_count,
        "ticket_count": ticket_count,
        "open_tickets": open_tickets,
        "closed_tickets": closed_tickets,
        "message_count": message_count
    }

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, access_token: str = Cookie(None)):
    if not access_token:
        return RedirectResponse(url="/", status_code=302)
    db = SessionLocal()
    payload = decode_access_token(access_token)
    if not payload or "sub" not in payload:
        return RedirectResponse(url="/", status_code=302)
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    db.close()
    if not user or user.role != "admin":
        return RedirectResponse(url="/", status_code=302)
    return HTMLResponse("Admin dashboard")

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return HTMLResponse("Register page")

@app.post("/register", response_class=HTMLResponse)
def register(request: Request, name: str = Form(...), email: str = Form(...), password: str = Form(...), role: str = Form(...)):
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    if user:
        return HTMLResponse("Email already registered", status_code=400)
    hashed_password = get_password_hash(password)
    db_user = User(
        name=name,
        email=email,
        role=role,
        password_hash=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    db.close()
    # Redirect to login page after successful registration
    return RedirectResponse(url="/", status_code=302)

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token")
    return response

@app.post("/dashboard/tickets/create", response_class=HTMLResponse)
async def dashboard_ticket_create(request: Request, access_token: str = Cookie(None), title: str = Form(...), description: str = Form(...), priority: str = Form('NORMAL'), assignee_id: str = Form(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    user_id = None
    payload = decode_access_token(access_token)
    if payload and "sub" in payload:
        user_id = int(payload["sub"])
    if not user_id:
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    from app.models.ticket import Ticket
    # Prevent duplicate tickets
    query = db.query(Ticket).filter(
        Ticket.title == title,
        Ticket.description == description,
        Ticket.creator_id == user_id,
        Ticket.assignee_id == (int(assignee_id) if assignee_id else None),
        Ticket.status != TicketStatus.CLOSED
    )
    if query.first():
        db.close()
        return HTMLResponse('<div class="text-red-600 text-center">Duplicate ticket: A ticket with the same title, description, creator, and assignee already exists.</div>', status_code=400)
    ticket = Ticket(title=title, description=description, priority=priority, status='OPEN', creator_id=user_id)
    if assignee_id:
        ticket.assignee_id = int(assignee_id)
    db.add(ticket)
    db.commit()
    # Send notification to assignee if not the creator
    if assignee_id and int(assignee_id) != user_id:
        payload = f"NOTIFY:ticket:{ticket.id}:{ticket.title}:{ticket.description[:30]}"
        await send_notification_to_user(int(assignee_id), payload)
    # Return updated ticket list
    tickets = db.query(Ticket).filter(or_(Ticket.creator_id == user_id, Ticket.assignee_id == user_id)).order_by(Ticket.created_at.desc()).all()
    db.close()
    html = ""
    for t in tickets:
        status_label = t.status.lower().replace('_', ' ')
        if t.status == 'OPEN':
            status_color = 'green-600'
        elif t.status == 'IN_PROGRESS':
            status_color = 'orange-500'
        elif t.status == 'WAITING_USER':
            status_color = 'blue-600'
        else:
            status_color = 'red-500'
        card_bg = 'bg-white'
        card_border = 'border-l-4 border-blue-400'
        card_hover = 'hover:bg-blue-50'
        if t.priority in ['HIGH', 'CRITICAL']:
            card_bg = 'bg-red-100'
            card_border = 'border-l-4 border-red-600 animate-pulse'
            card_hover = 'hover:bg-red-200'
        html += f'''<div class="p-4 {card_bg} rounded shadow cursor-pointer {card_hover} {card_border}"
            hx-get="/dashboard/chat/{t.id}" hx-target="#main-area" hx-swap="innerHTML">
            <div class="flex items-center justify-between">
                <span class="font-semibold truncate w-40">{t.title}</span>
                <span class="text-xs bg-orange-100 text-orange-700 px-2 py-1 rounded">{t.priority.lower()}</span>
            </div>
            <div class="text-xs text-gray-500 truncate">{t.description}</div>
            <div class="flex items-center gap-2 mt-1">
                <span class="text-{status_color} text-xs font-bold">{status_label}</span>
                <span class="text-xs text-gray-400">• {t.created_at.strftime('%I:%M %p')}</span>
            </div>
        </div>'''
    if not tickets:
        html = '<div class="text-gray-400 text-center">No tickets found.</div>'
    return HTMLResponse(html)

@app.get("/users/search", response_class=HTMLResponse)
def user_search(request: Request):
    q = request.query_params.get("assignee_search") or request.query_params.get("q") or ""
    db = SessionLocal()
    if q:
        users = db.query(User).filter(User.name.ilike(f"%{q}%")).limit(10).all()
    else:
        users = db.query(User).limit(50).all()  # Show all users if no search
    db.close()
    options = "".join([f'<option value="{u.id}">{u.name} ({u.email})</option>' for u in users])
    return HTMLResponse(options)

@app.post("/dashboard/ticket/{ticket_id}/close", response_class=HTMLResponse)
def close_ticket(ticket_id: int, request: Request, access_token: str = Cookie(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    payload = decode_access_token(access_token)
    if not payload or "sub" not in payload:
        db.close()
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    user_id = int(payload["sub"])
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket or (ticket.creator_id != user_id and ticket.assignee_id != user_id):
        db.close()
        return HTMLResponse("<div>Not authorized</div>", status_code=403)
    ticket.status = "CLOSED"
    db.commit()
    db.close()
    # Return updated chat area
    return dashboard_chat(ticket_id, request, access_token)

@app.get("/dashboard/chat/user/{friend_id}", response_class=HTMLResponse)
def dashboard_user_chat(friend_id: int, request: Request, access_token: str = Cookie(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    payload = decode_access_token(access_token)
    if not payload or "sub" not in payload:
        db.close()
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    user_id = int(payload["sub"])
    if user_id == friend_id:
        db.close()
        return HTMLResponse("<div>Cannot chat with yourself</div>", status_code=400)
    # Check if they are friends
    from app.models.user import User, UserContact
    contact = db.query(UserContact).filter(
        ((UserContact.user1_id == user_id) & (UserContact.user2_id == friend_id)) |
        ((UserContact.user1_id == friend_id) & (UserContact.user2_id == user_id))
    ).first()
    if not contact:
        db.close()
        return HTMLResponse("<div>You are not friends with this user.</div>", status_code=403)
    # Get friend user
    friend = db.query(User).filter(User.id == friend_id).first()
    if not friend:
        db.close()
        return HTMLResponse("<div>User not found</div>", status_code=404)
    # Get messages between the two users (direct chat)
    from app.models.message import Message
    messages = db.query(Message).filter(
        ((Message.sender_id == user_id) & (Message.receiver_id == friend_id)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == user_id))
    ).order_by(Message.timestamp).all()
    db.close()
    # Build chat UI
    chat_header = f"""
      <div class='flex-none flex items-center gap-3 px-4 py-3 border-b bg-gradient-to-r from-green-600 to-green-400 rounded-t-lg sticky top-0 z-10 relative'>
        <div class='w-10 h-10 rounded-full bg-white flex items-center justify-center text-green-700 font-bold text-lg shadow'>
          <img src='https://ui-avatars.com/api/?name={friend.name}&background=43B581&color=fff' class='w-10 h-10 rounded-full' />
        </div>
        <div class='flex flex-col flex-1'>
          <span class='text-white font-semibold'>{friend.name}</span>
          <span class='text-green-100 text-xs'>{friend.email}</span>
        </div>
      </div>
    """
    html = f"""
    <div id='main-area' class='flex flex-col w-full max-w-2xl mx-auto bg-white rounded-lg shadow-lg border border-gray-200 h-full min-h-0'>
    {chat_header}
      <div id='chat-area' data-friend-id='{friend_id}' data-user-id='{user_id}' data-token='{access_token}' class='flex flex-col flex-1 h-full w-full min-h-0'>
        <div id='chat-messages' class='flex-1 overflow-y-auto p-4 space-y-2 bg-gray-50 min-h-0' style='min-height:0;'>
    """
    for m in messages:
        is_me = m.sender_id == user_id
        align = "justify-end" if is_me else "justify-start"
        bubble = "bg-green-500 text-white" if is_me else "bg-white text-gray-900 border border-gray-200"
        tail = "rounded-br-2xl rounded-tl-2xl rounded-bl-md" if is_me else "rounded-bl-2xl rounded-tr-2xl rounded-br-md"
        avatar_url = f"https://ui-avatars.com/api/?name={'You' if is_me else friend.name}&background=43B581&color=fff"
        sender_name = 'You' if is_me else friend.name
        html += f"""
        <div class='flex {align} items-end gap-2'>
          {"" if is_me else f"<div class='w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center'><img src='{avatar_url}' class='w-8 h-8 rounded-full'/></div>"}
          <div class='rounded-2xl px-4 py-2 {bubble} {tail} max-w-xs shadow text-sm'>
            <div class='font-semibold text-xs mb-1'>{sender_name}</div>
            <div>{m.content}</div>
            <div class='text-xs text-right text-gray-400 mt-1'>{m.timestamp.strftime('%I:%M %p')}</div>
          </div>
          {"<div class='w-8 h-8'></div>" if is_me else ''}
        </div>
        """
    html += """
        </div>
        <form id='send-message-form' class='flex items-center gap-2 p-4 border-t bg-white' hx-post='/dashboard/chat/user/{friend_id}/send' hx-target='#main-area' hx-swap='outerHTML'>
          <input type='hidden' name='friend_id' value='{friend_id}' />
          <input type='text' name='content' class='flex-1 px-4 py-2 border rounded-full focus:outline-none focus:ring-2 focus:ring-green-500' placeholder='Type a message...' required />
          <button type='submit' class='bg-green-600 text-white px-4 py-2 rounded-full font-semibold hover:bg-green-700'>Send</button>
        </form>
      </div>
    </div>
    """
    return HTMLResponse(html)

@app.post("/dashboard/chat/user/{friend_id}/send", response_class=HTMLResponse)
def dashboard_user_send_message(friend_id: int, request: Request, content: str = Form(...), access_token: str = Cookie(None)):
    if not access_token:
        return HTMLResponse("<div>Please log in</div>", status_code=401)
    db = SessionLocal()
    payload = decode_access_token(access_token)
    if not payload or "sub" not in payload:
        db.close()
        return HTMLResponse("<div>Invalid token</div>", status_code=401)
    user_id = int(payload["sub"])
    if user_id == friend_id:
        db.close()
        return HTMLResponse("<div>Cannot chat with yourself</div>", status_code=400)
    # Check if they are friends
    from app.models.user import UserContact
    contact = db.query(UserContact).filter(
        ((UserContact.user1_id == user_id) & (UserContact.user2_id == friend_id)) |
        ((UserContact.user1_id == friend_id) & (UserContact.user2_id == user_id))
    ).first()
    if not contact:
        db.close()
        return HTMLResponse("<div>You are not friends with this user.</div>", status_code=403)
    # Save the message
    from app.models.message import Message
    db_message = Message(sender_id=user_id, receiver_id=friend_id, content=content)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    db.close()
    # Reload chat area into #main-area
    return dashboard_user_chat(friend_id, request, access_token) 