from fastapi import FastAPI, Request, Depends, HTTPException, status, Form
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncpg
import secrets
from datetime import datetime, timedelta
import random
from typing import Optional,List
from passlib.context import CryptContext
from database import get_connection
from fastapi import UploadFile, File
import os
from pathlib import Path
import json
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_DIR = BASE_DIR / "static" / "images"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


ADMIN_USERNAME = "admin@eventsystem.com"
ADMIN_PASSWORD = "admin123"
ADMIN_EMAIL = "admin@eventsystem.com"
ADMIN_NAME = "Администратор Системы"


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


password_reset_tokens = {}

security = HTTPBearer()


async def get_current_user_role(request: Request):
    """Получаем текущего пользователя и его роли"""
    current_user = await get_current_user(request)
    conn = await get_connection()
    try:
        roles = await conn.fetch(
            "SELECT r.name FROM roles r JOIN user_roles ur ON r.id = ur.role_id WHERE ur.user_id = $1",
            current_user['id']
        )
        return {"user": current_user, "roles": [r['name'] for r in roles]}
    finally:
        await conn.close()
        
def role_required(required_roles: list):
    async def _role_checker(request: Request):
        """Фабрика зависимостей для проверки ролей"""
        user_data = await get_current_user_role(request)
        user_roles = user_data["roles"]
        
        if 'Администратор' in user_roles:
            return user_data
        
        if not any(role in user_roles for role in required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия"
            )
        
        return user_data
    return _role_checker

def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str):
    return pwd_context.hash(password)

async def create_admin_user():
    """Создание администратора при первом запуске"""
    conn = await get_connection()
    try:
        admin = await conn.fetchrow(
            "SELECT * FROM users WHERE username = $1", ADMIN_USERNAME
        )
        if not admin:
            admin_id = await conn.fetchval(
                "INSERT INTO users (username, password_hash, full_name, email) VALUES ($1, $2, $3, $4) RETURNING id",
                ADMIN_USERNAME, get_password_hash(ADMIN_PASSWORD), ADMIN_NAME, ADMIN_EMAIL
            )
            
            await conn.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES ($1, (SELECT id FROM roles WHERE name = 'Администратор'))",
                admin_id
            )
    finally:
        await conn.close()

async def get_upcoming_events(conn):
    """Получение предстоящих мероприятий из БД"""
    try:
        return await conn.fetch(
            "SELECT e.id, e.name, e.description, e.start_time, e.end_time, e.max_participants, "
            "r.name as room_name, et.name as event_type_name "
            "FROM events e "
            "LEFT JOIN resource_bookings rb ON rb.event_id = e.id AND rb.resource_type = 'room' "
            "LEFT JOIN rooms r ON r.id = rb.resource_id "
            "LEFT JOIN event_types et ON et.id = e.event_type_id "
            "WHERE e.start_time > now() "
            "ORDER BY e.start_time LIMIT 3"
        )
    except Exception as e:
        print(f"Ошибка получения мероприятий: {e}")
        return []
    
async def get_current_user(request: Request):
    """Получение текущего пользователя из сессии"""
    session_token = request.cookies.get("session_token")
    print(f"Получен session_token из cookie: {session_token}")
    
    if not session_token:
        print("Сессионный токен отсутствует")
        raise HTTPException(
            status_code=303,
            detail="Not authenticated",
            headers={"Location": "/unregistered"}
        )
    
    conn = await get_connection()
    try:
        user = await conn.fetchrow(
            "SELECT u.id, u.username, u.full_name, u.email FROM users u "
            "JOIN user_sessions us ON u.id = us.user_id "
            "WHERE us.session_token = $1 AND us.expires_at > NOW()",
            session_token
        )
        
        if not user:
            print(f"Сессия не найдена или истекла: {session_token}")
            raise HTTPException(
            status_code=303,
            detail="Not authenticated",
            headers={"Location": "/unregistered"}
        )
            
        print(f"Пользователь найден: {user['username']}")
        return dict(user)
    finally:
        await conn.close()

@app.on_event("startup")
async def startup():
    """Создание таблицы сессий и администратора при запуске"""
    conn = await get_connection()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                session_token TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT NOW(),
                expires_at TIMESTAMP NOT NULL
            )
        """)
        print("Таблица user_sessions создана/проверена")
        await create_admin_user()
    except Exception as e:
        print(f"Ошибка при создании таблицы сессий: {e}")
        raise
    finally:
        await conn.close()

@app.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember: bool = Form(False)
):
    """Обработка входа в систему"""
    print(f"Попытка входа: {username}")
    
    conn = await get_connection()
    try:
        user = await conn.fetchrow(
            "SELECT id, username, password_hash, full_name, email FROM users WHERE username = $1", 
            username
        )
        
        if not user:
            print(f"Пользователь {username} не найден")
            return templates.TemplateResponse(
                "unregistered.html",
                {
                    "request": request,
                    "error": "Пользователь не найден",
                    "show_login_modal": True,
                    "admin_username": ADMIN_USERNAME,
                    "admin_password": ADMIN_PASSWORD
                },
                status_code=401
            )
        
        if not verify_password(password, user["password_hash"]):
            print(f"Неверный пароль для пользователя {username}")
            return templates.TemplateResponse(
                "unregistered.html",
                {
                    "request": request,
                    "error": "Неверный пароль",
                    "show_login_modal": True,
                    "admin_username": ADMIN_USERNAME,
                    "admin_password": ADMIN_PASSWORD
                },
                status_code=401
            )
        
        print(f"Успешная аутентификация для пользователя {username}")
        
        session_token = secrets.token_hex(32)
        expires_at = datetime.now() + timedelta(days=7 if remember else 1)
        
        await conn.execute(
            "INSERT INTO user_sessions (user_id, session_token, expires_at) VALUES ($1, $2, $3)",
            user["id"],
            session_token,
            expires_at
        )
        
        print(f"Сессия создана для user_id: {user['id']}")
        
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key="session_token",
            value=session_token,
            max_age=3600*24*7 if remember else None,
            httponly=True,
            secure=False
        )
        
        print(f"Cookie установлен: {session_token}")
        return response
        
    except Exception as e:
        print(f"Ошибка входа: {e}")
        return templates.TemplateResponse(
            "unregistered.html",
            {
                "request": request,
                "error": f"Ошибка сервера при входе: {str(e)}",
                "show_login_modal": True,
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            },
            status_code=500
        )
    finally:
        await conn.close()

@app.post("/forgot-password")
async def forgot_password(request: Request, email: str = Form(...)):
    """Обработка запроса на восстановление пароля"""
    conn = await get_connection()
    try:
        user = await conn.fetchrow(
            "SELECT id, full_name FROM users WHERE email = $1", 
            email
        )
        
        if user:
            token = secrets.token_urlsafe(32)
            password_reset_tokens[token] = {
                "user_id": user["id"],
                "expires": datetime.now() + timedelta(hours=1)
            }
            
            
            print(f"\n=== Ссылка для сброса пароля ===\n"
                  f"Для пользователя: {user['full_name']}\n"
                  f"Ссылка: http://127.0.0.1:8000/reset-password?token={token}\n"
                  f"Действительна до: {password_reset_tokens[token]['expires']}\n")
            
            return templates.TemplateResponse(
                "unregistered.html",
                {
                    "request": request,
                    "message": f"Инструкции по сбросу пароля отправлены на {email}",
                    "admin_username": ADMIN_USERNAME,
                    "admin_password": ADMIN_PASSWORD
                }
            )
        else:
            return templates.TemplateResponse(
                "unregistered.html",
                {
                    "request": request,
                    "error": "Пользователь с таким email не найден",
                    "admin_username": ADMIN_USERNAME,
                    "admin_password": ADMIN_PASSWORD
                },
                status_code=404
            )
    except Exception as e:
        print(f"Ошибка восстановления пароля: {e}")
        return templates.TemplateResponse(
            "unregistered.html",
            {
                "request": request,
                "error": "Ошибка сервера при обработке запроса",
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            },
            status_code=500
        )
    finally:
        await conn.close()

@app.get("/reset-password")
async def reset_password_form(request: Request, token: str):
    """Форма для сброса пароля"""
    if token not in password_reset_tokens:
        return templates.TemplateResponse(
            "unregistered.html",
            {
                "request": request,
                "error": "Недействительная или устаревшая ссылка",
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            },
            status_code=400
        )
    
    if datetime.now() > password_reset_tokens[token]["expires"]:
        del password_reset_tokens[token]
        return templates.TemplateResponse(
            "unregistered.html",
            {
                "request": request,
                "error": "Срок действия ссылки истек",
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            },
            status_code=400
        )
    
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "token": token,
            "admin_username": ADMIN_USERNAME,
            "admin_password": ADMIN_PASSWORD
        }
    )

@app.post("/reset-password")
async def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...)
):
    """Обработка сброса пароля"""
    if new_password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "token": token,
                "error": "Пароли не совпадают",
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            },
            status_code=400
        )
    
    if token not in password_reset_tokens:
        return templates.TemplateResponse(
            "unregistered.html",
            {
                "request": request,
                "error": "Недействительная или устаревшая ссылка",
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            },
            status_code=400
        )
    
    if datetime.now() > password_reset_tokens[token]["expires"]:
        del password_reset_tokens[token]
        return templates.TemplateResponse(
            "unregistered.html",
            {
                "request": request,
                "error": "Срок действия ссылки истек",
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            },
            status_code=400
        )
    
    user_id = password_reset_tokens[token]["user_id"]
    del password_reset_tokens[token]
    
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE users SET password_hash = $1 WHERE id = $2",
            get_password_hash(new_password),
            user_id
        )
        
        return templates.TemplateResponse(
            "unregistered.html",
            {
                "request": request,
                "message": "Пароль успешно изменен. Теперь вы можете войти.",
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            }
        )
    except Exception as e:
        print(f"Ошибка сброса пароля: {e}")
        return templates.TemplateResponse(
            "unregistered.html",
            {
                "request": request,
                "error": "Ошибка сервера при сбросе пароля",
                "admin_username": ADMIN_USERNAME,
                "admin_password": ADMIN_PASSWORD
            },
            status_code=500
        )
    finally:
        await conn.close()

@app.get("/logout")
async def logout():
    """Выход из системы"""
    response = RedirectResponse(url="/unregistered")
    response.delete_cookie("session_token")
    return response

@app.get("/", response_class=HTMLResponse)
async def root(
    request: Request,
    user_data: dict = Depends(role_required(['Пользователь', 'Сотрудник', 'Организатор', 'Администратор']))
):
    """Главная страница для авторизованных пользователей"""
    try:
        
        current_user = await get_current_user(request)
        
        conn = await get_connection()
        roles = await conn.fetch(
            "SELECT r.name FROM roles r JOIN user_roles ur ON r.id = ur.role_id WHERE ur.user_id = $1",
            current_user['id']
        )
        user_roles = [r['name'] for r in roles]
        current_user['roles'] = user_roles
        
        conn = await get_connection()
        events = await get_upcoming_events(conn)
        
        formatted_events = []
        for e in events:
            formatted_events.append({
                "id": e["id"],
                "name": e["name"],
                "description": e["description"],
                "start_time": e["start_time"],
                "end_time": e["end_time"],
                "max_participants": e["max_participants"],
                "room": {"name": e.get("room_name")},
                "event_type": {"name": e.get("event_type_name")}
            })
        
        return templates.TemplateResponse(
            "registered.html",
            {
                "request": request,
                "current_user": current_user,
                "upcoming_events": formatted_events
            }
        )
    except HTTPException as e:
        if e.status_code == 303:
            return RedirectResponse(url="/unregistered")
        raise
    except Exception as e:
        print(f"Ошибка загрузки главной страницы: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка загрузки данных"},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()
        
@app.get("/activity")
async def activity(
    request: Request,
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    """Страница отчетов о деятельности организации"""
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        
        conn = await get_connection()
        try:
            events = await conn.fetch("SELECT id, name FROM events ORDER BY name")
            rooms = await conn.fetch("SELECT id, name FROM rooms ORDER BY name")
            employees = await conn.fetch("SELECT id, full_name FROM employees ORDER BY full_name")
            age_categories = await conn.fetch("SELECT id, name FROM age_categories ORDER BY name")
            event_statuses = await conn.fetch("SELECT id, name FROM event_statuses ORDER BY name")
        finally:
            await conn.close()
        
        return templates.TemplateResponse(
            "activity.html",
            {
                "request": request,
                "current_user": current_user,
                "events": events,
                "rooms": rooms,
                "employees": employees,
                "age_categories": age_categories,
                "event_statuses": event_statuses
            }
        )
    except HTTPException as e:
        if e.status_code == 303:
            return RedirectResponse(url="/unregistered")
        raise
    except Exception as e:
        print(f"Ошибка загрузки страницы деятельности: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка загрузки данных"},
            status_code=500
        )
        
@app.post("/api/activity/report")
async def generate_activity_report(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    event_id: Optional[str] = Form(None),
    filter_type: Optional[str] = Form(None),
    filter_value: Optional[str] = Form(None),
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    """Генерация отчета о деятельности"""
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        try:
            if 'T' in start_date:
                start_datetime = datetime.fromisoformat(start_date.replace('T', ' '))
                end_datetime = datetime.fromisoformat(end_date.replace('T', ' '))
            else:
                start_datetime = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S")
                end_datetime = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            return {"success": False, "error": f"Неверный формат даты: {str(e)}. Попробуйте иначе."}
        
        query = """
            SELECT 
                e.id, e.name, e.description, 
                e.start_time, e.end_time, e.max_participants,
                r.name as room_name, et.name as event_type_name,
                ac.name as age_category_name, es.name as status_name
            FROM events e
            LEFT JOIN resource_bookings rb ON rb.event_id = e.id AND rb.resource_type = 'room'
            LEFT JOIN rooms r ON r.id = rb.resource_id
            LEFT JOIN event_types et ON et.id = e.event_type_id
            LEFT JOIN age_categories ac ON ac.id = e.min_age_category_id
            LEFT JOIN event_statuses es ON es.id = e.status_id
            WHERE e.start_time >= $1 AND e.end_time <= $2
        """
        params = [start_datetime, end_datetime]
        
        
        if event_id and event_id != "all":
            query += " AND e.id = $3"
            params.append(int(event_id))  
        
        if filter_type and filter_value and filter_value != "all":
            param_position = len(params) + 1
            
            if filter_type == "room":
                query += f" AND r.id = ${param_position}"
                params.append(int(filter_value))  
            elif filter_type == "employees":
                query += f"""
                    AND EXISTS (
                        SELECT 1 FROM resource_bookings rb2 
                        WHERE rb2.event_id = e.id 
                        AND rb2.resource_type = 'employee' 
                        AND rb2.resource_id = ${param_position}
                    )
                """
                params.append(int(filter_value))  
            elif filter_type == "participants":
                query += f" AND e.max_participants >= ${param_position}"
                params.append(int(filter_value))  
            elif filter_type == "age":
                query += f" AND e.min_age_category_id = ${param_position}"
                params.append(int(filter_value))  
            elif filter_type == "status":
                query += f" AND e.status_id = ${param_position}"
                params.append(int(filter_value))  
        
        query += " ORDER BY e.start_time"
        
        events = await conn.fetch(query, *params)
        
        report_data = []
        for event in events:
            report_data.append({
                "id": event["id"],
                "name": event["name"],
                "start_date": event["start_time"].isoformat(), 
                "end_date": event["end_time"].isoformat(),    
                "status": event["status_name"],
                "age_category": event["age_category_name"],
                "participants": event["max_participants"],
                "event_type": event["event_type_name"],
                "room": event["room_name"]
            })
        
        return {"success": True, "data": report_data}
        
    except Exception as e:
        print(f"Ошибка генерации отчета: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if 'conn' in locals():
            await conn.close()
            
@app.get("/profile")
async def profile(
    request: Request,
    user_data: dict = Depends(role_required(['Пользователь', 'Сотрудник', 'Организатор', 'Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        
        stats = await conn.fetchrow(
            """SELECT 
                  COUNT(DISTINCT e.id) FILTER (WHERE e.organizer_id = $1) AS organized_events,
                  COUNT(DISTINCT ep.event_id) AS participated_events
               FROM users u
               LEFT JOIN events e ON e.organizer_id = u.id
               LEFT JOIN event_participants ep ON ep.user_id = u.id
               WHERE u.id = $1""",
            current_user['id']
        )
        
        
        recent_events = await conn.fetch(
            """SELECT e.id, e.name, e.description, e.start_time, r.name as room_name
               FROM events e
               LEFT JOIN resource_bookings rb ON rb.event_id = e.id AND rb.resource_type = 'room'
               LEFT JOIN rooms r ON r.id = rb.resource_id
               WHERE e.organizer_id = $1
               ORDER BY e.start_time DESC LIMIT 5""",
            current_user['id']
        )
        
        
        roles = await conn.fetch(
            "SELECT r.name FROM roles r JOIN user_roles ur ON r.id = ur.role_id WHERE ur.user_id = $1",
            current_user['id']
        )
        
        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "current_user": current_user,
                "organized_events": stats['organized_events'],
                "participated_events": stats['participated_events'],
                "recent_events": recent_events,
                "user_roles": [r['name'] for r in roles]
            }
        )
    except HTTPException as e:
        if e.status_code == 303:
            return RedirectResponse(url="/unregistered")
        raise
    except Exception as e:
        print(f"Error loading profile: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка загрузки профиля"},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()

@app.post("/profile/update")
async def update_profile(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    user_data: dict = Depends(role_required(['Пользователь', 'Сотрудник', 'Организатор', 'Администратор']))
):
    """Обновление данных профиля"""
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        await conn.execute(
            "UPDATE users SET full_name = $1, email = $2 WHERE id = $3",
            full_name, email, current_user['id']
        )
        
        return RedirectResponse(url="/profile", status_code=303)
        
    except Exception as e:
        print(f"Error updating profile: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка при обновлении профиля"},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()

@app.post("/profile/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user_data: dict = Depends(role_required(['Пользователь', 'Сотрудник', 'Организатор', 'Администратор']))
):
    """Смена пароля пользователя"""
    try:
        if new_password != confirm_password:
            raise HTTPException(status_code=400, detail="Новый пароль и подтверждение не совпадают")
        
        if len(new_password) < 8:
            raise HTTPException(status_code=400, detail="Пароль должен содержать не менее 8 символов")
        
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        
        user = await conn.fetchrow(
            "SELECT password_hash FROM users WHERE id = $1",
            current_user['id']
        )
        
        if not verify_password(current_password, user['password_hash']):
            raise HTTPException(status_code=400, detail="Неверный текущий пароль")
        
        
        await conn.execute(
            "UPDATE users SET password_hash = $1 WHERE id = $2",
            get_password_hash(new_password),
            current_user['id']
        )
        
        return RedirectResponse(url="/profile", status_code=303)
        
    except HTTPException as e:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": str(e.detail)},
            status_code=e.status_code
        )
    except Exception as e:
        print(f"Error changing password: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка при смене пароля"},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()

@app.post("/events/{event_id}/update")
async def update_event(
    request: Request,
    event_id: int,
    name: str = Form(...),
    description: str = Form(...),
    event_type_id: int = Form(...),
    status_id: int = Form(...),
    room_id: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    min_age_category_id: Optional[int] = Form(None),
    max_participants: int = Form(...),
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        
        event = await conn.fetchrow("SELECT id FROM events WHERE id = $1", event_id)
        if not event:
            raise HTTPException(status_code=404, detail="Мероприятие не найдено")
        
        
        room = await conn.fetchrow("SELECT id FROM rooms WHERE id = $1", room_id)
        if not room:
            raise HTTPException(status_code=400, detail="Выбранное помещение не найдено")
        
        
        start_datetime = datetime.fromisoformat(start_time)
        end_datetime = datetime.fromisoformat(end_time)
        
        
        if end_datetime <= start_datetime:
            raise HTTPException(status_code=400, detail="Дата окончания должна быть позже даты начала")
        
        
        await conn.execute(
            """UPDATE events SET
                  name = $1,
                  description = $2,
                  event_type_id = $3,
                  status_id = $4,
                  start_time = $5,
                  end_time = $6,
                  min_age_category_id = $7,
                  max_participants = $8
               WHERE id = $9""",
            name, description, event_type_id, status_id,
            start_datetime, end_datetime, min_age_category_id,
            max_participants, event_id
        )
        
        
        await conn.execute(
            """UPDATE resource_bookings SET
                  resource_id = $1,
                  start_time = $2,
                  end_time = $3
               WHERE event_id = $4 AND resource_type = 'room'""",
            room_id, start_datetime, end_datetime, event_id
        )
        
        return RedirectResponse(url=f"/events/{event_id}", status_code=303)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating event: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка при обновлении мероприятия"},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()

@app.post("/events/{event_id}/participants")
async def add_event_participants(
    request: Request,
    event_id: int,
    employee_ids: List[int] = Form(...),
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        
        event = await conn.fetchrow(
            "SELECT start_time, end_time FROM events WHERE id = $1", 
            event_id
        )
        
        if not event:
            raise HTTPException(status_code=404, detail="Мероприятие не найдено")
        
        
        for employee_id in employee_ids:
            await conn.execute(
                """INSERT INTO resource_bookings 
                   (event_id, resource_type, resource_id, start_time, end_time)
                   VALUES ($1, 'employee', $2, $3, $4)
                   ON CONFLICT DO NOTHING""",
                event_id, employee_id, event['start_time'], event['end_time']
            )
        
        return RedirectResponse(url=f"/events/{event_id}", status_code=303)
        
    except Exception as e:
        print(f"Error adding participants: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка при добавлении участников"},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()

@app.delete("/events/{event_id}/participants/{employee_id}")
async def remove_event_participant(
    request: Request,
    event_id: int,
    employee_id: int,
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        
        await conn.execute(
            """DELETE FROM resource_bookings 
               WHERE event_id = $1 AND resource_type = 'employee' AND resource_id = $2""",
            event_id, employee_id
        )
        
        return JSONResponse({"success": True})
        
    except Exception as e:
        print(f"Error removing participant: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    finally:
        if 'conn' in locals():
            await conn.close()

@app.get("/employees")
async def employees(
    request: Request,
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        employees = await conn.fetch("SELECT * FROM employees ORDER BY full_name")
        
        return templates.TemplateResponse(
            "rooms.html",  
            {
                "request": request,
                "current_user": current_user,
                "employees": employees,
                "rooms": [],  
                "room_types": []  
            }
        )
    except HTTPException:
        return RedirectResponse(url="/unregistered")
    finally:
        await conn.close()

@app.delete("/employees/{employee_id}")
async def delete_employee(
    request: Request, 
    employee_id: int,
    user_data: dict = Depends(role_required(['Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        await conn.execute("DELETE FROM employees WHERE id = $1", employee_id)
        
        return JSONResponse({"success": True})
    except Exception as e:
        print(f"Error deleting employee: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    finally:
        await conn.close()

@app.get("/events")
async def events(
    request: Request,
    date: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    show_modal: Optional[bool] = False,
    user_data: dict = Depends(role_required(['Пользователь', 'Сотрудник', 'Организатор', 'Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        
        rooms = await conn.fetch("SELECT * FROM rooms ORDER BY name")
        age_categories = await conn.fetch("SELECT * FROM age_categories ORDER BY name")
        employees = await conn.fetch("SELECT * FROM employees ORDER BY full_name")
        
        
        query = """
            SELECT 
                e.id, e.name, e.description, e.start_time, e.end_time, e.max_participants,
                r.name as room_name, et.name as event_type_name, 
                ac.name as age_category_name, es.name as status_name
            FROM events e
            LEFT JOIN resource_bookings rb ON rb.event_id = e.id AND rb.resource_type = 'room'
            LEFT JOIN rooms r ON r.id = rb.resource_id
            LEFT JOIN event_types et ON et.id = e.event_type_id
            LEFT JOIN age_categories ac ON ac.id = e.min_age_category_id
            LEFT JOIN event_statuses es ON es.id = e.status_id
            WHERE 1=1
        """
        
        params = []
        
        if date:
            try:
                date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                query += " AND DATE(e.start_time) <= $1 AND DATE(e.end_time) >= $1"
                params.append(date_obj)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
        
        if event_type and event_type.strip():
            query += f" AND e.event_type_id = ${len(params)+1}"
            params.append(int(event_type))  
        
        
        if status and status.strip():
            query += f" AND e.status_id = ${len(params)+1}"
            params.append(int(status))  
        
        query += " ORDER BY e.start_time"
        
        events = await conn.fetch(query, *params)
        
        
        event_types = await conn.fetch("SELECT * FROM event_types ORDER BY name")
        event_statuses = await conn.fetch("SELECT * FROM event_statuses ORDER BY name")
        
        return templates.TemplateResponse(
            "events.html",
            {
                "request": request,
                "current_user": current_user,
                "events": events,
                "event_types": event_types,
                "event_statuses": event_statuses,
                "rooms": rooms,
                "age_categories": age_categories,
                "employees": employees,
                "show_create_modal": show_modal
            }
        )
    except HTTPException:
        return RedirectResponse(url="/unregistered")
    finally:
        if 'conn' in locals():
            await conn.close()

@app.post("/rooms/{room_id}/update")
async def update_room(
    request: Request,
    room_id: int,
    name: str = Form(...),
    room_type_id: int = Form(...),
    capacity: int = Form(...),
    address: str = Form(...),
    description: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    is_external: bool = Form(False),
    external_url: Optional[str] = Form(None),
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    """Обновление данных помещения"""
    image_filename = None
    
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()
        
        room = await conn.fetchrow("SELECT * FROM rooms WHERE id = $1", room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Помещение не найдено")
        
        room_type = await conn.fetchrow("SELECT id FROM room_types WHERE id = $1", room_type_id)
        if not room_type:
            raise HTTPException(status_code=400, detail="Неверный тип помещения")
        
        if image and image.filename:
            if room['image_filename']:
                old_image_path = UPLOAD_DIR / room['image_filename']
                if old_image_path.exists():
                    old_image_path.unlink()
            
            file_ext = os.path.splitext(image.filename)[1]
            image_filename = f"room_{secrets.token_hex(8)}{file_ext}"
            file_path = UPLOAD_DIR / image_filename
            with file_path.open("wb") as buffer:
                buffer.write(await image.read())
        
        if image_filename:
            await conn.execute(
                """UPDATE rooms SET 
                    name = $1, room_type_id = $2, capacity = $3, address = $4, 
                    description = $5, is_external = $6, external_url = $7,
                    image_filename = $8
                   WHERE id = $9""",
                name, room_type_id, capacity, address, description, 
                is_external, external_url, image_filename, room_id
            )
        else:
            await conn.execute(
                """UPDATE rooms SET 
                    name = $1, room_type_id = $2, capacity = $3, address = $4, 
                    description = $5, is_external = $6, external_url = $7
                   WHERE id = $8""",
                name, room_type_id, capacity, address, description, 
                is_external, external_url, room_id
            )
        
        return RedirectResponse(url=f"/rooms/{room_id}", status_code=303)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error updating room: {e}")
        if image_filename and (UPLOAD_DIR / image_filename).exists():
            (UPLOAD_DIR / image_filename).unlink()
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка при обновлении помещения"},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()
            
@app.get("/events/create", name="create_event")
async def create_event_form(
    request: Request,
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        
        conn = await get_connection()
        
        event_types = await conn.fetch("SELECT * FROM event_types ORDER BY name")
        rooms = await conn.fetch("SELECT * FROM rooms ORDER BY name")
        age_categories = await conn.fetch("SELECT * FROM age_categories ORDER BY name")
        employees = await conn.fetch("SELECT * FROM employees ORDER BY full_name")
        
        return templates.TemplateResponse(
            "create_event.html",
            {
                "request": request,
                "current_user": current_user,
                "event_types": event_types,
                "rooms": rooms,
                "age_categories": age_categories,
                "employees": employees
            }
        )
    except HTTPException:
        return RedirectResponse(url="/unregistered")
    finally:
        if 'conn' in locals():
            await conn.close()
            
@app.delete("/events/{event_id}")
async def delete_event(request: Request, event_id: int):
    try:
        conn = await get_connection()
        
        
        await conn.execute(
            "DELETE FROM resource_bookings WHERE event_id = $1",
            event_id
        )
        
        
        await conn.execute(
            "DELETE FROM events WHERE id = $1",
            event_id
        )
        
        return JSONResponse({"success": True})
        
    except Exception as e:
        print(f"Error deleting event: {e}")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()
                        
@app.post("/events/create")
async def create_event(
    request: Request,
    name: str = Form(...),
    description: str = Form(...),
    event_type_id: int = Form(...),
    room_id: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    min_age_category_id: Optional[int] = Form(None),
    max_participants: int = Form(...),
    employee_ids: List[int] = Form([]),
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    """Добавление помещения (внутреннего или внешнего)"""
    try:
        conn = await get_connection()
        
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        start_datetime = datetime.fromisoformat(start_time)
        end_datetime = datetime.fromisoformat(end_time)
        
        
        if end_datetime <= start_datetime:
            raise HTTPException(
                status_code=400,
                detail="Дата окончания должна быть позже даты начала"
            )
        
        
        event_types = await conn.fetch("SELECT * FROM event_types ORDER BY name")
        rooms = await conn.fetch("SELECT * FROM rooms ORDER BY name")
        age_categories = await conn.fetch("SELECT * FROM age_categories ORDER BY name")
        employees = await conn.fetch("SELECT * FROM employees ORDER BY full_name")
        
        
        event = await conn.fetchrow(
            """INSERT INTO events 
               (name, description, start_time, end_time, max_participants, 
                min_age_category_id, event_type_id, organizer_id, status_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 
                      (SELECT id FROM event_statuses WHERE name = 'Запланировано'))
               RETURNING id""",
            name, description, start_datetime, end_datetime, max_participants,
            min_age_category_id, event_type_id, current_user['id']
        )
        
        
        await conn.execute(
            """INSERT INTO resource_bookings 
               (event_id, resource_type, resource_id, start_time, end_time)
               VALUES ($1, 'room', $2, $3, $4)""",
            event['id'], room_id, start_datetime, end_datetime
        )
        
        
        for employee_id in employee_ids:
            await conn.execute(
                """INSERT INTO resource_bookings 
                   (event_id, resource_type, resource_id, start_time, end_time)
                   VALUES ($1, 'employee', $2, $3, $4)""",
                event['id'], employee_id, start_datetime, end_datetime
            )
        
        return RedirectResponse(url=f"/events/{event['id']}", status_code=303)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating event: {e}")
        
        if 'event_types' not in locals():
            conn = await get_connection()
            event_types = await conn.fetch("SELECT * FROM event_types ORDER BY name")
            rooms = await conn.fetch("SELECT * FROM rooms ORDER BY name")
            age_categories = await conn.fetch("SELECT * FROM age_categories ORDER BY name")
            employees = await conn.fetch("SELECT * FROM employees ORDER BY full_name")
            await conn.close()
            
        return templates.TemplateResponse(
            "create_event.html",
            {
                "request": request,
                "error": "Ошибка при создании мероприятия",
                "current_user": current_user,
                "event_types": event_types,
                "rooms": rooms,
                "age_categories": age_categories,
                "employees": employees
            },
            status_code=400
        )
    finally:
        if 'conn' in locals():
            await conn.close()
            
@app.get("/events/{event_id}", name="event_details")
async def event_details(
    request: Request,  # Добавляем request как первый параметр
    event_id: int,     # Параметр пути
    user_data: dict = Depends(role_required(['Пользователь', 'Сотрудник', 'Организатор', 'Администратор'])) 
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        conn = await get_connection()     
        event = await conn.fetchrow(
            """SELECT 
                  e.id, e.name, e.description, e.start_time, e.end_time, 
                  e.max_participants, e.event_type_id, e.status_id,
                  e.min_age_category_id, e.organizer_id,
                  et.name as event_type_name,
                  es.name as status_name, 
                  u.full_name as organizer_name,
                  r.id as room_id, r.name as room_name,
                  ac.name as age_category_name
               FROM events e
               LEFT JOIN event_types et ON et.id = e.event_type_id
               LEFT JOIN event_statuses es ON es.id = e.status_id
               LEFT JOIN users u ON u.id = e.organizer_id
               LEFT JOIN resource_bookings rb ON rb.event_id = e.id AND rb.resource_type = 'room'
               LEFT JOIN rooms r ON r.id = rb.resource_id
               LEFT JOIN age_categories ac ON ac.id = e.min_age_category_id
               WHERE e.id = $1""",
            event_id
        )
        
        if not event:
            raise HTTPException(status_code=404, detail="Мероприятие не найдено")
        
        employees = await conn.fetch(
            """SELECT 
                  e.id, e.full_name, e.position, e.is_external
               FROM resource_bookings rb
               JOIN employees e ON e.id = rb.resource_id
               WHERE rb.event_id = $1 AND rb.resource_type = 'employee'""",
            event_id
        )
        
        
        all_employees = await conn.fetch("SELECT * FROM employees ORDER BY full_name")
        current_employee_ids = [e['id'] for e in employees]
        
        
        event_types = await conn.fetch("SELECT * FROM event_types ORDER BY name")
        event_statuses = await conn.fetch("SELECT * FROM event_statuses ORDER BY name")
        rooms = await conn.fetch("SELECT * FROM rooms ORDER BY name")
        age_categories = await conn.fetch("SELECT * FROM age_categories ORDER BY name")
        
        return templates.TemplateResponse(
            "event_details.html",
            {
                "request": request,
                "current_user": current_user,
                "event": event,
                "employees": employees,
                "event_types": event_types,
                "event_statuses": event_statuses,
                "rooms": rooms,
                "age_categories": age_categories,
                "all_employees": all_employees,
                "current_employee_ids": current_employee_ids
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting event details: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")
    finally:
        if 'conn' in locals():
            await conn.close()

@app.get("/activity")
async def external(request: Request,
                   user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
                   ):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        return templates.TemplateResponse(
            "activity.html",
            {"request": request, "current_user": current_user}
        )
    except HTTPException:
        return RedirectResponse(url="/unregistered")

@app.get("/api/positions")
async def get_positions():
    """Получение списка всех должностей"""
    try:
        conn = await get_connection()
        positions = await conn.fetch("SELECT id, name FROM positions ORDER BY name")
        return {
            "success": True,
            "positions": [{"id": p["id"], "name": p["name"]} for p in positions]
        }
    except Exception as e:
        print(f"Error getting positions: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if 'conn' in locals():
            await conn.close()

@app.post("/api/positions/add")
async def add_position(request: Request):
    """Добавление новой должности"""
    try:
        data = await request.json()
        position_name = data.get('name', '').strip()
        
        if not position_name:
            return {"success": False, "error": "Название должности не может быть пустым"}
        
        conn = await get_connection()
        
        # Проверяем, существует ли уже такая должность
        existing_position = await conn.fetchrow(
            "SELECT id, name FROM positions WHERE name = $1", 
            position_name
        )
        
        if existing_position:
            return {
                "success": True, 
                "position_id": existing_position["id"],
                "position_name": existing_position["name"],
                "message": "Должность уже существует"
            }
        
        # Создаем новую должность
        position_id = await conn.fetchval(
            "INSERT INTO positions (name) VALUES ($1) RETURNING id",
            position_name
        )
        
        return {
            "success": True,
            "position_id": position_id,
            "position_name": position_name,
            "message": "Должность успешно добавлена"
        }
        
    except Exception as e:
        print(f"Error adding position: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if 'conn' in locals():
            await conn.close()
            
@app.post("/employees/add")
async def add_employee(
    request: Request,
    full_name: str = Form(...),
    position_id: Optional[int] = Form(None),
    new_position: Optional[str] = Form(None),  # Новая должность, если пользователь хочет создать
    contact_info: Optional[str] = Form(None),
    is_external: bool = Form(False),
    external_url: Optional[str] = Form(None),
    parsed_data: Optional[str] = Form(None),
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    """Добавление сотрудника (внутреннего или внешнего)"""
    try:
        conn = await get_connection()
        current_user = user_data["user"]
        
        # Определяем ID должности
        final_position_id = None
        position_name = None
        
        if new_position and new_position.strip():
            # Создаем новую должность
            position_name = new_position.strip()
            final_position_id = await conn.fetchval(
                "INSERT INTO positions (name) VALUES ($1) RETURNING id",
                position_name
            )
        elif position_id:
            # Используем существующую должность
            position_record = await conn.fetchrow(
                "SELECT id, name FROM positions WHERE id = $1", 
                position_id
            )
            if position_record:
                final_position_id = position_record["id"]
                position_name = position_record["name"]
        
        if not final_position_id:
            raise HTTPException(
                status_code=400, 
                detail="Не указана должность"
            )
        
        # Добавляем сотрудника
        employee_id = await conn.fetchval("""
            INSERT INTO employees (full_name, position, position_id, contact_info, is_external, external_url)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
        """, full_name, position_name, final_position_id, contact_info, is_external, external_url)
        
        return RedirectResponse(url="/rooms?tab=employees", status_code=303)
        
    except Exception as e:
        print(f"Error adding employee: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка при добавлении сотрудника: {str(e)}"
        )
    finally:
        if 'conn' in locals():
            await conn.close()
            
@app.post("/employees/{employee_id}/update")
async def update_employee(
    request: Request,
    employee_id: int,
    full_name: str = Form(...),
    position_id: Optional[int] = Form(None),
    new_position: Optional[str] = Form(None),
    contact_info: Optional[str] = Form(None),
    is_external: bool = Form(False),
    external_url: Optional[str] = Form(None),
    user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    """Обновление данных сотрудника"""
    try:
        conn = await get_connection()
        
        # Определяем ID должности (аналогично добавлению)
        final_position_id = None
        position_name = None
        
        if new_position and new_position.strip():
            position_name = new_position.strip()
            final_position_id = await conn.fetchval(
                "INSERT INTO positions (name) VALUES ($1) RETURNING id",
                position_name
            )
        elif position_id:
            position_record = await conn.fetchrow(
                "SELECT id, name FROM positions WHERE id = $1", 
                position_id
            )
            if position_record:
                final_position_id = position_record["id"]
                position_name = position_record["name"]
        
        if not final_position_id:
            raise HTTPException(status_code=400, detail="Не указана должность")
        
        await conn.execute("""
            UPDATE employees SET 
                full_name = $1, 
                position = $2, 
                position_id = $3, 
                contact_info = $4, 
                is_external = $5, 
                external_url = $6 
            WHERE id = $7
        """, full_name, position_name, final_position_id, contact_info, is_external, external_url, employee_id)
        
        return RedirectResponse(url="/rooms?tab=employees", status_code=303)
        
    except Exception as e:
        print(f"Error updating employee: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Ошибка при обновлении сотрудника: {str(e)}"
        )
    finally:
        if 'conn' in locals():
            await conn.close()
@app.get("/rooms")
async def rooms(request: Request,
                user_data: dict = Depends(role_required(['Организатор', 'Администратор']))
):
    try:
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        
        conn = await get_connection()
        
        rooms = await conn.fetch("""
            SELECT r.*, rt.name as room_type_name 
            FROM rooms r
            LEFT JOIN room_types rt ON r.room_type_id = rt.id
            ORDER BY r.name
        """)
        
        employees = await conn.fetch("""
            SELECT e.*, p.name as position_name 
            FROM employees e
            LEFT JOIN positions p ON e.position_id = p.id
            ORDER BY e.full_name
        """)
        
        room_types = await conn.fetch("SELECT * FROM room_types ORDER BY name")
        positions = await conn.fetch("SELECT * FROM positions ORDER BY name")
        
        # Добавьте эту проверку для отладки
        print(f"Количество должностей: {len(positions)}")
        for position in positions:
            print(f"Должность: {position['name']} (ID: {position['id']})")
        
        return templates.TemplateResponse(
            "rooms.html",
            {
                "request": request,
                "current_user": current_user,
                "rooms": rooms,
                "employees": employees,  
                "room_types": room_types,
                "positions": positions  # Убедитесь, что это передается
            }
        )
    except HTTPException as e:
        if e.status_code == 303:
            return RedirectResponse(url="/unregistered")
        raise
    except Exception as e:
        print(f"Error in /rooms: {e}")
        return templates.TemplateResponse(
            "error.html", 
            {"request": request, "error": str(e)}, 
            status_code=500
        )
    finally:
        await conn.close()
        
@app.get("/rooms/{room_id}")
async def room_details(request: Request, room_id: int,
                       user_data: dict = Depends(role_required(['Организатор', 'Администратор']))):
    try:
        conn = await get_connection()
        current_user = user_data["user"]
        current_user['roles'] = user_data["roles"]
        
        # Получаем данные помещения
        room = await conn.fetchrow(
            """SELECT r.*, rt.name as room_type_name 
               FROM rooms r
               LEFT JOIN room_types rt ON r.room_type_id = rt.id
               WHERE r.id = $1""",
            room_id
        )
        
        if not room:
            raise HTTPException(status_code=404, detail="Помещение не найдено")
            
        # Получаем список типов помещений для формы редактирования
        room_types = await conn.fetch("SELECT * FROM room_types ORDER BY name")
        
        # Получаем мероприятия в этом помещении
        events = await conn.fetch(
            """SELECT e.id, e.name, e.start_time, e.end_time 
               FROM events e
               JOIN resource_bookings rb ON rb.event_id = e.id AND rb.resource_type = 'room'
               WHERE rb.resource_id = $1
               ORDER BY e.start_time""",
            room_id
        )
        
        return templates.TemplateResponse(
            "room_details.html",
            {
                "request": request,
                "current_user": current_user,
                "room": room,
                "room_types": room_types,  # Добавляем типы помещений
                "events": events
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting room details: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера")
    finally:
        if 'conn' in locals():
            await conn.close()

@app.delete("/rooms/{room_id}")
async def delete_room(request: Request, room_id: int):
    try:
        conn = await get_connection()
        
        
        has_bookings = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM resource_bookings WHERE resource_type = 'room' AND resource_id = $1)",
            room_id
        )
        
        if has_bookings:
            return JSONResponse(
                {"success": False, "error": "Невозможно удалить помещение, так как оно связано с мероприятиями"},
                status_code=400
            )
        
        
        room = await conn.fetchrow("SELECT image_filename FROM rooms WHERE id = $1", room_id)
        if room and room['image_filename']:
            image_path = UPLOAD_DIR / room['image_filename']
            if image_path.exists():
                image_path.unlink()
        
        await conn.execute("DELETE FROM rooms WHERE id = $1", room_id)
        
        return JSONResponse({"success": True})
        
    except Exception as e:
        print(f"Error deleting room: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    finally:
        if 'conn' in locals():
            await conn.close()         
        
@app.get("/unregistered")
async def unregistered(
    request: Request,
    error: Optional[str] = None,
    message: Optional[str] = None,
    show_login_modal: bool = False
):
    """Главная страница для неавторизованных пользователей"""
    return templates.TemplateResponse(
        "unregistered.html",
        {
            "request": request,
            "error": error,
            "message": message,
            "show_login_modal": show_login_modal,
            "admin_username": ADMIN_USERNAME,
            "admin_password": ADMIN_PASSWORD
        }
    )


@app.get("/external/sync")
async def sync_external_resources(request: Request):
    """Синхронизация внешних ресурсов (специалистов и помещений)"""
    try:
        conn = await get_connection()
        
        
        await sync_hh_contractors(conn)
        
        
        await sync_flamp_venues(conn)
        
        return JSONResponse({"success": True, "message": "Внешние ресурсы успешно синхронизированы"})
        
    except Exception as e:
        print(f"Error syncing external resources: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    finally:
        if 'conn' in locals():
            await conn.close()

async def sync_hh_contractors(conn):
    """Синхронизация специалистов с hh.ru"""
    try:
        
        
        contractors = [
            {
                "name": "Иванов Иван Иванович",
                "specialty": "Охранник",
                "contact_info": "https://hh.ru/resume/123",
                "rating": 4.5,
                "price_per_hour": 500
            }
        ]
        
        for contractor in contractors:
            
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM external_contractors WHERE name = $1 AND specialty = $2)",
                contractor["name"], contractor["specialty"]
            )
            
            if not exists:
                await conn.execute(
                    "INSERT INTO external_contractors (name, specialty, contact_info, rating, price_per_hour) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    contractor["name"], contractor["specialty"], 
                    contractor["contact_info"], contractor["rating"],
                    contractor["price_per_hour"]
                )
        
    except Exception as e:
        print(f"Error syncing hh contractors: {e}")
        raise

async def sync_flamp_venues(conn):
    """Синхронизация помещений с flamp"""
    try:
        
        
        venues = [
            {
                "name": "Чердак (ночной клуб)",
                "address": "ул. Ленина, 1",
                "capacity": 100,
                "description": "Ночной клуб с танцполом",
                "room_type_id": 1,  
                "is_external": True,
                "image_filename": None
            }
        ]
        
        for venue in venues:
            
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM rooms WHERE name = $1 AND address = $2)",
                venue["name"], venue["address"]
            )
            
            if not exists:
                await conn.execute(
                    "INSERT INTO rooms (name, address, capacity, description, room_type_id, is_external, image_filename) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    venue["name"], venue["address"], venue["capacity"],
                    venue["description"], venue["room_type_id"], 
                    venue["is_external"], venue["image_filename"]
                )
        
    except Exception as e:
        print(f"Error syncing flamp venues: {e}")
        raise

@app.post("/api/parse/flamp")
async def parse_flamp_venue(url: str = Form(...)):
    """Парсинг помещения с flamp.ru"""
    try:
        from parsers.flamp_parser import parse_flamp_venue, format_for_db
        result = parse_flamp_venue(url)
        if not result:
            return {"success": False, "error": "Не удалось распарсить заведение"}
        
        db_data = format_for_db(result)
        return {"success": True, "data": db_data}
    except Exception as e:
        print(f"Error parsing flamp venue: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/parse/hh")
async def parse_hh_resume(url: str = Form(...)):
    """Парсинг резюме с hh.ru"""
    try:
        from parsers.hh_parser import parse_hh_resume, format_for_db
        result = parse_hh_resume(url)
        if not result:
            return {"success": False, "error": "Не удалось распарсить резюме"}
        
        db_data = format_for_db(result)
        return {"success": True, "data": db_data}
    except Exception as e:
        print(f"Error parsing hh resume: {e}")
        return {"success": False, "error": str(e)}


@app.post("/rooms/add")
async def add_room(
    request: Request,
    name: str = Form(...),
    room_type_id: int = Form(...),
    capacity: int = Form(...),
    address: str = Form(...),
    description: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    is_external: bool = Form(False),
    external_url: Optional[str] = Form(None),
    parsed_data: Optional[str] = Form(None)
):
    """Добавление помещения (внутреннего или внешнего)"""
    image_filename = None  
    
    try:
        conn = await get_connection()
        
        
        if parsed_data:
            try:
                parsed_data = json.loads(parsed_data)
                name = parsed_data.get('name', name)
                address = parsed_data.get('address', address)
                capacity = parsed_data.get('capacity', capacity)
                description = parsed_data.get('description', description)
                room_type_id = parsed_data.get('room_type_id', room_type_id)
                is_external = True  
                external_url = parsed_data.get('source_url', external_url)
            except json.JSONDecodeError as e:
                print(f"Ошибка декодирования JSON: {e}")
                
        
        
        room_type = await conn.fetchrow("SELECT id FROM room_types WHERE id = $1", room_type_id)
        if not room_type:
            raise HTTPException(status_code=400, detail="Неверный тип помещения")
        
        
        if image and image.filename:
            file_ext = os.path.splitext(image.filename)[1]
            image_filename = f"room_{secrets.token_hex(8)}{file_ext}"
            file_path = UPLOAD_DIR / image_filename
            with file_path.open("wb") as buffer:
                buffer.write(await image.read())
        
        
        await conn.execute(
            "INSERT INTO rooms (name, room_type_id, capacity, address, description, image_filename, is_external, external_url) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
            name, room_type_id, capacity, address, description, image_filename, is_external, external_url
        )
        
        return RedirectResponse(url="/rooms", status_code=303)
    except HTTPException:
        raise
    except Exception as e:
        print(f"Ошибка добавления помещения: {e}")
        if image_filename and (UPLOAD_DIR / image_filename).exists():
            (UPLOAD_DIR / image_filename).unlink()
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "error": "Ошибка при добавлении помещения"},
            status_code=500
        )
    finally:
        if 'conn' in locals():
            await conn.close()
            
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)