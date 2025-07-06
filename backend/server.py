from fastapi import FastAPI, APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import JWTError, jwt
import os
import logging
import uuid
from pathlib import Path
from dotenv import load_dotenv
import motor.motor_asyncio
import asyncio
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import random

# async def test_db():
#     client = motor.motor_asyncio.AsyncIOMotorClient("mongodb+srv://arinjain789123:Gamerboi123@kanban.gespaxs.mongodb.net/kanban_todo_app?retryWrites=true&w=majority")
#     db = client["kanban_todo_app"]
#     collections = await db.list_collection_names()
#     print("Collections:", collections)

# # asyncio.run(test_db())


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
db_name = os.environ['DB_NAME']
jwt_secret = os.environ['JWT_SECRET']
jwt_algorithm = os.environ['JWT_ALGORITHM']
jwt_expiration_hours = int(os.environ['JWT_EXPIRATION_HOURS'])

client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Create the main app
app = FastAPI(title="Kanban Todo API", version="1.0.0")
api_router = APIRouter(prefix="/api")

# Models
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: str
    hashed_password: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    priority: str = "medium"  # low, medium, high
    due_date: Optional[datetime] = None
    project_id: Optional[str] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = None
    project_id: Optional[str] = None

class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: Optional[str] = ""
    priority: str = "medium"
    status: str = "todo"  # todo, in_progress, done
    due_date: Optional[datetime] = None
    project_id: Optional[str] = None
    user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    color: str = "#6366f1"  # Default purple color

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None

class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = ""
    color: str = "#6366f1"
    user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ProjectWithTasks(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    color: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    tasks: List[Task] = []

# OTP Model
class OTPRequest(BaseModel):
    email: EmailStr
    otp: Optional[str] = None
    otp_token: Optional[str] = None
    new_password: Optional[str] = None

# Utility functions
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=jwt_expiration_hours)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, jwt_secret, algorithm=jwt_algorithm)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    try:
        token = credentials.credentials
        payload = jwt.decode(token, jwt_secret, algorithms=[jwt_algorithm])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_doc = await db.users.find_one({"id": user_id})
    if user_doc is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return User(**user_doc)

# Utility: Send email using SendGrid API
def send_email(to_email: str, subject: str, body: str, otp: str = None):
    sendgrid_api_key = os.environ.get('SENDGRID_API_KEY')
    from_email = os.environ.get('FROM_EMAIL')
    if not sendgrid_api_key or not from_email:
        raise Exception('SENDGRID_API_KEY and FROM_EMAIL must be set in environment')

    # If sending OTP, use a beautiful HTML template
    if otp:
        logo_url = 'https://kanban-board-git-main-lancerhawks-projects.vercel.app/logo.png'
        html_content = f'''
        <div style="font-family: 'Segoe UI', Arial, sans-serif; background: #f6f8fa; padding: 40px 0;">
          <div style="max-width: 480px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(80,80,120,0.08); padding: 32px 32px 24px 32px;">
            <div style="text-align: center; margin-bottom: 24px;">
              <img src='{logo_url}' alt='TaskFlow' width='180' style='margin-bottom: 12px;'/>
              <h2 style="margin: 0; color: #4f46e5; font-size: 2rem; font-weight: 700;">Password Reset OTP</h2>
            </div>
            <p style="font-size: 1.1rem; color: #222; margin-bottom: 18px;">Hello,</p>
            <p style="font-size: 1.1rem; color: #222; margin-bottom: 18px;">We received a request to reset your password for your TaskFlow account. Use the OTP below to continue:</p>
            <div style="text-align: center; margin: 32px 0;">
              <span style="display: inline-block; font-size: 2.2rem; letter-spacing: 0.3rem; color: #fff; background: linear-gradient(90deg,#6366f1,#4f46e5); padding: 16px 40px; border-radius: 10px; font-weight: bold; box-shadow: 0 2px 8px rgba(80,80,120,0.08);">{otp}</span>
            </div>
            <p style="font-size: 1rem; color: #444; margin-bottom: 18px;">This OTP is valid for <b>10 minutes</b>. If you did not request a password reset, you can safely ignore this email.</p>
            <p style="font-size: 1rem; color: #888; margin-top: 32px; text-align: center;">&mdash; Arin Jain</p>
          </div>
          <div style="text-align: center; color: #aaa; font-size: 0.95rem; margin-top: 18px;">&copy; {datetime.now().year} TaskFlow. All rights reserved.</div>
        </div>
        '''
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            plain_text_content=body,
            html_content=html_content
        )
    else:
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            plain_text_content=body
        )
    try:
        sg = SendGridAPIClient(sendgrid_api_key)
        sg.send(message)
    except Exception as e:
        raise Exception(f'Failed to send email: {e}')

# Auth Routes
@api_router.post("/auth/register", response_model=Token)
async def register(user_data: UserCreate):
    # Check if user already exists
    existing_user = await db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    hashed_password = hash_password(user_data.password)
    user = User(
        name=user_data.name,
        email=user_data.email,
        hashed_password=hashed_password
    )
    
    await db.users.insert_one(user.dict())
    
    # Create token
    access_token = create_access_token(data={"sub": user.id})
    user_response = UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at
    )
    
    return Token(access_token=access_token, token_type="bearer", user=user_response)

@api_router.post("/auth/login", response_model=Token)
async def login(login_data: UserLogin):
    user_doc = await db.users.find_one({"email": login_data.email})
    if not user_doc or not verify_password(login_data.password, user_doc["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = User(**user_doc)
    access_token = create_access_token(data={"sub": user.id})
    user_response = UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at
    )
    
    return Token(access_token=access_token, token_type="bearer", user=user_response)

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        created_at=current_user.created_at
    )

# Task Routes
@api_router.post("/tasks", response_model=Task)
async def create_task(task_data: TaskCreate, current_user: User = Depends(get_current_user)):
    task = Task(**task_data.dict(), user_id=current_user.id)
    await db.tasks.insert_one(task.dict())
    return task

@api_router.get("/tasks", response_model=List[Task])
async def get_tasks(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    query = {"user_id": current_user.id}
    if project_id:
        query["project_id"] = project_id
    # If no project_id, return ALL tasks for the user (including project tasks)
    tasks = await db.tasks.find(query).to_list(1000)
    return [Task(**task) for task in tasks]

@api_router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str, current_user: User = Depends(get_current_user)):
    task_doc = await db.tasks.find_one({"id": task_id, "user_id": current_user.id})
    if not task_doc:
        raise HTTPException(status_code=404, detail="Task not found")
    return Task(**task_doc)

@api_router.put("/tasks/{task_id}", response_model=Task)
async def update_task(
    task_id: str,
    task_update: TaskUpdate,
    current_user: User = Depends(get_current_user)
):
    task_doc = await db.tasks.find_one({"id": task_id, "user_id": current_user.id})
    if not task_doc:
        raise HTTPException(status_code=404, detail="Task not found")
    
    update_data = {k: v for k, v in task_update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    await db.tasks.update_one(
        {"id": task_id, "user_id": current_user.id},
        {"$set": update_data}
    )
    
    updated_task = await db.tasks.find_one({"id": task_id, "user_id": current_user.id})
    return Task(**updated_task)

@api_router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, current_user: User = Depends(get_current_user)):
    result = await db.tasks.delete_one({"id": task_id, "user_id": current_user.id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"message": "Task deleted successfully"}

# Project Routes
@api_router.post("/projects", response_model=Project)
async def create_project(project_data: ProjectCreate, current_user: User = Depends(get_current_user)):
    project = Project(**project_data.dict(), user_id=current_user.id)
    await db.projects.insert_one(project.dict())
    return project

@api_router.get("/projects", response_model=List[Project])
async def get_projects(current_user: User = Depends(get_current_user)):
    projects = await db.projects.find({"user_id": current_user.id}).to_list(1000)
    return [Project(**project) for project in projects]

@api_router.get("/projects/{project_id}", response_model=ProjectWithTasks)
async def get_project_with_tasks(project_id: str, current_user: User = Depends(get_current_user)):
    project_doc = await db.projects.find_one({"id": project_id, "user_id": current_user.id})
    if not project_doc:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get all tasks for this project
    tasks = await db.tasks.find({"project_id": project_id, "user_id": current_user.id}).to_list(1000)
    
    project = Project(**project_doc)
    project_with_tasks = ProjectWithTasks(
        **project.dict(),
        tasks=[Task(**task) for task in tasks]
    )
    
    return project_with_tasks

@api_router.put("/projects/{project_id}", response_model=Project)
async def update_project(
    project_id: str,
    project_update: ProjectUpdate,
    current_user: User = Depends(get_current_user)
):
    project_doc = await db.projects.find_one({"id": project_id, "user_id": current_user.id})
    if not project_doc:
        raise HTTPException(status_code=404, detail="Project not found")
    
    update_data = {k: v for k, v in project_update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc)
    
    await db.projects.update_one(
        {"id": project_id, "user_id": current_user.id},
        {"$set": update_data}
    )
    
    updated_project = await db.projects.find_one({"id": project_id, "user_id": current_user.id})
    return Project(**updated_project)

@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str, current_user: User = Depends(get_current_user)):
    # Delete all tasks in the project
    await db.tasks.delete_many({"project_id": project_id, "user_id": current_user.id})
    
    # Delete the project
    result = await db.projects.delete_one({"id": project_id, "user_id": current_user.id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {"message": "Project and all associated tasks deleted successfully"}

# Dashboard/Stats Routes
@api_router.get("/dashboard/stats")
async def get_dashboard_stats(current_user: User = Depends(get_current_user)):
    # Get task counts
    total_tasks = await db.tasks.count_documents({"user_id": current_user.id})
    completed_tasks = await db.tasks.count_documents({"user_id": current_user.id, "status": "done"})
    in_progress_tasks = await db.tasks.count_documents({"user_id": current_user.id, "status": "in_progress"})
    todo_tasks = await db.tasks.count_documents({"user_id": current_user.id, "status": "todo"})
    
    # Get project count
    total_projects = await db.projects.count_documents({"user_id": current_user.id})
    
    # Get overdue tasks
    current_time = datetime.now(timezone.utc)
    overdue_tasks = await db.tasks.count_documents({
        "user_id": current_user.id,
        "status": {"$ne": "done"},
        "due_date": {"$lt": current_time}
    })
    
    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "in_progress_tasks": in_progress_tasks,
        "todo_tasks": todo_tasks,
        "total_projects": total_projects,
        "overdue_tasks": overdue_tasks,
        "completion_rate": round((completed_tasks / total_tasks * 100) if total_tasks > 0 else 0, 1)
    }

# Health check
@api_router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc),
        "database": "connected"
    }

# --- Forgot Password: Step 1: Request OTP ---
@api_router.post('/auth/forgot-password')
async def forgot_password(data: OTPRequest):
    user = await db.users.find_one({'email': data.email})
    if not user:
        raise HTTPException(status_code=404, detail='Email not registered')
    otp = str(random.randint(100000, 999999))
    otp_token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db.otps.insert_one({
        'email': data.email,
        'otp': otp,
        'otp_token': otp_token,
        'expires_at': expires_at
    })
    send_email(
        to_email=data.email,
        subject='Your OTP for Password Reset',
        body=f'Your OTP is: {otp}\nIt is valid for 10 minutes.',
        otp=otp
    )
    return {'message': 'OTP sent to email', 'otp_token': otp_token}

# --- Forgot Password: Step 2: Verify OTP ---
@api_router.post('/auth/verify-otp')
async def verify_otp(data: OTPRequest):
    otp_doc = await db.otps.find_one({'email': data.email, 'otp': data.otp, 'otp_token': data.otp_token})
    if not otp_doc:
        raise HTTPException(status_code=400, detail='Invalid OTP or token')
    expires_at = otp_doc['expires_at']
    if expires_at.tzinfo is None:
        from datetime import timezone
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail='OTP expired')
    return {'message': 'OTP verified', 'otp_token': data.otp_token}

# --- Forgot Password: Step 3: Reset Password ---
@api_router.post('/auth/reset-password')
async def reset_password(data: OTPRequest):
    otp_doc = await db.otps.find_one({'email': data.email, 'otp_token': data.otp_token})
    if not otp_doc:
        raise HTTPException(status_code=400, detail='Invalid or expired OTP token')
    expires_at = otp_doc['expires_at']
    if expires_at.tzinfo is None:
        from datetime import timezone
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail='OTP expired')
    # Update user password
    hashed = hash_password(data.new_password)
    await db.users.update_one({'email': data.email}, {'$set': {'hashed_password': hashed}})
    # Remove OTP after use
    await db.otps.delete_one({'_id': otp_doc['_id']})
    return {'message': 'Password reset successful'}

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
