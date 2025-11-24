"""
AI-powered auto-reply generator for Riverline borrower communications using OpenAI GPT
"""
from typing import Optional, Dict, Any
from datetime import datetime
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

class BorrowerAutoReplyGenerator:
    """Generate AI-powered auto-replies for Riverline borrower emails using GPT"""
    
    def __init__(
        self, 
        company_name: str = "Riverline",
        support_email: str = "support@riverline.com",
        model: str = "gpt-4o"
    ):
        self.company_name = company_name
        self.support_email = support_email
        self.model = model
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables. Please set it in your .env file.")
        self.client = AsyncOpenAI(api_key=api_key)
    
    def _build_system_prompt(self) -> str:
        """Build the system prompt for Riverline borrower support"""
        return """You are Riverline's empathetic borrower-support assistant. Read ONLY the borrower's latest message in the email thread and respond with warmth, clarity, certainty, and one clear next step. Your goal: help borrowers feel safe, respected, and guided, while ensuring accurate next steps based on their intent. ALWAYS include the secondary CTA: 'Any query you can whatsapp us on +91 99024 05551.' Never mention categories, classification, rules, or internal logic. Never sound legalistic, threatening, or robotic. Always be supportive, calm, and human. Use simple language. Replies must be 3–5 warm lines with a single primary CTA plus the required secondary CTA."""
    
    def _build_user_prompt(
        self,
        email_body: str,
        subject: str = "",
        borrower_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build the user prompt with intent classification and response generation"""
        
        borrower_name = borrower_name or context.get("borrower_name") or "Valued Borrower"
        
        priority_order = [
            "Already paid",
            "Asks for payment link",
            "Provides WhatsApp number",
            "Wants a call / wants to discuss",
            "Committed to pay (no negotiation)",
            "Negotiation mode (asking for reduction)",
            "Wants to pay lower amount (counter-offer)",
            "Extreme financial stress but committed",
            "Can't pay this month but can pay next month",
            "Needs 1 month time / unclear timeline",
            "Wants partial payment option (some now, rest later)",
            "Wants reduction + more time",
            "Does not know which loan",
            "Thinks Riverline is fraud",
            "Emotional / wants understanding",
            "Needs steps / confused about process",
            "Wants draft NOC"
        ]
        
        categories = {
            "Already paid": [
                "Borrower says payment is done",
                "Borrower sends screenshot",
                "Borrower says 'I already paid'"
            ],
            "Asks for payment link": [
                "Share the link",
                "Send link",
                "I want to close now",
                "Please provide payment link"
            ],
            "Committed to pay (no negotiation)": [
                "I will pay",
                "I accept settlement",
                "I want to pay full amount",
                "I want to close",
                "I want to pay the due amount (not settlement)"
            ],
            "Negotiation mode (asking for reduction)": [
                "Do it for 5000",
                "Can you reduce more",
                "This amount is too high",
                "Extremely low offers (e.g., settle 6500 → 2000)"
            ],
            "Wants to pay lower amount (counter-offer)": [
                "I can pay X",
                "I can afford only X",
                "I propose X"
            ],
            "Extreme financial stress but committed": [
                "Family issues",
                "Legal seizure",
                "Unable to manage daily expenses",
                "But still wants to resolve loan"
            ],
            "Can't pay this month but can pay next month": [
                "Salary delay",
                "Will pay next month",
                "Cannot pay this month"
            ],
            "Needs 1 month time / unclear timeline": [
                "Give me one month",
                "Not possible now",
                "I need time but no clear date"
            ],
            "Wants partial payment option (some now, rest later)": [
                "I can pay some now",
                "I cannot commit a date but can pay a part"
            ],
            "Wants reduction + more time": [
                "Lower the amount and give me time",
                "I want both reduction + future date"
            ],
            "Wants a call / wants to discuss": [
                "Call me",
                "I want to discuss something",
                "Here is my number",
                "Call on",
                "Call me on",
                "Please call"
            ],
            "Provides WhatsApp number": [
                "WhatsApp on",
                "Whatsapp on",
                "WhatsApp me on",
                "Whatsapp me on",
                "My WhatsApp",
                "WhatsApp number"
            ],
            "Does not know which loan": [
                "Which loan is this?",
                "I never took this loan",
                "Please provide loan proof"
            ],
            "Thinks Riverline is fraud": [
                "You are fraud",
                "This is scam",
                "I won't pay even 1 rupee"
            ],
            "Emotional / wants understanding": [
                "Please understand my situation",
                "I am struggling",
                "General emotional sharing"
            ],
            "Needs steps / confused about process": [
                "Explain steps",
                "What happens next?",
                "How does settlement work?"
            ],
            "Wants draft NOC": [
                "Send NOC",
                "I need closure letter",
                "Give me proof of closure"
            ]
        }
        
        actions = {
            "Already paid": {
                "next_steps": [
                    "Thank them warmly.",
                    "Ask for payment screenshot + UTR.",
                    "Promise verification within 24 hours.",
                    "Explain NOC will follow after payment clears. Do NOT mention any timeline for NOC."
                ],
                "primary_cta": "Please share the payment screenshot and UTR so we can verify and update you today."
            },
            "Asks for payment link": {
                "next_steps": [
                    "Acknowledge their intent.",
                    "Tell them the payment link will be requested from lender within 24 hours.",
                    "Tell them link will be sent on WhatsApp + email.",
                    "Offer a call if they want clarity."
                ],
                "primary_cta": "Please tell me if you'd also like a call when we share the link."
            },
            "Committed to pay (no negotiation)": {
                "next_steps": [
                    "Thank them for confirming.",
                    "Tell them link will be requested within 24 hours.",
                    "Tell them link will arrive via WhatsApp + email.",
                    "Offer optional call."
                ],
                "primary_cta": "Please let me know if you'd like a quick call or if receiving the link on WhatsApp is fine."
            },
            "Negotiation mode (asking for reduction)": {
                "next_steps": [
                    "Acknowledge the requested amount.",
                    "Tell them Riverline will check with lender.",
                    "Promise revert within 24 hours.",
                    "Ask them to WhatsApp for faster coordination."
                ],
                "primary_cta": "Please WhatsApp us on +91 99024 05551 so we can coordinate this quickly."
            },
            "Wants to pay lower amount (counter-offer)": {
                "next_steps": [
                    "Acknowledge their amount offer.",
                    "Tell them you will check with lender.",
                    "Promise a decision within 24 hours.",
                    "Inform they will receive updates on WhatsApp + email."
                ],
                "primary_cta": "Please confirm if this is the final amount you want us to check with the lender."
            },
            "Extreme financial stress but committed": {
                "next_steps": [
                    "Respond with deep empathy.",
                    "Offer a call with a senior advisor to help plan.",
                    "Ask for a realistic timeline they can manage."
                ],
                "primary_cta": "Would you like a senior advisor to speak with you and help plan something manageable?"
            },
            "Can't pay this month but can pay next month": {
                "next_steps": [
                    "Acknowledge their situation.",
                    "Ask for their phone number.",
                    "Ask for a realistic date next month."
                ],
                "primary_cta": "Please share your number and a realistic date so we can plan accordingly."
            },
            "Needs 1 month time / unclear timeline": {
                "next_steps": [
                    "Acknowledge their request.",
                    "Ask for exact date after one month.",
                    "Show calm reassurance."
                ],
                "primary_cta": "Please let me know the exact date so we can plan the next steps properly."
            },
            "Wants partial payment option (some now, rest later)": {
                "next_steps": [
                    "Acknowledge their partial-payment intent.",
                    "Ask how much they can pay today.",
                    "Explain settlement ideally needs one-time payment.",
                    "Offer a call."
                ],
                "primary_cta": "Please tell me how much you can pay today so I can guide you properly."
            },
            "Wants reduction + more time": {
                "next_steps": [
                    "Acknowledge their situation.",
                    "Ask for their number.",
                    "Tell them you will coordinate both amount + timeline with lender.",
                    "Promise revert in 24 hours."
                ],
                "primary_cta": "Please share your number so we can coordinate the amount and timeline with the lender."
            },
            "Wants a call / wants to discuss": {
                "next_steps": [
                    "Acknowledge their request.",
                    "Ask what would be a good time to call.",
                    "Reassure the call will be calm.",
                    "Offer WhatsApp chat too."
                ],
                "primary_cta": "What would be a good time to call?"
            },
            "Provides WhatsApp number": {
                "next_steps": [
                    "Acknowledge their WhatsApp number.",
                    "Tell them you will drop a text in 24 hours.",
                    "Reassure they will receive the link or information via WhatsApp."
                ],
                "primary_cta": "Sure we will drop you a text in 24 hours."
            },
            "Does not know which loan": {
                "next_steps": [
                    "Share NBFC name and partner platform.",
                    "Share last 4 digits of loan ID if available.",
                    "Offer to verify details on call."
                ],
                "primary_cta": "Please let me know if you'd like a call to verify all loan details clearly."
            },
            "Thinks Riverline is fraud": {
                "next_steps": [
                    "Stay calm and non-defensive.",
                    "Share NBFC name and lending partner.",
                    "Offer verification steps.",
                    "Offer a call for clarity."
                ],
                "primary_cta": "Would you like us to help verify your loan details on a short call?"
            },
            "Emotional / wants understanding": {
                "next_steps": [
                    "Respond with warmth and empathy.",
                    "Offer a supportive call.",
                    "Ask for a timeline that feels manageable."
                ],
                "primary_cta": "What timeline feels comfortable for you so we can plan gently around it?"
            },
            "Needs steps / confused about process": {
                "next_steps": [
                    "Explain simple 3-step closure process:",
                    "1) Confirm intent",
                    "2) Lender shares payment link",
                    "3) Payment → Closure + NOC",
                    "Offer a call."
                ],
                "primary_cta": "Would you like a call where we explain everything calmly?"
            },
            "Wants draft NOC": {
                "next_steps": [
                    "Explain NOC is issued after payment clears.",
                    "Do NOT mention any timeline for NOC.",
                    "Offer payment link."
                ],
                "primary_cta": "Would you like me to send the payment link so the closure and NOC process can start?"
            }
        }
        
        # Build context info if available
        context_info = ""
        if context:
            context_parts = []
            for key, value in context.items():
                if value is not None:
                    if isinstance(value, float):
                        context_parts.append(f"{key.replace('_', ' ').title()}: ${value:,.2f}")
                    else:
                        context_parts.append(f"{key.replace('_', ' ').title()}: {value}")
            if context_parts:
                context_info = f"\n\nAdditional Context:\n" + "\n".join(context_parts)
        
        # Format categories for display
        categories_text = []
        for cat, examples in categories.items():
            categories_text.append(f"{cat}: {', '.join(examples)}")
        
        user_prompt = f"""STEP 1 - INTENT CLASSIFICATION:
Classify the borrower's LAST message in the email thread into exactly ONE of these intents. Use the priority order below. Even if multiple intents appear, choose the most relevant/highest priority intent.

Priority Order (highest to lowest):
{', '.join(priority_order)}

Category Examples:
{chr(10).join(categories_text)}

Borrower Name: {borrower_name}
Email Subject: {subject}
Email Content: {email_body}{context_info}

STEP 2 - GENERATE RESPONSE:
Based on the classified intent, generate a response using the EXACT action rules below. The response must be:
- 3-5 warm, empathetic lines (format next steps as concise bullet points)
- Always give clear certainty about next steps (use bullet points for clarity)
- Format next steps as concise bullet points, not long paragraphs
- End with ONE primary CTA from the action rules
- After the primary CTA, ALWAYS add: "Any query you can whatsapp us on +91 99024 05551."
- Do NOT output category names
- Do NOT mention classification, logic, rules, internal system, or AI
- Do NOT pressure or sound legalistic
- NEVER commit any timeline for NOC issuance. Do not mention days, weeks, or any time period for NOC
- Use simple language, be supportive, calm, and human

Action Rules:
{self._format_actions(actions)}

STEP 3 - OUTPUT:
Output ONLY the email body. No labels, no JSON, no explanations. Just the warm, empathetic reply with certainty (using bullet points for next steps), primary CTA, and WhatsApp CTA."""
        
        return user_prompt
    
    def _format_actions(self, actions: Dict[str, Dict]) -> str:
        """Format actions dictionary into readable text with bullet points"""
        formatted = []
        for category, details in actions.items():
            formatted.append(f"\n{category}:")
            formatted.append("  Next Steps (format as bullet points in response):")
            for step in details['next_steps']:
                formatted.append(f"    • {step}")
            formatted.append(f"  Primary CTA: {details['primary_cta']}")
        return "\n".join(formatted)
    
    async def generate_ai_reply(
        self,
        email_body: str,
        subject: str = "",
        borrower_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """Generate an AI-powered email reply using GPT with Riverline's prompt structure"""
        
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            email_body=email_body,
            subject=subject,
            borrower_name=borrower_name,
            context=context
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            ai_reply = response.choices[0].message.content.strip()
            
            return {
                "reply": ai_reply,
                "model": self.model,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            raise Exception(f"Failed to generate AI reply: {str(e)}")
    
    async def generate_auto_reply(
        self,
        email_body: str,
        subject: str = "",
        borrower_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """Generate AI-powered auto-reply based on email content"""
        return await self.generate_ai_reply(
            email_body=email_body,
            subject=subject,
            borrower_name=borrower_name,
            context=context
        )
