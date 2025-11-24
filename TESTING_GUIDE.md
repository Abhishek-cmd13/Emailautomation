# Testing Guide for Instantly.ai Auto-Reply System

## Prerequisites

1. ✅ Server is running: `http://localhost:8000`
2. ✅ Instantly.ai API key configured in `.env`
3. ✅ OpenAI API key configured in `.env`
4. ✅ Campaign exists: "New AI automation testing campaign"

## Step-by-Step Testing Process

### Step 1: Verify Your Campaign Exists

First, let's check if your campaign is accessible:

```bash
# Check server health
curl http://localhost:8000/health

# You can also check campaigns via Instantly.ai API directly
curl -X GET "https://api.instantly.ai/api/v2/campaigns" \
  -H "Authorization: Bearer YOUR_INSTANTLY_API_KEY" \
  -H "Content-Type: application/json"
```

### Step 2: Send a Test Email from Your Campaign

**In Instantly.ai Dashboard:**
1. Go to your campaign: "New AI automation testing campaign"
2. Make sure the campaign is active and sending emails
3. Wait for a borrower to reply, OR
4. Send a test email to yourself and reply to it from that email

**Alternative: Manual Test Email**
- Send an email from a test account to one of your campaign email accounts
- Reply to that email (this simulates a borrower reply)

### Step 3: Test with Auto-Reply = False (Safe Mode)

**First, test without actually sending replies:**

```bash
curl -X POST 'http://localhost:8000/campaign/process' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "campaign_name": "New AI automation testing campaign",
    "auto_reply": false,
    "borrower_name": null,
    "context": {}
  }'
```

**What to expect:**
- ✅ Returns generated replies without sending them
- ✅ Shows all unread emails found
- ✅ Shows generated replies in the response
- ✅ Status: "generated_only" for each email

**Example Response:**
```json
{
  "success": true,
  "message": "Processed 0 emails from campaign 'New AI automation testing campaign'",
  "campaign_id": "...",
  "campaign_name": "New AI automation testing campaign",
  "total_emails": 1,
  "processed": 0,
  "results": [
    {
      "email_id": "...",
      "lead": "test@example.com",
      "status": "generated_only",
      "reply": "Thank you for reaching out...\n\n• We will...\n\nPlease...\n\nAny query you can whatsapp us on +91 99024 05551."
    }
  ]
}
```

### Step 4: Review Generated Replies

**Check the generated replies:**
- Are they empathetic and warm?
- Do they have bullet points for next steps?
- Do they include the WhatsApp CTA?
- Is the intent classification correct?

**If replies look good, proceed to Step 5.**

### Step 5: Test with Auto-Reply = True (Actual Sending)

**Now test with actual sending enabled:**

```bash
curl -X POST 'http://localhost:8000/campaign/process' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
    "campaign_name": "New AI automation testing campaign",
    "auto_reply": true,
    "borrower_name": null,
    "context": {}
  }'
```

**What to expect:**
- ✅ Replies are actually sent through Instantly.ai
- ✅ Status: "replied" for each email
- ✅ Reply IDs are returned

**Example Response:**
```json
{
  "success": true,
  "message": "Processed 1 emails from campaign 'New AI automation testing campaign'",
  "campaign_id": "...",
  "campaign_name": "New AI automation testing campaign",
  "total_emails": 1,
  "processed": 1,
  "results": [
    {
      "email_id": "...",
      "lead": "test@example.com",
      "status": "replied",
      "reply_id": "..."
    }
  ]
}
```

### Step 6: Verify in Instantly.ai

**Check Instantly.ai Dashboard:**
1. Go to your campaign inbox
2. Look for the sent replies
3. Verify the reply content matches what was generated
4. Check that the reply is properly threaded

## Testing Different Scenarios

### Test Scenario 1: Borrower Asks for Payment Link

**Send this test email:**
```
Subject: Payment Link Request
Body: Hi, I want to close my loan. Please send me the payment link.
```

**Expected AI Reply:**
- Intent: "Asks for payment link"
- Should mention: "within 24 hours", "WhatsApp + email"
- Should include WhatsApp CTA

### Test Scenario 2: Borrower Already Paid

**Send this test email:**
```
Subject: Payment Done
Body: I already made the payment. Here's the screenshot.
```

**Expected AI Reply:**
- Intent: "Already paid" (highest priority)
- Should ask for screenshot + UTR
- Should mention verification within 24 hours

### Test Scenario 3: Borrower Wants to Negotiate

**Send this test email:**
```
Subject: Can you reduce the amount?
Body: The amount is too high. Can you do it for 5000 instead?
```

**Expected AI Reply:**
- Intent: "Negotiation mode (asking for reduction)"
- Should acknowledge the amount
- Should mention checking with lender
- Should include WhatsApp CTA for coordination

### Test Scenario 4: Borrower Provides WhatsApp Number

**Send this test email:**
```
Subject: Contact
Body: My WhatsApp number is +91 98765 43210
```

**Expected AI Reply:**
- Intent: "Provides WhatsApp number"
- Should acknowledge the number
- Should mention dropping a text in 24 hours

## Using the Playground for Testing

**Before testing on actual campaign emails, test in the playground:**

1. Open: `http://localhost:8000/playground`
2. Enter test email content
3. Click "Generate AI Response"
4. Review the generated reply
5. Adjust context if needed
6. Test different scenarios

**Example in Playground:**
- **Borrower Name:** John Doe
- **Subject:** Payment Inquiry
- **Email Body:** "Hi, when is my payment due and how much do I owe?"
- **Context:**
  - Key: `payment_amount`, Value: `500.00`
  - Key: `next_payment_date`, Value: `2024-12-01`

## Troubleshooting

### Issue: "Campaign not found"
**Solution:**
- Verify the exact campaign name (case-sensitive)
- Check that the campaign exists in Instantly.ai
- Ensure your API key has access to the campaign

### Issue: "No unread emails found"
**Solution:**
- Make sure you have unread emails in the campaign
- Check that emails are marked as unread in Instantly.ai
- Verify emails are from the correct campaign

### Issue: "OpenAI API key not configured"
**Solution:**
- Check `.env` file has `OPENAI_API_KEY`
- Restart the server after adding the key
- Verify the key is valid

### Issue: Replies not being sent
**Solution:**
- Check `auto_reply` is set to `true`
- Verify Instantly.ai API key is valid
- Check email account permissions in Instantly.ai

## Monitoring and Logs

**Check server logs:**
```bash
# If running in terminal, you'll see logs directly
# Look for:
# - API requests
# - Error messages
# - Success confirmations
```

**Check API responses:**
- All responses include `timestamp`
- Check `success` field
- Review `results` array for individual email status

## Best Practices

1. **Always test with `auto_reply: false` first**
   - Review generated replies
   - Ensure quality before sending

2. **Start with one email**
   - Test with a single reply first
   - Scale up after confirming it works

3. **Monitor the first few replies**
   - Check in Instantly.ai dashboard
   - Verify replies are appropriate
   - Adjust prompt if needed

4. **Use context when available**
   - Add payment amounts, dates, etc.
   - Makes replies more accurate and helpful

5. **Test different intent categories**
   - Try various borrower scenarios
   - Ensure all intents work correctly

## Quick Test Commands

**Health Check:**
```bash
curl http://localhost:8000/health
```

**Test Generation (No Send):**
```bash
curl -X POST 'http://localhost:8000/campaign/process' \
  -H 'Content-Type: application/json' \
  -d '{"campaign_name": "New AI automation testing campaign", "auto_reply": false}'
```

**Test with Send:**
```bash
curl -X POST 'http://localhost:8000/campaign/process' \
  -H 'Content-Type: application/json' \
  -d '{"campaign_name": "New AI automation testing campaign", "auto_reply": true}'
```

**Test Individual Email (Playground):**
Open browser: `http://localhost:8000/playground`

## Next Steps After Testing

Once testing is successful:

1. **Set up scheduled processing** (optional)
   - Use cron job or scheduler
   - Run every 15-30 minutes
   - Process new unread emails automatically

2. **Monitor performance**
   - Track reply quality
   - Monitor borrower responses
   - Adjust prompts as needed

3. **Scale to other campaigns**
   - Apply to additional campaigns
   - Customize context per campaign if needed

