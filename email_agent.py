import os
import httpx
from typing import Optional, Dict, Any
import uuid
from datetime import datetime
from dotenv import load_dotenv
import asyncio
import time

load_dotenv()

class EmailAgent:
    """Email automation agent using Instantly.ai API"""
    
    def __init__(self):
        api_key = os.getenv("INSTANTLY_API_KEY", "")
        # Strip quotes and whitespace if present
        if api_key:
            api_key = api_key.strip().strip('"').strip("'")
        self.api_key = api_key
        base_url = os.getenv("INSTANTLY_API_URL", "https://api.instantly.ai")
        # Ensure base_url doesn't have trailing slash and doesn't include /api/v2
        self.base_url = base_url.rstrip('/').replace('/api/v2', '')
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Rate limiting: Max 20 requests per minute (3 seconds between requests to be safe)
        self.min_request_interval = 3.0
        self.last_request_time = 0
        
        if not self.api_key:
            print("Warning: INSTANTLY_API_KEY not found in environment variables")
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retry_count: int = 3
    ) -> Dict[str, Any]:
        """Make HTTP request to Instantly.ai API with rate limiting and retry logic"""
        url = f"{self.base_url}{endpoint}"
        
        # Rate limiting: Ensure minimum time between requests
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            wait_time = self.min_request_interval - time_since_last
            await asyncio.sleep(wait_time)
        
        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    self.last_request_time = time.time()
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=self.headers,
                        json=data,
                        params=params
                    )
                    
                    # Handle rate limit (429) with exponential backoff
                    if response.status_code == 429:
                        if attempt < retry_count - 1:
                            wait_time = (2 ** attempt) * 5  # 5s, 10s, 20s
                            error_detail = "Rate limit exceeded"
                            try:
                                error_json = response.json()
                                error_detail = error_json.get('message', error_detail)
                                # Check if response includes retry-after header
                                retry_after = response.headers.get('Retry-After')
                                if retry_after:
                                    wait_time = int(retry_after) + 1
                            except:
                                pass
                            
                            print(f"Rate limit hit. Waiting {wait_time} seconds before retry {attempt + 1}/{retry_count}...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            raise Exception(f"Rate limit exceeded after {retry_count} attempts. Please wait a minute and try again.")
                    
                    response.raise_for_status()
                    return response.json()
                    
            except httpx.HTTPStatusError as e:
                error_detail = "Unknown error"
                try:
                    error_detail = e.response.json()
                except:
                    error_detail = e.response.text
                status_code = e.response.status_code
                
                # Retry on 429 (handled above) or 5xx errors
                if status_code == 429:
                    if attempt < retry_count - 1:
                        wait_time = (2 ** attempt) * 5
                        print(f"Rate limit hit. Waiting {wait_time} seconds before retry {attempt + 1}/{retry_count}...")
                        await asyncio.sleep(wait_time)
                        continue
                
                if status_code >= 500 and attempt < retry_count - 1:
                    wait_time = (2 ** attempt) * 2
                    print(f"Server error {status_code}. Retrying in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                
                if status_code == 401:
                    raise Exception(f"Instantly.ai API authentication failed. Please check your API key. Status: {status_code}, Error: {error_detail}")
                raise Exception(f"Instantly.ai API error (Status {status_code}): {error_detail}")
            except Exception as e:
                if attempt < retry_count - 1 and "Rate limit" not in str(e):
                    wait_time = (2 ** attempt) * 1
                    await asyncio.sleep(wait_time)
                    continue
                raise Exception(f"Request failed: {str(e)}")
        
        raise Exception("Request failed after all retry attempts")
    
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None,
        eaccount: Optional[str] = None
    ) -> dict:
        """Send an email using Instantly.ai API"""
        campaign_data = {
            "name": f"Quick Send - {subject[:50]}",
            "subject": subject,
            "content": html_body if html_body else body,
            "from_name": eaccount or "Email Agent",
            "eaccount": eaccount,
            "campaign_schedule": {
                "schedules": [{
                    "name": "Immediate Send",
                    "timing": {
                        "from": "00:00",
                        "to": "23:59"
                    },
                    "days": {
                        "0": True, "1": True, "2": True, "3": True,
                        "4": True, "5": True, "6": True
                    },
                    "timezone": "UTC"
                }]
            },
            "leads": [
                {
                    "email": to,
                    "first_name": "",
                    "last_name": ""
                }
            ]
        }
        
        try:
            campaign_result = await self._make_request(
                "POST",
                "/api/v2/campaigns",
                data=campaign_data
            )
            
            campaign_id = campaign_result.get("id")
            
            if campaign_id:
                await self._make_request(
                    "POST",
                    f"/api/v2/campaigns/{campaign_id}/activate"
                )
            
            email_id = str(uuid.uuid4())
            return {
                "email_id": email_id,
                "status": "sent",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            raise Exception(f"Failed to send email: {str(e)}")
    
    async def reply_to_email(
        self,
        email_id: str,
        body: str,
        html_body: Optional[str] = None,
        eaccount: Optional[str] = None,
        subject: Optional[str] = None,
        email_data: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Reply to an existing email"""
        # Use provided email_data or fetch it
        if not email_data:
            try:
                email_data = await self.get_email(email_id)
            except Exception as e:
                # If email not found, try using email_id directly as reply_to_uuid
                print(f"Warning: Could not fetch email {email_id}: {e}. Using email_id as reply_to_uuid.")
                email_data = {"id": email_id, "subject": subject or ""}
        
        # Use the email id as reply_to_uuid (not thread_id)
        # The Instantly.ai API expects the email id, not thread_id
        reply_to_uuid = email_data.get("id") or email_id
        
        # Get subject from original email or use provided subject
        reply_subject = subject or email_data.get("subject", "")
        # If subject doesn't start with "Re:", add it
        if reply_subject and not reply_subject.startswith("Re:"):
            reply_subject = f"Re: {reply_subject}"
        
        # Body must be an object with text and/or html properties
        body_obj = {}
        if html_body:
            body_obj["html"] = html_body
        body_obj["text"] = body  # Always include text version
        
        # Get eaccount from email data if not provided
        reply_eaccount = eaccount or email_data.get("eaccount", "")
        
        reply_data = {
            "reply_to_uuid": reply_to_uuid,
            "subject": reply_subject,
            "body": body_obj
        }
        
        # Only include eaccount if we have it (required field)
        if reply_eaccount:
            reply_data["eaccount"] = reply_eaccount
        else:
            raise Exception("eaccount is required for replying. Please provide eaccount.")
        
        try:
            result = await self._make_request(
                "POST",
                "/api/v2/emails/reply",
                data=reply_data
            )
            
            return {
                "success": True,
                "email_id": result.get("id"),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            raise Exception(f"Failed to reply to email: {str(e)}")
    
    async def get_email(self, email_id: str) -> dict:
        """Get a specific email by ID"""
        try:
            result = await self._make_request(
                "GET",
                f"/api/v2/emails/{email_id}"
            )
            return result
        except Exception as e:
            raise Exception(f"Failed to get email: {str(e)}")
    
    async def get_campaigns(self, limit: int = 100, offset: int = 0) -> dict:
        """Get list of campaigns"""
        params = {
            "limit": limit,
            "offset": offset
        }
        try:
            result = await self._make_request(
                "GET",
                "/api/v2/campaigns",
                params=params
            )
            return result
        except Exception as e:
            raise Exception(f"Failed to get campaigns: {str(e)}")
    
    async def get_campaign_by_name(self, campaign_name: str) -> Optional[dict]:
        """Get a campaign by name"""
        try:
            campaigns = await self.get_campaigns(limit=100)
            items = campaigns.get("items", [])
            for campaign in items:
                if campaign.get("name") == campaign_name:
                    return campaign
            return None
        except Exception as e:
            raise Exception(f"Failed to find campaign: {str(e)}")
    
    async def get_all_unread_emails(self, limit: int = 100, offset: int = 0) -> dict:
        """Get all unread emails directly - fastest method (only 1 API call)"""
        params = {
            "limit": limit,
            "offset": offset,
            "is_unread": True  # Get only unread emails
        }
        
        try:
            result = await self._make_request(
                "GET",
                "/api/v2/emails",
                params=params
            )
            return result
        except Exception as e:
            raise Exception(f"Failed to get unread emails: {str(e)}")
    
    async def get_emails_by_campaign(self, campaign_id: str, limit: int = 50, offset: int = 0, is_unread: Optional[bool] = None) -> dict:
        """Get emails from a specific campaign"""
        params = {
            "limit": limit,
            "offset": offset
        }
        if is_unread is not None:
            params["is_unread"] = is_unread  # Send as boolean, not integer
        
        try:
            result = await self._make_request(
                "GET",
                "/api/v2/emails",
                params=params
            )
            # Filter emails by campaign_id
            items = result.get("items", [])
            filtered_items = [email for email in items if email.get("campaign_id") == campaign_id]
            return {
                "items": filtered_items,
                "total": len(filtered_items)
            }
        except Exception as e:
            raise Exception(f"Failed to get emails by campaign: {str(e)}")
