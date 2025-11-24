from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
import uvicorn
import os

from email_agent import EmailAgent
from auto_reply_prompts import BorrowerAutoReplyGenerator

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
try:
    auto_reply_generator = BorrowerAutoReplyGenerator()
except ValueError as e:
    print(f"Warning: Auto-reply generator not initialized: {e}")
    auto_reply_generator = None

# Request models
class SendEmailRequest(BaseModel):
    to: EmailStr
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

class GenerateAutoReplyRequest(BaseModel):
    email_body: str
    subject: Optional[str] = ""
    borrower_name: Optional[str] = None
    context: Optional[dict] = None

class AutoReplyToBorrowerRequest(BaseModel):
    email_id: str
    borrower_name: Optional[str] = None
    context: Optional[dict] = None
    eaccount: Optional[str] = None

class ProcessCampaignRequest(BaseModel):
    campaign_name: str
    auto_reply: bool = False
    borrower_name: Optional[str] = None
    context: Optional[dict] = None

class EmailResponse(BaseModel):
    success: bool
    message: str
    email_id: Optional[str] = None
    timestamp: str

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Instantly.ai Email Automation Agent",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/playground")
async def playground():
    """Serve the playground HTML file"""
    playground_path = os.path.join(os.path.dirname(__file__), "playground.html")
    if os.path.exists(playground_path):
        return FileResponse(playground_path)
    else:
        raise HTTPException(status_code=404, detail="Playground file not found")

@app.get("/approval")
async def approval_ui():
    """Serve the email approval dashboard HTML file"""
    approval_path = os.path.join(os.path.dirname(__file__), "approval_ui.html")
    if os.path.exists(approval_path):
        return FileResponse(approval_path)
    else:
        raise HTTPException(status_code=404, detail="Approval UI file not found")

@app.post("/send-email", response_model=EmailResponse)
async def send_email(request: SendEmailRequest):
    """Send a single email using Instantly.ai"""
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
            email_id=result.get("email_id"),
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reply-email", response_model=EmailResponse)
async def reply_email(request: ReplyEmailRequest):
    """Reply to an existing email"""
    try:
        # Use provided email_data or fetch it
        # reply_to_uuid should be the email id to reply to
        reply_email_id = request.reply_to_uuid or request.email_id
        
        # Try to fetch the email to get full data, but if it fails, use provided data
        email_data = None
        try:
            email_data = await email_agent.get_email(reply_email_id)
        except Exception:
            # If fetch fails, create minimal structure with the email id
            email_data = {
                "id": reply_email_id,
                "subject": request.subject or "",
                "eaccount": request.eaccount
            }
        
        result = await email_agent.reply_to_email(
            email_id=reply_email_id,
            body=request.body,
            html_body=request.html_body,
            eaccount=request.eaccount,
            subject=request.subject,
            email_data=email_data
        )
        
        return EmailResponse(
            success=True,
            message="Reply sent successfully",
            email_id=result.get("email_id"),
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auto-reply/generate")
async def generate_auto_reply(request: GenerateAutoReplyRequest):
    """Generate an AI-powered auto-reply for a borrower email using GPT"""
    if not auto_reply_generator:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    try:
        result = await auto_reply_generator.generate_auto_reply(
            email_body=request.email_body,
            subject=request.subject or "",
            borrower_name=request.borrower_name,
            context=request.context or {}
        )
        
        return {
            "success": True,
            "reply": result.get("reply"),
            "model": result.get("model"),
            "timestamp": result.get("timestamp")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auto-reply/to-borrower", response_model=EmailResponse)
async def auto_reply_to_borrower(request: AutoReplyToBorrowerRequest):
    """Automatically reply to a borrower email using AI-generated response"""
    if not auto_reply_generator:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    try:
        # Get the original email
        original_email = await email_agent.get_email(request.email_id)
        
        email_body = original_email.get("body", {}).get("text", "") or original_email.get("body", {}).get("html", "")
        subject = original_email.get("subject", "")
        
        # Generate AI-powered auto-reply
        reply_data = await auto_reply_generator.generate_auto_reply(
            email_body=email_body,
            subject=subject,
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
        
        return EmailResponse(
            success=True,
            message=f"AI auto-reply sent successfully (Model: {reply_data.get('model')})",
            email_id=result.get("email_id"),
            timestamp=datetime.now().isoformat()
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/campaign/process")
async def process_campaign_emails(request: ProcessCampaignRequest):
    """Process and auto-reply to unread emails from a specific campaign. 
    Note: auto_reply defaults to False - set to True to actually send replies."""
    if not auto_reply_generator:
        raise HTTPException(status_code=500, detail="OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    try:
        # Find the campaign by name
        campaign = await email_agent.get_campaign_by_name(request.campaign_name)
        if not campaign:
            raise HTTPException(status_code=404, detail=f"Campaign '{request.campaign_name}' not found")
        
        campaign_id = campaign.get("id")
        
        # Get unread emails from this campaign
        emails_data = await email_agent.get_emails_by_campaign(
            campaign_id=campaign_id,
            limit=50,
            is_unread=True
        )
        
        emails = emails_data.get("items", [])
        
        if not emails:
            return {
                "success": True,
                "message": f"No unread emails found in campaign '{request.campaign_name}'",
                "campaign_id": campaign_id,
                "campaign_name": request.campaign_name,
                "processed": 0,
                "timestamp": datetime.now().isoformat()
            }
        
        results = []
        processed = 0
        
        # Process emails with delay to avoid rate limits
        import asyncio
        for i, email in enumerate(emails):
            # Add delay between emails to respect rate limits (3 seconds between requests)
            if i > 0:
                await asyncio.sleep(3)
            try:
                email_id = email.get("id")
                email_body = email.get("body", {}).get("text", "") or email.get("body", {}).get("html", "")
                subject = email.get("subject", "")
                lead_email = email.get("lead")
                
                # Skip if already replied or if it's a sent email (not received)
                if email.get("ue_type") == 1:  # Sent email, not received
                    continue
                
                # Generate AI-powered auto-reply
                reply_data = await auto_reply_generator.generate_auto_reply(
                    email_body=email_body,
                    subject=subject,
                    borrower_name=request.borrower_name or lead_email,
                    context=request.context or {}
                )
                
                reply_body = reply_data.get("reply")
                
                # Store original email body and reply for approval UI
                result_item = {
                    "email_id": email_id,
                    "lead": lead_email,
                    "original_body": email_body,
                    "original_subject": subject,
                    "reply": reply_body,
                    "intent": reply_data.get("inquiry_type"),
                    "status": "pending",
                    "eaccount": email.get("eaccount"),
                    "reply_to_uuid": email.get("id") or email_id,  # Use email id, not thread_id
                    "subject": subject
                }
                
                # Send the AI-generated reply
                if request.auto_reply:
                    # Ensure we have eaccount
                    reply_eaccount = email.get("eaccount")
                    if not reply_eaccount:
                        raise Exception(f"eaccount is required for email {email_id}. Email data: {email}")
                    
                    result = await email_agent.reply_to_email(
                        email_id=email_id,
                        body=reply_body,
                        html_body=f"<p>{reply_body.replace(chr(10), '<br>')}</p>" if reply_body else None,
                        eaccount=reply_eaccount,
                        subject=subject,
                        email_data=email  # Pass the email data we already have
                    )
                    processed += 1
                    result_item["status"] = "replied"
                    result_item["reply_id"] = result.get("email_id")
                else:
                    result_item["status"] = "generated_only"
                
                results.append(result_item)
                    
            except Exception as e:
                results.append({
                    "email_id": email.get("id"),
                    "lead": email.get("lead"),
                    "status": "error",
                    "error": str(e)
                })
        
        return {
            "success": True,
            "message": f"Processed {processed} emails from campaign '{request.campaign_name}'",
            "campaign_id": campaign_id,
            "campaign_name": request.campaign_name,
            "total_emails": len(emails),
            "processed": processed,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
