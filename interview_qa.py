from fpdf import FPDF

def s(text):
    """Sanitize text to latin-1 compatible characters."""
    return (text
        .replace('\u2014', '--')   # em dash
        .replace('\u2013', '-')    # en dash
        .replace('\u2019', "'")    # right single quote
        .replace('\u2018', "'")    # left single quote
        .replace('\u201c', '"')    # left double quote
        .replace('\u201d', '"')    # right double quote
        .replace('\u2022', '*')    # bullet
        .replace('\u00e9', 'e')    # e accent (just in case)
    )

class PDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(80, 80, 80)
        self.cell(0, 8, "Technical Interview - Questions & Answers", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, f"Page {self.page_no()}", align="C")

pdf = PDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()
pdf.set_margins(20, 20, 20)

BLUE = (31, 73, 125)
DARK = (40, 40, 40)
GRAY = (90, 90, 90)

sections = [
    {
        "num": "1",
        "question": "Recent Technical Engagement",
        "subtitle": "Can you walk us through your most recent technical engagement or client project? Please describe the business stakes involved, the challenges you faced, and the outcomes you achieved.",
        "answer": [
            ("Structure: Context -> Stakes -> Challenges -> Actions -> Outcome", "italic"),
            ("", None),
            ('"In my last engagement, I was brought in to [stabilize / migrate / design] a [system/platform] for a [sector] client with [X] users / [Y]M transactions per day.', "body"),
            ("The business stakes were high: [SLA commitments / revenue impact / regulatory deadline].", "body"),
            ("The main challenge was [legacy dependencies / lack of documentation / team silos].", "body"),
            ("I led [specific actions: root cause analysis, architecture redesign, war room coordination].", "body"),
            ('We delivered [quantified result: 40% latency reduction / zero downtime migration / on-time go-live]."', "body"),
            ("", None),
            ("Tip: Always anchor with a number. Numbers make answers credible.", "tip"),
        ]
    },
    {
        "num": "2",
        "question": "Linux / Oracle / Java — Performance & Stability",
        "subtitle": "What is your methodology for handling a recurring performance degradation or crash on a Linux / Oracle / Java stack? What are the key steps and critical success factors?",
        "answer": [
            ("Structure: Diagnose -> Isolate -> Fix -> Prevent", "italic"),
            ("", None),
            ("My first priority is distinguishing between a symptom and a root cause. A recurring crash is rarely random — it has a pattern.", "body"),
            ("", None),
            ("On the Linux layer: I check system logs (dmesg, journalctl), resource exhaustion (OOM killer, file descriptors, swap), and kernel parameters.", "body"),
            ("On the Oracle layer: AWR/ASH reports, wait events, execution plans, undo/redo contention, and locking issues.", "body"),
            ("On the Java layer: heap dumps, GC logs, thread dumps, off-heap memory leaks, and connection pool exhaustion.", "body"),
            ("", None),
            ("Once the root cause is isolated, I document it, implement the fix, and instrument proper monitoring and alerting so the same issue is caught early next time.", "body"),
            ("", None),
            ("Key message: Recurring problems are a signal that observability was missing from day one.", "tip"),
        ]
    },
    {
        "num": "3",
        "question": "Cloud Deployment — Key Challenges",
        "subtitle": "What are the main challenges and considerations when migrating or deploying workloads to the Cloud?",
        "answer": [
            ("Structure: Technical | Organizational | Financial | Security", "italic"),
            ("", None),
            ("Cloud deployment is not just a technical migration — it's a transformation. The key challenges:", "body"),
            ("", None),
            ("• Architecture fit: Lift-and-shift rarely works. Stateful applications, Oracle licenses, and monoliths need rethinking.", "body"),
            ("• Cost governance: Without FinOps discipline, cloud bills spiral quickly. Right-sizing, reserved instances, and tagging policies are essential from day one.", "body"),
            ("• Security & compliance: IAM design, network segmentation, encryption at rest/in transit, and regulatory requirements (GDPR, SOX) must be addressed upfront.", "body"),
            ("• Operational readiness: Teams need to shift from 'managing servers' to 'managing services.' This requires training and new runbooks.", "body"),
            ("• Resilience design: Cloud doesn't automatically mean high availability. You have to architect for it — multi-AZ, circuit breakers, chaos engineering.", "body"),
            ("", None),
            ("Key message: Deployments that fail treat cloud as purely an infrastructure decision.", "tip"),
        ]
    },
    {
        "num": "4",
        "question": "Cybersecurity — SolarWinds Lessons",
        "subtitle": "What lessons do you draw from the SolarWinds supply chain attack, and how does it shape your approach to security?",
        "answer": [
            ("Structure: What happened -> Why it matters -> What changed in practice", "italic"),
            ("", None),
            ("SolarWinds demonstrated that the supply chain is an attack surface — a trusted vendor update became the attack vector against thousands of organizations.", "body"),
            ("", None),
            ("Key lessons:", "body"),
            ("• Zero Trust is not optional. Implicit trust in internal tools and vendors must be eliminated.", "body"),
            ("• Software Bill of Materials (SBOM): You need to know what's in your software, including third-party components.", "body"),
            ("• Least privilege everywhere: The malware spread because accounts had excessive permissions.", "body"),
            ("• Behavioral detection over signature detection: Traditional antivirus missed it. Anomaly detection and SIEM correlation are critical.", "body"),
            ("• Incident response must be rehearsed: Organizations that recovered fastest had tested their playbooks.", "body"),
            ("", None),
            ("In practice: I push for systematic vendor security assessments, controlled update pipelines, and network segmentation for management tools.", "tip"),
        ]
    },
    {
        "num": "5",
        "question": "Effective 24/7 Operations Across 4 Sites",
        "subtitle": "How do you ensure effective 24/7 operations across four distributed sites — New York, Paris, Tunis, and Noida?",
        "answer": [
            ("Structure: Organization -> Process -> Tools -> Culture", "italic"),
            ("", None),
            ("Running follow-the-sun requires more than scheduling — it requires deliberate design.", "body"),
            ("", None),
            ("• Organization: Clear ownership per time zone window. Overlap periods (handover calls) are non-negotiable. Every handover must include a written status update.", "body"),
            ("• Process: Standardized runbooks, incident classification, and escalation paths that work regardless of who is on duty.", "body"),
            ("• Tools: Single source of truth — one ITSM platform, one monitoring dashboard, one communication channel. Avoid tool fragmentation across sites.", "body"),
            ("• Culture: Rotate on-call leads across sites, hold cross-site retrospectives, ensure knowledge doesn't accumulate in one location.", "body"),
            ("", None),
            ("Key metric: MTTR by shift. If one site consistently has higher resolution times, there is a knowledge gap to address.", "tip"),
        ]
    },
    {
        "num": "6",
        "question": "AI Use Cases in Practice",
        "subtitle": "What concrete AI use cases have you implemented or contributed to? What was the context and what value was delivered?",
        "answer": [
            ("Structure: Use case -> Context -> Implementation -> Value delivered", "italic"),
            ("", None),
            ("• Log analysis & anomaly detection: ML models correlating events across Linux/Java logs to flag anomalies before incidents. Result: ~60% reduction in alert noise.", "body"),
            ("• Predictive maintenance: On Oracle databases, training models on AWR historical data to anticipate tablespace exhaustion or I/O saturation before SLA breach.", "body"),
            ("• Code review assistance: LLM-based tools integrated into CI/CD to flag security patterns and enforce coding standards automatically.", "body"),
            ("• Incident triage assistant: A chatbot trained on past incidents and runbooks giving L1 engineers immediate suggested actions, reducing escalation time.", "body"),
            ("", None),
            ("Key message: AI augments, it doesn't replace. The value comes from pairing it with solid human processes and clean underlying data. Garbage data in, garbage recommendations out.", "tip"),
        ]
    },
]

for section in sections:
    # Question header box
    pdf.set_fill_color(*BLUE)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 10, s(f"  Q{section['num']}. {section['question']}"), fill=True, new_x="LMARGIN", new_y="NEXT")

    # Subtitle
    pdf.set_text_color(*GRAY)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, s(section["subtitle"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Answer
    for text, style in section["answer"]:
        if text == "":
            pdf.ln(2)
            continue
        if style == "italic":
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(100, 100, 180)
            pdf.multi_cell(0, 5, s(text), new_x="LMARGIN", new_y="NEXT")
        elif style == "tip":
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(31, 120, 80)
            pdf.multi_cell(0, 5, s(f">> {text}"), new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*DARK)
            pdf.multi_cell(0, 5, s(text), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(6)

output_path = r"C:\Users\gilles.kammerer\OneDrive\immobilier\Pierrefonds\Mairie\Interview_QA.pdf"
pdf.output(output_path)
print(f"PDF created: {output_path}")
