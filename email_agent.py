import imaplib
import email
import json
import os
import re
import time
import smtplib
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr
from email.header import decode_header
from pathlib import Path
from collections import Counter
import urllib.parse
from html import unescape

import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

# ==================================================
# CONFIGURATION
# ==================================================

USER_NAME = "Sreeja Kurra"
LMSTUDIO_URL = "http://localhost:1234/v1/chat/completions"
LMSTUDIO_MODEL = "local-model"

GMAIL_EMAIL = None
GMAIL_APP_PASSWORD = None
IMAP_SERVER = "imap.gmail.com"

MAX_EMAILS_PER_RUN = 50
DATA_DIR = Path("email_data")
DATA_DIR.mkdir(exist_ok=True)
EMAILS_DB = DATA_DIR / "emails.json"
REPORT_DIR = DATA_DIR / "reports"
REPORT_DIR.mkdir(exist_ok=True)

analysis_in_progress = False
analysis_progress = 0
email_store = None

VALID_CATEGORIES = [
    "Internship", "Interview", "Placement", "Job Offer", 
    "Webinar", "Coding Contest", "Assessment", "Hiring", "Other", "Notification", "Course Promotion"
]

# ==================================================
# PLATFORMS THAT DON'T NEED REPLIES
# ==================================================

NO_REPLY_PLATFORMS = [
    "linkedin", "internshala", "naukri", "indeed", "glassdoor", "monster",
    "timesjobs", "shine.com", "foundit", "apna", "hirect", "unstop",
    "newsletter", "no-reply", "noreply", "notifications", "alerts",
    "udemy", "coursera", "edx", "udacity", "greatlearning", "upgrad",
    "skillshare", "pluralsight", "codecademy", "udemy"
]

# ==================================================
# KEYWORDS THAT INDICATE REPLY IS NEEDED
# ==================================================

REPLY_REQUIRED_KEYWORDS = [
    "please reply", "kindly reply", "reply back", "respond back",
    "kindly confirm", "please confirm", "confirm your", "confirmation",
    "let us know", "let me know", "please let us know", "please let me know",
    "awaiting your response", "awaiting your reply", "looking forward to your response",
    "please share", "could you share", "can you share", "please provide",
    "can you provide", "could you provide", "please send", "please submit",
    "register as soon as possible", "limited seats", "RSVP",
    "please RSVP", "confirm your attendance", "confirm participation",
    "reply to this email", "respond to this email", "get back to us",
    "we need your confirmation", "your response is required",
    "action required", "please take action", "confirm your availability"
]

# Keywords that indicate NO reply needed
NO_REPLY_KEYWORDS = [
    "unsubscribe", "manage your preferences", "view online", "weekly digest",
    "newsletter", "promotion", "advertisement", "sponsored", "marketing email",
    "course recommendation", "bootcamp", "certification course", "enroll now",
    "limited time offer", "discount", "free webinar", "webinar recording"
]

# ==================================================
# HELPER FUNCTIONS
# ==================================================

def clean_html(text: str) -> str:
    if not text:
        return ""
    text = unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def shorten_url(url: str, max_length: int = 40) -> str:
    if len(url) <= max_length:
        return url
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc
        if domain.startswith('www.'):
            domain = domain[4:]
        domain = re.sub(r'\.(com|org|net|in|io|ai|co|edu|gov)$', '', domain)
        path = parsed.path
        if len(path) > 15:
            path = path[:12] + '...'
        short_url = f"{domain}{path}"
        if len(short_url) > max_length:
            short_url = short_url[:max_length-3] + '...'
        return short_url
    except:
        return url[:max_length-3] + '...'

def extract_links_from_text(text: str, max_links: int = 5) -> List[Dict]:
    """Extract unique links and shorten them - NO DUPLICATES"""
    if not text:
        return []
    
    clean_text = clean_html(text)
    url_pattern = r'https?://[^\s<>"\']+|www\.[^\s<>"\']+'
    links = re.findall(url_pattern, clean_text)
    
    # Use dictionary to remove duplicates while preserving order
    unique_links = {}
    for link in links:
        if not link.startswith('http'):
            link = 'https://' + link
        
        # Clean the link - remove tracking parameters
        link = re.sub(r'\?utm_[^&]+(&|$)', '?', link)
        link = re.sub(r'\?$', '', link)
        link = re.sub(r'&$', '', link)
        
        if link not in unique_links:
            unique_links[link] = True
    
    # Convert to list of dicts with shortened URLs
    result = []
    for link in list(unique_links.keys())[:max_links]:
        result.append({
            "full_url": link,
            "short_url": shorten_url(link, 40)
        })
    
    return result

def get_attachment_summary(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    summaries = {
        '.pdf': 'PDF Document', '.docx': 'Word Document', '.doc': 'Word Document',
        '.txt': 'Text File', '.jpg': 'Image', '.jpeg': 'Image', '.png': 'Image',
        '.xlsx': 'Excel Spreadsheet', '.xls': 'Excel Spreadsheet',
        '.zip': 'Zip Archive', '.rar': 'RAR Archive'
    }
    return summaries.get(ext, 'File Attachment')

def decode_subject(subject: str) -> str:
    if not subject:
        return ""
    try:
        decoded_parts = []
        for part, encoding in decode_header(subject):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or 'utf-8', errors='ignore'))
            else:
                decoded_parts.append(str(part))
        return " ".join(decoded_parts).strip()
    except:
        return subject

def extract_body(msg: email.message.Message) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and not part.get_filename():
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode('utf-8', errors='ignore')
                except:
                    pass
            elif content_type == "text/html" and not part.get_filename() and not body:
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        html_content = payload.decode('utf-8', errors='ignore')
                        body = clean_html(html_content)
                except:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode('utf-8', errors='ignore')
                if '<html' in body.lower() or '<div' in body.lower():
                    body = clean_html(body)
        except:
            pass
    return body.strip()

def extract_domain_from_sender(sender: str) -> str:
    match = re.search(r'@([a-zA-Z0-9.-]+)', sender)
    if match:
        domain = match.group(1).lower()
        domain = re.sub(r'^mail\.|^emails\.|^notifications\.|^noreply\.', '', domain)
        return domain
    return ""

def is_notification_email(sender: str, subject: str) -> bool:
    sender_lower = sender.lower()
    subject_lower = subject.lower()
    domain = extract_domain_from_sender(sender)
    
    for platform in NO_REPLY_PLATFORMS:
        if platform in sender_lower or platform in domain:
            return True
    
    if 'noreply' in sender_lower or 'no-reply' in sender_lower:
        return True
    
    notification_keywords = ['weekly', 'digest', 'alert', 'notification', 'update']
    for keyword in notification_keywords:
        if keyword in subject_lower:
            return True
    
    return False

def is_course_promotion(subject: str, body: str) -> bool:
    combined = f"{subject} {body}".lower()
    
    course_keywords = ['course', 'training', 'certification', 'bootcamp', 'masterclass', 
                       'learn', 'upskill', 'enroll', 'fee', 'discount', 'offer',
                       'curriculum', 'module', 'lecture', 'tutorial']
    for keyword in course_keywords:
        if keyword in combined:
            return True
    
    if re.search(r'₹\s?\d{1,5}|Rs\.?\s?\d{1,5}|\$\s?\d{1,3}', combined):
        return True
    
    return False

# ==================================================
# IMPROVED: Action Needed Detection based on keywords
# ==================================================

def should_reply_to_email(subject: str, sender: str, body: str, category: str) -> tuple:
    """Determine if reply is needed based on keywords and context"""
    
    text = f"{subject} {body}".lower()
    sender_lower = sender.lower()
    
    # FIRST: Check for NO reply indicators
    for keyword in NO_REPLY_KEYWORDS:
        if keyword in text:
            return False, f"Marketing/promotion content detected: '{keyword}'"
    
    # Check if from notification platforms
    if is_notification_email(sender, subject):
        return False, "Notification platform - no reply needed"
    
    # Check for course promotions
    if is_course_promotion(subject, body):
        return False, "Course promotion - no reply needed"
    
    # SECOND: Check for positive reply indicators
    for keyword in REPLY_REQUIRED_KEYWORDS:
        if keyword in text:
            return True, f"Reply requested: '{keyword}' found"
    
    # Check for direct questions
    question_patterns = [
        r'(?:can|could|will|would|do|does|is|are)\s+you\s+(?:available|interested|confirm|attend)',
        r'would you be able to',
        r'do you have (?:any questions|time|availability)',
        r'are you (?:interested|available|confirming)',
        r'will you be (?:attending|joining|participating)',
    ]
    for pattern in question_patterns:
        if re.search(pattern, text):
            return True, f"Question detected: '{pattern}'"
    
    # Check for confirmation requests
    if re.search(r'confirm\s+(?:your\s+)?(?:attendance|participation|availability|presence)', text):
        return True, "Confirmation requested"
    
    # Check for registration requests
    if re.search(r'(?:register|sign up|enroll)\s+(?:asap|soon|quickly|now|today)', text):
        return True, "Registration requested with urgency"
    
    # Category-based decision
    if category == "Interview":
        return True, "Interview invitation - reply needed"
    elif category == "Internship" and "application" in text:
        return True, "Internship application - reply needed"
    elif category == "Job Offer":
        return True, "Job offer - reply needed"
    elif category == "Assessment":
        return True, "Assessment - reply needed"
    
    return False, "No reply indicators found"

# ==================================================
# IMPROVED: Context-Aware Reply Generation
# ==================================================

def generate_context_aware_reply(subject: str, sender: str, body: str, category: str, reply_reason: str) -> str:
    """Generate a personalized reply based on the specific email content"""
    
    body_lower = body.lower()
    sender_name = sender.split('<')[0].strip() if '<' in sender else sender
    if '@' in sender_name:
        sender_name = sender_name.split('@')[0]
    
    # Extract date
    date_match = re.search(r'(?:on|for|by)\s+([A-Za-z]+(?:\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})?)', body, re.IGNORECASE)
    date_info = date_match.group(1) if date_match else None
    
    # Extract time
    time_match = re.search(r'(?:at)\s+(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))', body, re.IGNORECASE)
    time_info = time_match.group(1) if time_match else None
    
    # Extract position
    position_match = re.search(r'(?:position|role|job|internship|intern)\s+(?:as|of|for)?\s+["\']?([A-Za-z\s]+?)["\']?', body, re.IGNORECASE)
    position = position_match.group(1).strip() if position_match else None
    
    # Extract event name
    event_match = re.search(r'(?:debugging session|workshop|webinar|event|meeting)\s+(?:called|named|titled)?\s+["\']?([A-Za-z\s]+?)["\']?', body, re.IGNORECASE)
    event_name = event_match.group(1).strip() if event_match else None
    
    # Generate specific reply based on detected patterns
    
    # Registration/RSVP replies
    if 'register' in body_lower or 'rsvp' in body_lower or 'confirm your attendance' in body_lower:
        return f"""Dear {sender_name},

Thank you for the invitation to{f' the {event_name}' if event_name else ''}{f' {category.lower()}' if category else ''}.

I confirm my registration/attendance{f' on {date_info}' if date_info else ''}{f' at {time_info}' if time_info else ''}. Please let me know if there are any additional details I need to provide.

Best regards,
{USER_NAME}"""
    
    # Confirmation replies
    elif 'confirm' in body_lower or 'confirmation' in body_lower:
        return f"""Dear {sender_name},

Thank you for your message.

I confirm my{f' {category.lower()}' if category else ''} participation{f' on {date_info}' if date_info else ''}. I look forward to the{f' {event_name}' if event_name else ''} session.

Please let me know if you need any further information from my end.

Best regards,
{USER_NAME}"""
    
    # Interview replies
    elif 'interview' in category.lower() or 'meeting' in body_lower:
        return f"""Dear {sender_name},

Thank you for scheduling the interview{f' for the {position} position' if position else ''}.

I confirm my availability{f' on {date_info}' if date_info else ''}{f' at {time_info}' if time_info else ''}. Please let me know if there are any materials I should prepare beforehand.

Best regards,
{USER_NAME}"""
    
    # Urgent replies (limited seats, ASAP)
    elif 'as soon as possible' in body_lower or 'limited seats' in body_lower or 'asap' in body_lower:
        return f"""Dear {sender_name},

Thank you for bringing this to my attention. I understand the urgency regarding{f' the {event_name}' if event_name else ''}{f' {category.lower()}' if category else ''}.

I confirm my participation and will complete the required action{f' by {date_info}' if date_info else ''} as requested.

Best regards,
{USER_NAME}"""
    
    # Job offer replies
    elif 'offer' in category.lower():
        return f"""Dear {sender_name},

Thank you very much for the job offer{f' for the {position} position' if position else ''}.

I am excited about this opportunity. Could you please share more details about:
- Compensation and benefits
- Expected start date
- Next steps in the process

I look forward to discussing this further.

Best regards,
{USER_NAME}"""
    
    # Assessment replies
    elif 'assessment' in category.lower() or 'test' in body_lower:
        return f"""Dear {sender_name},

Thank you for sharing the assessment details.

I acknowledge the requirements and will complete the assessment{f' by {date_info}' if date_info else ''}. Please confirm the platform where I should take it.

Best regards,
{USER_NAME}"""
    
    # Default professional reply
    else:
        return f"""Dear {sender_name},

Thank you for your email regarding "{subject[:80]}".

I have reviewed the information and will respond to your request{f' by {date_info}' if date_info else ''}.

Best regards,
{USER_NAME}"""

# ==================================================
# EMAIL DATABASE CLASS
# ==================================================

class EmailDatabase:
    def __init__(self):
        self.emails = []
        self.load_data()
    
    def load_data(self):
        try:
            if EMAILS_DB.exists():
                with open(EMAILS_DB, 'r', encoding='utf-8') as f:
                    self.emails = json.load(f)
                    print(f"✅ Loaded {len(self.emails)} emails")
        except Exception as e:
            print(f"Error loading emails: {e}")
            self.emails = []
    
    def save_data(self):
        try:
            with open(EMAILS_DB, 'w', encoding='utf-8') as f:
                json.dump(self.emails, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving emails: {e}")
    
    def add_emails(self, new_emails: List[Dict]):
        existing_ids = {e.get('email_id') for e in self.emails}
        for email in new_emails:
            if email.get('email_id') not in existing_ids:
                self.emails.insert(0, email)
        self.save_data()
    
    def get_all_emails(self, search: str = None) -> List[Dict]:
        if not search:
            return self.emails
        search_lower = search.lower()
        return [e for e in self.emails if 
                search_lower in e.get('subject', '').lower() or
                search_lower in e.get('sender', '').lower() or
                search_lower in e.get('summary', '').lower()]
    
    def update_email(self, email_id: str, updates: Dict):
        for email in self.emails:
            if email.get('email_id') == email_id:
                email.update(updates)
                self.save_data()
                return True
        return False
    
    def clear_all(self):
        self.emails = []
        self.save_data()
    
    def get_stats(self) -> Dict:
        return {
            "total": len(self.emails),
            "high_priority": sum(1 for e in self.emails if e.get('priority') == 'HIGH'),
            "medium_priority": sum(1 for e in self.emails if e.get('priority') == 'MEDIUM'),
            "low_priority": sum(1 for e in self.emails if e.get('priority') == 'LOW'),
            "action_needed": sum(1 for e in self.emails if e.get('action_needed'))
        }

# ==================================================
# EMAIL ANALYZER
# ==================================================

class EmailAnalyzer:
    def __init__(self):
        self.use_lm_studio = self.check_lm_studio()
    
    def check_lm_studio(self):
        try:
            response = requests.get("http://localhost:1234/v1/models", timeout=2)
            if response.status_code == 200:
                print("✅ LM Studio detected")
                return True
        except:
            pass
        print("⚠️ Using keyword analysis")
        return False
    
    def analyze_email(self, subject: str, sender: str, body: str) -> Dict:
        clean_body = clean_html(body)
        
        # Determine category
        if self.use_lm_studio:
            category, priority, summary = self.get_with_ai(subject, sender, clean_body)
        else:
            category, priority, summary = self.get_with_keywords(subject, clean_body)
        
        # Check if reply is needed using the keyword-based function
        action_needed, action_reason = should_reply_to_email(subject, sender, clean_body, category)
        
        print(f"     Action: {action_needed} - {action_reason}")
        
        return {
            "category": category,
            "priority": priority,
            "summary": summary,
            "action_needed": action_needed,
            "action_reason": action_reason
        }
    
    def get_with_ai(self, subject: str, sender: str, body: str) -> tuple:
        prompt = f"""Analyze this email:

From: {sender[:50]}
Subject: {subject[:100]}
Content: {body[:500]}

Respond EXACTLY:
CATEGORY: [Internship/Interview/Placement/Job Offer/Webinar/Coding Contest/Assessment/Hiring/Other]
PRIORITY: [HIGH/MEDIUM/LOW]
SUMMARY: [One sentence]"""
        
        try:
            response = requests.post(
                LMSTUDIO_URL,
                json={
                    "model": LMSTUDIO_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 150
                },
                timeout=20
            )
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                category, priority, summary = self.parse_response(content)
                if category != "Other":
                    return category, priority, summary
        except:
            pass
        return self.get_with_keywords(subject, body)
    
    def parse_response(self, content: str) -> tuple:
        category = "Other"
        priority = "MEDIUM"
        summary = "Email received"
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith("CATEGORY:"):
                cat = line.replace("CATEGORY:", "").strip()
                if cat in VALID_CATEGORIES:
                    category = cat
            elif line.startswith("PRIORITY:"):
                pri = line.replace("PRIORITY:", "").strip().upper()
                if pri in ["HIGH", "MEDIUM", "LOW"]:
                    priority = pri
            elif line.startswith("SUMMARY:"):
                summary = line.replace("SUMMARY:", "").strip()
                if summary and len(summary) > 10:
                    summary = summary
        return category, priority, summary
    
    def get_with_keywords(self, subject: str, body: str) -> tuple:
        text = f"{subject} {body}".lower()
        
        category = "Other"
        if re.search(r'\b(?:intern|internship)\b', text):
            category = "Internship"
        elif re.search(r'\b(?:interview|meeting|call)\b', text):
            category = "Interview"
        elif re.search(r'\b(?:placement|recruitment|campus drive)\b', text):
            category = "Placement"
        elif re.search(r'\b(?:job|position|hiring|career|opportunity|offer)\b', text):
            category = "Job Offer"
        elif re.search(r'\b(?:webinar|workshop|seminar)\b', text):
            category = "Webinar"
        elif re.search(r'\b(?:coding|hackathon|contest|challenge)\b', text):
            category = "Coding Contest"
        elif re.search(r'\b(?:test|assessment|exam|quiz)\b', text):
            category = "Assessment"
        
        priority = "HIGH" if re.search(r'\b(?:urgent|asap|immediately|deadline|limited seats)\b', text) else "MEDIUM"
        
        sentences = re.split(r'[.!?]+', body)
        first_sentence = ""
        for sent in sentences[:3]:
            sent = sent.strip()
            if len(sent) > 30 and not sent.startswith('http'):
                first_sentence = sent[:120]
                break
        
        summary = first_sentence if first_sentence else f"{category}: {subject[:100]}"
        
        return category, priority, summary
    
    def generate_reply(self, email: Dict) -> Optional[str]:
        if not email.get('action_needed', False):
            return None
        
        subject = email.get('subject', '')
        sender = email.get('sender', '')
        body = email.get('body', '')
        category = email.get('category', 'Other')
        action_reason = email.get('action_reason', '')
        
        # Use AI if available
        if self.use_lm_studio:
            prompt = f"""Write a personalized reply to this email.

Original Email:
From: {sender}
Subject: {subject}
Content: {body[:600]}

Category: {category}
Why reply is needed: {action_reason}

Write a natural, specific reply addressing the email's content.
Sign with "Best regards,\n{USER_NAME}" """
            
            try:
                response = requests.post(
                    LMSTUDIO_URL,
                    json={
                        "model": LMSTUDIO_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.7,
                        "max_tokens": 400
                    },
                    timeout=25
                )
                if response.status_code == 200:
                    reply = response.json()["choices"][0]["message"]["content"]
                    if len(reply) > 80:
                        return reply.strip()
            except:
                pass
        
        return generate_context_aware_reply(subject, sender, body, category, action_reason)

# ==================================================
# EMAIL FETCHING AND PROCESSING
# ==================================================

def fetch_and_process_emails():
    global analysis_in_progress, analysis_progress, email_store, GMAIL_EMAIL, GMAIL_APP_PASSWORD
    
    print("\n" + "="*60)
    print(f"📧 Processing - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    if not GMAIL_EMAIL or not GMAIL_APP_PASSWORD:
        print("❌ Not logged in!")
        analysis_in_progress = False
        return
    
    try:
        print(f"📡 Connecting to {GMAIL_EMAIL}...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        mail.select("INBOX")
        
        status, messages = mail.search(None, "UNSEEN")
        email_ids = messages[0].split()
        total_unread = len(email_ids)
        
        print(f"📨 Unread: {total_unread}")
        
        if total_unread == 0:
            print("📭 No new emails")
            analysis_in_progress = False
            mail.logout()
            return
        
        to_process = min(MAX_EMAILS_PER_RUN, total_unread)
        processed_emails = []
        analyzer = EmailAnalyzer()
        
        for idx, email_id in enumerate(email_ids[:to_process]):
            try:
                print(f"\n  [{idx+1}/{to_process}] Fetching...")
                status, msg_data = mail.fetch(email_id, "(RFC822)")
                
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        subject = decode_subject(msg.get("Subject", ""))
                        sender = msg.get("From", "")
                        full_body = extract_body(msg)
                        
                        print(f"     Subject: {subject[:60]}...")
                        print(f"     From: {sender[:40]}...")
                        
                        # Extract unique links (no duplicates)
                        links = extract_links_from_text(full_body, max_links=5)
                        
                        attachments = []
                        if msg.is_multipart():
                            for part in msg.walk():
                                filename = part.get_filename()
                                if filename:
                                    attachments.append({
                                        "name": filename,
                                        "summary": get_attachment_summary(filename)
                                    })
                        
                        print(f"     Analyzing...")
                        analysis = analyzer.analyze_email(subject, sender, full_body)
                        
                        print(f"     📊 {analysis['category']} | {analysis['priority']}")
                        print(f"     ✉️ Action: {'YES - ' + analysis['action_reason'] if analysis['action_needed'] else 'NO'}")
                        print(f"     🔗 Links found: {len(links)}")
                        
                        body_preview = clean_html(full_body[:250]) + ("..." if len(full_body) > 250 else "")
                        
                        # Generate reply if action needed
                        ai_reply = None
                        if analysis['action_needed']:
                            ai_reply = analyzer.generate_reply({
                                "subject": subject,
                                "sender": sender,
                                "body": full_body,
                                "category": analysis['category'],
                                "action_reason": analysis['action_reason']
                            })
                            if ai_reply:
                                print(f"     ✅ Reply generated")
                        
                        email_data = {
                            "email_id": email_id.decode() if isinstance(email_id, bytes) else str(email_id),
                            "subject": subject,
                            "sender": sender,
                            "date": msg.get("Date", ""),
                            "body": full_body[:3000],
                            "body_preview": body_preview,
                            "links": links,
                            "attachments": attachments,
                            "category": analysis["category"],
                            "priority": analysis["priority"],
                            "summary": analysis["summary"],
                            "action_needed": analysis["action_needed"],
                            "action_reason": analysis.get("action_reason", ""),
                            "ai_reply": ai_reply,
                            "processed_at": datetime.now().isoformat(),
                            "replied": False
                        }
                        processed_emails.append(email_data)
                
                analysis_progress = int(((idx + 1) / to_process) * 100)
                time.sleep(0.5)
                
            except Exception as e:
                print(f"     ❌ Error: {e}")
        
        mail.logout()
        
        if processed_emails:
            email_store.add_emails(processed_emails)
            print(f"\n✅ Saved {len(processed_emails)} emails")
            generate_report(processed_emails, total_unread)
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        analysis_in_progress = False
        analysis_progress = 100
        print("\n" + "="*60 + "\n")

def generate_report(emails: List[Dict], total_unread: int):
    timestamp = datetime.now()
    report_file = REPORT_DIR / f"report_{timestamp.strftime('%Y%m%d_%H%M%S')}.txt"
    
    priority_counts = Counter(e.get('priority', 'LOW') for e in emails)
    category_counts = Counter(e.get('category', 'Other') for e in emails)
    
    report = f"""
EMAIL SORTER BOT - ANALYSIS REPORT
{'='*60}

Date: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}
Total unread: {total_unread}
Processed: {len(emails)}

PRIORITIES:
  HIGH: {priority_counts.get('HIGH', 0)}
  MEDIUM: {priority_counts.get('MEDIUM', 0)}
  LOW: {priority_counts.get('LOW', 0)}

CATEGORIES:
"""
    for cat, count in category_counts.most_common():
        report += f"  {cat}: {count}\n"
    
    report += f"\nREPLIES NEEDED:\n{'-'*40}\n"
    for i, e in enumerate([e for e in emails if e.get('action_needed')], 1):
        report += f"\n{i}. [{e.get('category')}] {e.get('subject', '')[:70]}\n   From: {e.get('sender', '')[:50]}\n   Reason: {e.get('action_reason', '')}\n"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    with open(REPORT_DIR / "latest_report.txt", 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"📄 Report: {report_file}")

# ==================================================
# FASTAPI APP
# ==================================================

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

class LoginRequest(BaseModel):
    email: str
    app_password: str

class ReplyRequest(BaseModel):
    email_id: str
    reply_text: str

class GenerateReplyRequest(BaseModel):
    email_id: str

email_store = EmailDatabase()

@app.get("/")
@app.get("/frontend")
async def serve_frontend():
    return FileResponse("frontend.html")

@app.post("/api/login")
async def login(request: LoginRequest):
    global GMAIL_EMAIL, GMAIL_APP_PASSWORD
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(request.email, request.app_password)
        mail.select("INBOX")
        mail.logout()
        GMAIL_EMAIL = request.email
        GMAIL_APP_PASSWORD = request.app_password
        return {"success": True, "email": request.email}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/logout")
async def logout():
    global GMAIL_EMAIL, GMAIL_APP_PASSWORD
    GMAIL_EMAIL = None
    GMAIL_APP_PASSWORD = None
    return {"success": True}

@app.get("/api/check-session")
async def check_session():
    if GMAIL_EMAIL:
        return {"logged_in": True, "email": GMAIL_EMAIL}
    return {"logged_in": False}

@app.post("/api/analyze")
async def start_analysis(background_tasks: BackgroundTasks):
    global analysis_in_progress
    if not GMAIL_EMAIL:
        raise HTTPException(status_code=401, detail="Not logged in")
    if analysis_in_progress:
        return {"status": "already_running"}
    analysis_in_progress = True
    analysis_progress = 0
    background_tasks.add_task(fetch_and_process_emails)
    return {"status": "started"}

@app.get("/api/status")
async def get_status():
    return {"in_progress": analysis_in_progress, "progress": analysis_progress}

@app.get("/api/emails")
async def get_emails(search: str = "", limit: int = 100):
    if not GMAIL_EMAIL:
        raise HTTPException(status_code=401, detail="Not logged in")
    emails = email_store.get_all_emails(search=search if search else None)
    return {"emails": emails[:limit], "total": len(emails)}

@app.get("/api/stats")
async def get_stats():
    if not GMAIL_EMAIL:
        raise HTTPException(status_code=401, detail="Not logged in")
    return email_store.get_stats()

@app.post("/api/generate-reply")
async def generate_reply(request: GenerateReplyRequest):
    if not GMAIL_EMAIL:
        raise HTTPException(status_code=401, detail="Not logged in")
    emails = email_store.get_all_emails()
    email = next((e for e in emails if e.get('email_id') == request.email_id), None)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    if email.get('ai_reply'):
        return {"reply": email['ai_reply']}
    analyzer = EmailAnalyzer()
    reply = analyzer.generate_reply(email)
    if reply:
        email_store.update_email(request.email_id, {"ai_reply": reply})
        return {"reply": reply}
    return {"reply": "No reply needed for this email"}

@app.post("/api/send-reply")
async def send_reply(request: ReplyRequest):
    global GMAIL_EMAIL, GMAIL_APP_PASSWORD
    if not GMAIL_EMAIL:
        raise HTTPException(status_code=401, detail="Not logged in")
    emails = email_store.get_all_emails()
    email = next((e for e in emails if e.get('email_id') == request.email_id), None)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    try:
        sender_email = parseaddr(email.get('sender', ''))[1]
        msg = MIMEMultipart()
        msg["From"] = GMAIL_EMAIL
        msg["To"] = sender_email
        msg["Subject"] = f"Re: {email.get('subject', '')}"
        msg.attach(MIMEText(request.reply_text, "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        email_store.update_email(request.email_id, {"replied": True, "replied_at": datetime.now().isoformat()})
        return {"success": True, "message": "Reply sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/clear")
async def clear_data():
    if not GMAIL_EMAIL:
        raise HTTPException(status_code=401, detail="Not logged in")
    email_store.clear_all()
    return {"success": True}

@app.get("/api/reports")
async def get_reports():
    if not GMAIL_EMAIL:
        raise HTTPException(status_code=401, detail="Not logged in")
    reports = []
    for report_file in sorted(REPORT_DIR.glob("*.txt"), reverse=True)[:10]:
        reports.append({"name": report_file.name, "modified": datetime.fromtimestamp(report_file.stat().st_mtime).isoformat()})
    return {"reports": reports}

@app.get("/api/report/{report_name}")
async def get_report(report_name: str):
    if not GMAIL_EMAIL:
        raise HTTPException(status_code=401, detail="Not logged in")
    report_path = REPORT_DIR / report_name
    if report_path.exists():
        with open(report_path, 'r', encoding='utf-8') as f:
            return {"content": f.read()}
    raise HTTPException(status_code=404, detail="Report not found")

# ==================================================
# MAIN
# ==================================================

def get_credentials():
    print("\n" + "="*60)
    print("📧 EMAIL SORTER BOT")
    print("="*60)
    print("\n⚠️  Get App Password from Google Account → Security → App Passwords\n")
    email = input("📧 Gmail address: ").strip()
    password = input("🔑 App Password: ").strip()
    return email, password

def main():
    global GMAIL_EMAIL, GMAIL_APP_PASSWORD
    email, password = get_credentials()
    if not email or not password:
        print("❌ Required!")
        return
    GMAIL_EMAIL = email
    GMAIL_APP_PASSWORD = password
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(GMAIL_EMAIL, GMAIL_APP_PASSWORD)
        mail.select("INBOX")
        mail.logout()
        print("\n✅ Connected!\n")
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        return
    print("="*60)
    print(f"👤 {USER_NAME}")
    print("🚀 http://localhost:8000/frontend")
    print("="*60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()