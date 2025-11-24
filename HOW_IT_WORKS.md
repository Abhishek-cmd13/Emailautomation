# How the Email Auto-Reply System Works

## Overview
This system automatically generates and sends AI-powered replies to borrower emails from your Instantly.ai campaign "New AI automation testing campaign".

## System Architecture

```
┌─────────────────┐
│  Instantly.ai   │
│    Campaign     │
│  (Sends emails) │
└────────┬────────┘
         │
         │ Borrower replies
         ▼
┌─────────────────┐
│  Instantly.ai   │
│  Email Inbox    │
│  (Receives)     │
└────────┬────────┘
         │
         │ API Call
         ▼
┌─────────────────┐
│  FastAPI Server │
│  /campaign/     │
│  process        │
└────────┬────────┘
         │
         │ 1. Fetch unread emails
         │ 2. For each email:
         ▼
┌─────────────────┐
│  OpenAI GPT-4o  │
│  (AI Generator)  │
└────────┬────────┘
         │
         │ Generate reply using
         │ Riverline prompt
         ▼
┌─────────────────┐
│  Instantly.ai   │
│  Reply API      │
│  (Sends reply)  │
└─────────────────┘
```

## Step-by-Step Workflow

### 1. **Campaign Setup in Instantly.ai**
   - You have a campaign named "New AI automation testing campaign"
   - This campaign sends emails to borrowers
   - When borrowers reply, those replies appear in Instantly.ai inbox

### 2. **Trigger the Auto-Reply Process**
   You call the API endpoint:
   ```bash
   POST http://localhost:8000/campaign/process
   {
     "campaign_name": "New AI automation testing campaign",
     "auto_reply": true
   }
   ```

### 3. **System Processing**
   The system:
   
   a. **Finds Your Campaign**
      - Searches Instantly.ai for campaign with name "New AI automation testing campaign"
      - Gets the campaign ID
   
   b. **Fetches Unread Emails**
      - Gets all unread emails from that campaign
      - Filters to only received emails (not sent emails)
   
   c. **For Each Email:**
      - Extracts email content, subject, and borrower info
      - Sends to OpenAI GPT-4o with your Riverline prompt
      - AI classifies intent (e.g., "Wants payment link", "Already paid", etc.)
      - AI generates empathetic, warm reply with:
        * Clear next steps (as bullet points)
        * Primary CTA
        * Secondary CTA: "Any query you can whatsapp us on +91 99024 05551"
      - Sends the reply back through Instantly.ai

### 4. **Response Format**
   Returns summary:
   ```json
   {
     "success": true,
     "campaign_name": "New AI automation testing campaign",
     "total_emails": 5,
     "processed": 5,
     "results": [
       {
         "email_id": "...",
         "lead": "borrower@example.com",
         "status": "replied",
         "reply_id": "..."
       }
     ]
   }
   ```

## Example Scenarios

### Scenario 1: Borrower Asks for Payment Link
**Borrower Email:**
> "Hi, I want to close my loan. Please send me the payment link."

**AI Processing:**
1. Classifies intent: "Asks for payment link" (Priority #2)
2. Uses action rules for this intent
3. Generates reply with bullet points:
   - • We will request the payment link from lender within 24 hours
   - • The link will be sent on WhatsApp + email
   - • We can offer a call if you want clarity
4. Adds CTAs

**AI Reply:**
> "Thank you for confirming your intent to close the loan.
> 
> • We will request the payment link from the lender within 24 hours
> • The link will be sent to you on WhatsApp and email
> • We can offer a call if you'd like clarity on the process
> 
> Please tell me if you'd also like a call when we share the link.
> 
> Any query you can whatsapp us on +91 99024 05551."

### Scenario 2: Borrower Already Paid
**Borrower Email:**
> "I already made the payment. Here's the screenshot."

**AI Processing:**
1. Classifies intent: "Already paid" (Priority #1 - highest)
2. Uses action rules for "Already paid"
3. Generates reply asking for screenshot + UTR

**AI Reply:**
> "Thank you for making the payment!
> 
> • We need the payment screenshot and UTR for verification
> • We will verify within 24 hours
> • NOC will follow after payment clears
> 
> Please share the payment screenshot and UTR so we can verify and update you today.
> 
> Any query you can whatsapp us on +91 99024 05551."

## Intent Classification Priority

The AI uses this priority order (highest to lowest):
1. Already paid
2. Asks for payment link
3. Provides WhatsApp number
4. Wants a call / wants to discuss
5. Committed to pay (no negotiation)
6. Negotiation mode (asking for reduction)
7. ... and so on

## Key Features

### ✅ Automatic Intent Detection
- AI automatically detects what the borrower wants
- Uses 17 different intent categories
- Chooses highest priority if multiple intents detected

### ✅ Context-Aware Replies
- Can include additional context (payment amounts, dates, etc.)
- Personalizes responses with borrower name
- Uses loan-specific information when available

### ✅ Empathetic Tone
- Warm, human, non-judgmental
- Supportive and calm
- Never sounds legalistic or threatening

### ✅ Clear Next Steps
- Always provides certainty about what happens next
- Uses bullet points for easy reading
- Includes specific timelines (e.g., "within 24 hours")

### ✅ Consistent CTAs
- Primary CTA based on intent
- Always includes WhatsApp CTA: "+91 99024 05551"

## Usage Options

### Option 1: Manual Processing
Call the endpoint when you want to process emails:
```bash
curl -X POST http://localhost:8000/campaign/process \
  -H "Content-Type: application/json" \
  -d '{"campaign_name": "New AI automation testing campaign"}'
```

### Option 2: Scheduled Processing (Future)
You can set up a cron job or scheduler to call this endpoint periodically:
```bash
# Run every 15 minutes
*/15 * * * * curl -X POST http://localhost:8000/campaign/process -H "Content-Type: application/json" -d '{"campaign_name": "New AI automation testing campaign"}'
```

### Option 3: Webhook Integration (Future)
Instantly.ai can send webhooks when new emails arrive, triggering automatic replies.

## Testing

### Test Individual Email
Use the playground: `http://localhost:8000/playground`
- Enter email content
- See AI-generated reply
- Test different scenarios

### Test Campaign Processing
```bash
# Process campaign (dry run - generates but doesn't send)
curl -X POST http://localhost:8000/campaign/process \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_name": "New AI automation testing campaign",
    "auto_reply": false
  }'

# Process and actually send replies
curl -X POST http://localhost:8000/campaign/process \
  -H "Content-Type: application/json" \
  -d '{
    "campaign_name": "New AI automation testing campaign",
    "auto_reply": true
  }'
```

## Important Notes

1. **Only Unread Emails**: The system only processes unread emails to avoid duplicate replies
2. **Only Received Emails**: Skips sent emails (ue_type == 1), only processes received emails
3. **No NOC Timelines**: AI never mentions specific timelines for NOC issuance
4. **3-5 Lines**: Replies are kept concise (3-5 warm lines)
5. **Bullet Points**: Next steps are formatted as bullet points for clarity

## Configuration

Make sure your `.env` file has:
```env
INSTANTLY_API_KEY=your-key-here
INSTANTLY_API_URL=https://api.instantly.ai/api/v2
OPENAI_API_KEY=your-openai-key-here
```

## Monitoring

Check the response from `/campaign/process` to see:
- How many emails were found
- How many were successfully processed
- Any errors that occurred
- Individual email status

