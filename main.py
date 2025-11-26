from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, List
from datetime import datetime
import uvicorn
import os
import asyncio
import uuid
import time

from email_agent import EmailAgent
from auto_reply_prompts import BorrowerAutoReplyGenerator

# In-memory storage for progress tracking
progress_store: Dict[str, Dict] = {}
processed_email_cache: Dict[str, float] = {}
PROCESSED_EMAIL_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_INITIAL_DELAY = 20  # seconds
RATE_LIMIT_BACKOFF = 2
RATE_LIMIT_KEYWORDS = ("rate limit", "too many requests", "429")

# Rate limiter: 100 requests per 10 seconds = 10 requests per second max
class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 10):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = []
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Wait if necessary to respect rate limit"""
        async with self.lock:
            now = asyncio.get_event_loop().time()
            # Remove requests older than the window
            self.requests = [req_time for req_time in self.requests if now - req_time < self.window_seconds]
            
            # If we're at the limit, wait until the oldest request expires
            if len(self.requests) >= self.max_requests:
                oldest = min(self.requests)
                wait_time = self.window_seconds - (now - oldest) + 0.1  # Add 0.1s buffer
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    # Clean up again after waiting
                    now = asyncio.get_event_loop().time()
                    self.requests = [req_time for req_time in self.requests if now - req_time < self.window_seconds]
            
            # Record this request
            self.requests.append(now)

# Global rate limiter for Instantly.ai API calls
instantly_rate_limiter = RateLimiter(max_requests=100, window_seconds=10)

def cleanup_processed_cache():
    """Remove expired entries from processed email cache"""
    now = time.time()
    expired_keys = [
        email_id for email_id, ts in processed_email_cache.items()
        if now - ts > PROCESSED_EMAIL_TTL_SECONDS
    ]
    for key in expired_keys:
        processed_email_cache.pop(key, None)

def mark_email_processed(email_id: Optional[str]):
    """Mark an email as processed to avoid duplicate approvals"""
    if not email_id:
        return
    cleanup_processed_cache()
    processed_email_cache[email_id] = time.time()

def is_email_processed(email_id: Optional[str]) -> bool:
    """Check if an email has already been processed recently"""
    return get_processed_timestamp(email_id) is not None

def get_processed_timestamp(email_id: Optional[str]) -> Optional[float]:
    """Return the timestamp when the email was processed, if any"""
    if not email_id:
        return None
    cleanup_processed_cache()
    return processed_email_cache.get(email_id)

def build_skipped_entry(email: dict, reason: str, processed_ts: Optional[float] = None) -> Dict[str, Optional[str]]:
    """Create a summary for an email that was skipped from processing"""
    entry = {
        "email_id": email.get("id"),
        "lead": email.get("lead"),
        "subject": email.get("subject"),
        "campaign_name": email.get("campaign_name") or email.get("campaign_id"),
        "thread_id": email.get("thread_id"),
        "reason": reason,
        "processed_at": datetime.fromtimestamp(processed_ts).isoformat() if processed_ts else None,
        "received_at": email.get("timestamp_email"),
    }
    return entry

async def fetch_with_rate_limit_retry(fetch_fn, progress_id: Optional[str], context: str) -> dict:
    """Call fetch_fn with exponential backoff on rate limit errors"""
    delay = RATE_LIMIT_INITIAL_DELAY
    for attempt in range(1, RATE_LIMIT_MAX_ATTEMPTS + 1):
        try:
            return await fetch_fn()
        except Exception as e:
            error_text = str(e)
            lower_error = error_text.lower()
            is_rate_limit = any(keyword in lower_error for keyword in RATE_LIMIT_KEYWORDS)
            if not is_rate_limit or attempt == RATE_LIMIT_MAX_ATTEMPTS:
                raise
            log_entry = (f"[{datetime.now().strftime('%H:%M:%S')}] Rate limit hit while {context}. "
                         f"Retrying in {delay} seconds (attempt {attempt}/{RATE_LIMIT_MAX_ATTEMPTS})...")
            if progress_id and progress_id in progress_store:
                if "logs" not in progress_store[progress_id]:
                    progress_store[progress_id]["logs"] = []
                progress_store[progress_id]["logs"].append(log_entry)
            await asyncio.sleep(delay)
            delay *= RATE_LIMIT_BACKOFF
    raise Exception("Rate limit retry exhausted")

app = FastAPI(
    title="Instantly.ai Email Automation Agent",
    description="A FastAPI-based email automation service using Instantly.ai API",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize email agent
email_agent = EmailAgent()

# Initialize auto-reply generator
auto_reply_generator = None
try:
    auto_reply_generator = BorrowerAutoReplyGenerator()
except Exception as e:
    print(f"Warning: Could not initialize auto-reply generator: {e}")

# Pydantic models
class EmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    html_body: Optional[str] = None
    eaccount: Optional[str] = None

class ReplyEmailRequest(BaseModel):
    email_id: str
    body: str
    html_body: Optional[str] = None
    eaccount: Optional[str] = None
    subject: Optional[str] = None
    reply_to_uuid: Optional[str] = None

class AutoReplyRequest(BaseModel):
    email_body: str
    subject: str
    borrower_name: Optional[str] = None
    context: Optional[dict] = None

class AutoReplyToBorrowerRequest(BaseModel):
    email_id: str
    email_body: str
    subject: str
    borrower_name: Optional[str] = None
    eaccount: Optional[str] = None
    context: Optional[dict] = None

class EmailResponse(BaseModel):
    success: bool
    message: str
    email_id: Optional[str] = None
    timestamp: str

class ProcessCampaignRequest(BaseModel):
    campaign_name: Optional[str] = None
    auto_reply: bool = False
    borrower_name: Optional[str] = None
    context: Optional[dict] = None

class ProcessAllCampaignsRequest(BaseModel):
    auto_reply: bool = False
    borrower_name: Optional[str] = None
    context: Optional[dict] = None

# Helper function to process a single email
async def process_single_email(
    email: dict,
    campaign_id: str,
    campaign_name: str,
    auto_reply: bool,
    borrower_name: Optional[str],
    context: Optional[dict],
    progress_id: Optional[str] = None
) -> dict:
    """Process a single email and generate reply"""
    try:
        email_id = email.get("id")
        email_body = email.get("body", {}).get("text", "") or email.get("body", {}).get("html", "")
        subject = email.get("subject", "")
        lead_email = email.get("lead")
        
        # Skip if already replied or if it's a sent email (not received)
        if email.get("ue_type") == 1:  # Sent email, not received
            return None
        
        # Update progress (do this before the slow OpenAI call)
        if progress_id and progress_id in progress_store:
            # Don't increment yet - we'll do it after OpenAI call succeeds
            progress_store[progress_id]["current_email"] = lead_email or email_id
            # Add log entry
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Processing email from {lead_email or email_id}"
            if "logs" not in progress_store[progress_id]:
                progress_store[progress_id]["logs"] = []
            progress_store[progress_id]["logs"].append(log_entry)
        
        # Generate AI-powered auto-reply
        if progress_id and progress_id in progress_store:
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Calling OpenAI API to generate reply..."
            if "logs" not in progress_store[progress_id]:
                progress_store[progress_id]["logs"] = []
            progress_store[progress_id]["logs"].append(log_entry)
        
        reply_data = await auto_reply_generator.generate_auto_reply(
            email_body=email_body,
            subject=subject,
            borrower_name=borrower_name or lead_email,
            context=context or {}
        )
        
        reply_body = reply_data.get("reply")
        
        # Update progress after successful OpenAI call
        if progress_id and progress_id in progress_store:
            progress_store[progress_id]["current"] += 1
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Reply generated successfully for {lead_email or email_id}"
            if "logs" not in progress_store[progress_id]:
                progress_store[progress_id]["logs"] = []
            progress_store[progress_id]["logs"].append(log_entry)
        
        # Store original email body and reply for approval UI
        result_item = {
            "email_id": email_id,  # Full email ID from Instantly.ai
            "lead": lead_email,
            "original_body": email_body,
            "original_subject": subject,
            "reply": reply_body,
            "intent": reply_data.get("inquiry_type"),
            "status": "pending",
            "eaccount": email.get("eaccount"),
            "reply_to_uuid": email.get("id") or email_id,
            "subject": subject,
            "campaign_name": campaign_name,
            "campaign_id": campaign_id,
            "message_id": email.get("message_id"),  # Add message_id for reference
            "from_address": email.get("from_address_email")  # Add from address for reference
        }
        
        # Send the AI-generated reply
        if auto_reply:
            reply_eaccount = email.get("eaccount")
            if not reply_eaccount:
                raise Exception(f"eaccount is required for email {email_id}")
            
            # Rate limit Instantly.ai API calls (100 requests per 10 seconds)
            if progress_id and progress_id in progress_store:
                log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Waiting for rate limit... (100 req/10s)"
                if "logs" not in progress_store[progress_id]:
                    progress_store[progress_id]["logs"] = []
                progress_store[progress_id]["logs"].append(log_entry)
            
            await instantly_rate_limiter.acquire()
            
            if progress_id and progress_id in progress_store:
                log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Sending reply via Instantly.ai API..."
                if "logs" not in progress_store[progress_id]:
                    progress_store[progress_id]["logs"] = []
                progress_store[progress_id]["logs"].append(log_entry)
            
            result = await email_agent.reply_to_email(
                email_id=email_id,
                body=reply_body,
                html_body=f"<p>{reply_body.replace(chr(10), '<br>')}</p>" if reply_body else None,
                eaccount=reply_eaccount,
                subject=subject,
                email_data=email
            )
            result_item["status"] = "approved"
            result_item["sent_at"] = datetime.now().isoformat()
            
            if progress_id and progress_id in progress_store:
                log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Reply sent successfully to {lead_email or email_id}"
                if "logs" not in progress_store[progress_id]:
                    progress_store[progress_id]["logs"] = []
                progress_store[progress_id]["logs"].append(log_entry)
            
            mark_email_processed(email_id)
        else:
            result_item["status"] = "generated_only"
        
        return result_item
        
    except Exception as e:
        return {
            "email_id": email.get("id"),
            "lead": email.get("lead"),
            "status": "error",
            "error": str(e)
        }

@app.get("/")
async def root():
    return {"message": "Instantly.ai Email Automation Agent API", "status": "running"}

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "Instantly.ai Email Automation Agent",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/send-email", response_model=EmailResponse)
async def send_email(request: EmailRequest):
    """Send an email using Instantly.ai API"""
    try:
        result = await email_agent.send_email(
            to=request.to,
            subject=request.subject,
            body=request.body,
            html_body=request.html_body,
            eaccount=request.eaccount
        )
        
        return EmailResponse(
            success=True,
            message="Email sent successfully",
            email_id=result.get("campaign_id"),
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reply-email", response_model=EmailResponse)
async def reply_email(request: ReplyEmailRequest):
    """Reply to an existing email"""
    try:
        # Use provided email_data or fetch it
        email_data = None
        if request.reply_to_uuid:
            # If reply_to_uuid is provided, use it as the email id
            email_data = {
                "id": request.reply_to_uuid,  # Use reply_to_uuid as the email id
                "subject": request.subject or "",
                "eaccount": request.eaccount
            }
        else:
            # Try to fetch the email to get full data
            try:
                email_data = await email_agent.get_email(request.email_id)
            except Exception:
                # If fetch fails, create minimal structure
                email_data = {
                    "id": request.email_id,
                    "subject": request.subject or "",
                    "eaccount": request.eaccount
                }
        
        result = await email_agent.reply_to_email(
            email_id=request.email_id,
            body=request.body,
            html_body=request.html_body,
            eaccount=request.eaccount,
            subject=request.subject,
            email_data=email_data
        )
        
        mark_email_processed(request.reply_to_uuid or request.email_id)
        
        return EmailResponse(
            success=True,
            message="Reply sent successfully",
            email_id=result.get("email_id"),
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auto-reply/generate")
async def generate_auto_reply(request: AutoReplyRequest):
    """Generate an AI-powered auto-reply for a borrower email"""
    if not auto_reply_generator:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    try:
        reply_data = await auto_reply_generator.generate_auto_reply(
            email_body=request.email_body,
            subject=request.subject,
            borrower_name=request.borrower_name,
            context=request.context or {}
        )
        
        return {
            "success": True,
            "reply": reply_data.get("reply"),
            "inquiry_type": reply_data.get("inquiry_type"),
            "model": reply_data.get("model"),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auto-reply/to-borrower", response_model=EmailResponse)
async def auto_reply_to_borrower(request: AutoReplyToBorrowerRequest):
    """Generate and send an AI-powered auto-reply to a borrower"""
    if not auto_reply_generator:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    try:
        # Generate AI-powered auto-reply
        reply_data = await auto_reply_generator.generate_auto_reply(
            email_body=request.email_body,
            subject=request.subject,
            borrower_name=request.borrower_name,
            context=request.context or {}
        )
        
        reply_body = reply_data.get("reply")
        
        # Send the AI-generated reply
        result = await email_agent.reply_to_email(
            email_id=request.email_id,
            body=reply_body,
            html_body=f"<p>{reply_body.replace(chr(10), '<br>')}</p>" if reply_body else None,
            eaccount=request.eaccount
        )
        
        mark_email_processed(request.email_id)
        
        return EmailResponse(
            success=True,
            message=f"AI auto-reply sent successfully (Model: {reply_data.get('model')})",
            email_id=result.get("email_id"),
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/playground")
async def playground():
    """Serve the playground HTML file"""
    return FileResponse("playground.html")

@app.get("/approval")
async def approval():
    """Serve the approval UI HTML file"""
    return FileResponse("approval_ui.html")

@app.get("/progress/{progress_id}")
async def get_progress(progress_id: str):
    """Get progress for a processing job"""
    if progress_id not in progress_store:
        raise HTTPException(status_code=404, detail="Progress not found")
    return progress_store[progress_id]

@app.post("/campaign/process")
async def process_campaign_emails(request: ProcessCampaignRequest):
    """Process and auto-reply to unread emails from a specific campaign or all campaigns.
    If campaign_name is not provided, processes all campaigns.
    Note: auto_reply defaults to False - set to True to actually send replies."""
    if not auto_reply_generator:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    
    progress_id = str(uuid.uuid4())
    
    # Start processing in background
    asyncio.create_task(process_emails_background(request, progress_id))
    
    return {
        "success": True,
        "message": "Processing started",
        "progress_id": progress_id,
        "status": "processing"
    }

async def process_emails_background(request: ProcessCampaignRequest, progress_id: str):
    """Background task to process emails"""
    try:
        # Initialize progress
        progress_store[progress_id] = {
            "status": "processing",
            "total": 0,
            "current": 0,
            "current_email": "",
            "results": [],
            "skipped_emails": [],
            "error": None
        }
        
        # If no campaign_name provided, fetch all unread emails directly (fastest - only 1 API call)
        if not request.campaign_name:
            await process_all_unread_emails_background(request, progress_id)
        else:
            await process_single_campaign_background(request, progress_id)
    except Exception as e:
        progress_store[progress_id]["status"] = "error"
        progress_store[progress_id]["error"] = str(e)

async def process_single_campaign_background(request: ProcessCampaignRequest, progress_id: str):
    """Process emails from a single campaign"""
    try:
        # Rate limit: Get campaign by name (1 Instantly.ai API call)
        progress_store[progress_id]["logs"] = []
        log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Starting email processing..."
        progress_store[progress_id]["logs"].append(log_entry)
        
        log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Fetching campaign: {request.campaign_name}"
        progress_store[progress_id]["logs"].append(log_entry)
        
        await instantly_rate_limiter.acquire()
        campaign = await email_agent.get_campaign_by_name(request.campaign_name)
        if not campaign:
            progress_store[progress_id]["status"] = "error"
            progress_store[progress_id]["error"] = f"Campaign '{request.campaign_name}' not found"
            return
        
        campaign_id = campaign.get("id")
        
        # Rate limit: Get unread emails from this campaign (1 Instantly.ai API call)
        log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Campaign found. Fetching unread emails..."
        progress_store[progress_id]["logs"].append(log_entry)
        
        await instantly_rate_limiter.acquire()
        emails_data = await fetch_with_rate_limit_retry(
            lambda: email_agent.get_emails_by_campaign(
                campaign_id=campaign_id,
                limit=50,
                is_unread=True
            ),
            progress_id,
            f"fetching unread emails for campaign '{request.campaign_name}'"
        )
        
        emails = emails_data.get("items", [])
        valid_emails = [e for e in emails if e.get("ue_type") != 1]
        
        log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Found {len(valid_emails)} unread email(s) to process"
        progress_store[progress_id]["logs"].append(log_entry)
        
        if not valid_emails:
            progress_store[progress_id]["status"] = "completed"
            progress_store[progress_id]["total"] = 0
            return
        
        # Filter out emails already processed recently
        initial_count = len(valid_emails)
        skipped_entries: List[Dict[str, Optional[str]]] = []
        filtered_emails: List[dict] = []
        for email in valid_emails:
            email_id = email.get("id")
            processed_ts = get_processed_timestamp(email_id)
            if processed_ts:
                skipped_entries.append(build_skipped_entry(email, "already_processed", processed_ts))
            else:
                filtered_emails.append(email)
        valid_emails = filtered_emails
        if skipped_entries:
            progress_store[progress_id].setdefault("skipped_emails", []).extend(skipped_entries)
            log_entry = (f"[{datetime.now().strftime('%H:%M:%S')}] ⏭ Skipped {len(skipped_entries)} email(s) "
                         "already approved earlier")
            progress_store[progress_id]["logs"].append(log_entry)
        
        progress_store[progress_id]["total"] = len(valid_emails)
        
        # Process emails in parallel with controlled concurrency
        # Rate limit: 100 requests per 10 seconds = 10 requests per second max
        # Use 8 concurrent to be safe (leaves buffer for other API calls)
        semaphore = asyncio.Semaphore(8)
        
        async def process_with_semaphore(email):
            async with semaphore:
                return await process_single_email(
                    email, campaign_id, request.campaign_name,
                    request.auto_reply, request.borrower_name,
                    request.context, progress_id
                )
        
        tasks = [process_with_semaphore(email) for email in valid_emails]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None results and exceptions
        final_results = []
        for result in results:
            if result is None:
                continue
            if isinstance(result, Exception):
                final_results.append({"status": "error", "error": str(result)})
            else:
                final_results.append(result)
        
        progress_store[progress_id]["status"] = "completed"
        progress_store[progress_id]["results"] = final_results
        
    except Exception as e:
        progress_store[progress_id]["status"] = "error"
        progress_store[progress_id]["error"] = str(e)

async def process_all_unread_emails_background(request: ProcessCampaignRequest, progress_id: str):
    """Process all unread emails directly - fastest method (only 1 API call)"""
    try:
        progress_store[progress_id]["logs"] = []
        log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Starting email processing for ALL unread emails..."
        progress_store[progress_id]["logs"].append(log_entry)
        
        # Rate limit: Get all unread emails directly (ONLY 1 Instantly.ai API call - much faster!)
        log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Fetching all unread emails directly (fastest method)..."
        progress_store[progress_id]["logs"].append(log_entry)
        
        await instantly_rate_limiter.acquire()
        # Get unread emails and also include sent emails to check for replies
        emails_data = await fetch_with_rate_limit_retry(
            lambda: email_agent.get_all_unread_emails(limit=100, include_sent=True),
            progress_id,
            "fetching unread emails"
        )
        all_emails = emails_data.get("items", [])
        
        # Keep only received (unreplied) emails; rely on processed cache to avoid duplicates
        valid_emails = [e for e in all_emails if e.get("ue_type") != 1]
        log_entry = (f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Retrieved {len(valid_emails)} unread email(s) "
                     "before duplicate filtering")
        progress_store[progress_id]["logs"].append(log_entry)
        
        if not valid_emails:
            progress_store[progress_id]["status"] = "completed"
            progress_store[progress_id]["total"] = 0
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] No unread emails to process"
            progress_store[progress_id]["logs"].append(log_entry)
            return
        
        # Filter out emails already processed recently
        initial_count = len(valid_emails)
        skipped_entries: List[Dict[str, Optional[str]]] = []
        filtered_emails: List[dict] = []
        for email in valid_emails:
            email_id = email.get("id")
            processed_ts = get_processed_timestamp(email_id)
            if processed_ts:
                skipped_entries.append(build_skipped_entry(email, "already_processed", processed_ts))
            else:
                filtered_emails.append(email)
        valid_emails = filtered_emails
        if skipped_entries:
            progress_store[progress_id].setdefault("skipped_emails", []).extend(skipped_entries)
            log_entry = (f"[{datetime.now().strftime('%H:%M:%S')}] ⏭ Skipped {len(skipped_entries)} email(s) "
                         "already approved earlier")
            progress_store[progress_id]["logs"].append(log_entry)
        
        progress_store[progress_id]["total"] = len(valid_emails)
        
        if len(valid_emails) > 0:
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] Starting parallel processing (max 5 concurrent)..."
            progress_store[progress_id]["logs"].append(log_entry)
        
        # Process emails in parallel with controlled concurrency
        # Rate limit: 100 requests per 10 seconds
        # Use 5 concurrent to be safe (OpenAI calls don't count toward Instantly.ai limit)
        # Only Instantly.ai API calls (sending replies) count toward the limit
        semaphore = asyncio.Semaphore(5)
        
        async def process_with_semaphore(email):
            async with semaphore:
                # Get campaign name from email data if available
                campaign_id = email.get("campaign_id", "unknown")
                campaign_name = email.get("campaign_name") or f"Campaign {campaign_id[:8]}"
                return await process_single_email(
                    email, campaign_id, campaign_name,
                    request.auto_reply, request.borrower_name,
                    request.context, progress_id
                )
        
        tasks = [process_with_semaphore(email) for email in valid_emails]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out None results and exceptions
        final_results = []
        for result in results:
            if result is None:
                continue
            if isinstance(result, Exception):
                final_results.append({"status": "error", "error": str(result)})
            else:
                final_results.append(result)
        
        progress_store[progress_id]["status"] = "completed"
        progress_store[progress_id]["results"] = final_results
        
        log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Processing complete! Generated {len(final_results)} reply(ies)"
        progress_store[progress_id]["logs"].append(log_entry)
        
    except Exception as e:
        progress_store[progress_id]["status"] = "error"
        progress_store[progress_id]["error"] = str(e)
        if "logs" in progress_store[progress_id]:
            log_entry = f"[{datetime.now().strftime('%H:%M:%S')}] ✗ Error: {str(e)}"
            progress_store[progress_id]["logs"].append(log_entry)

@app.post("/campaign/process-all")
async def process_all_campaigns_emails(request: ProcessAllCampaignsRequest):
    """Process and auto-reply to unread emails from ALL campaigns. 
    Note: auto_reply defaults to False - set to True to actually send replies."""
    # Redirect to main process endpoint
    return await process_campaign_emails(ProcessCampaignRequest(
        campaign_name=None,
        auto_reply=request.auto_reply,
        borrower_name=request.borrower_name,
        context=request.context
    ))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
