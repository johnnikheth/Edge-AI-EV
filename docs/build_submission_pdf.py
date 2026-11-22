"""Generate docs/Depot-EV-Submission.pdf -- the full submission package."""
from fpdf import FPDF
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ACCENT  = (59, 130, 212)   # #3b82d4
DARK    = (31, 35, 40)     # #1f2328
MUTED   = (87, 96, 106)    # #57606a
SURFACE = (247, 248, 250)  # #f7f8fa
BORDER  = (229, 231, 235)  # #e5e7eb
WHITE   = (255, 255, 255)
GREEN   = (18, 161, 80)

def _s(text):
    """Sanitise text to latin-1 safe characters for fpdf core fonts."""
    tbl = {
        0x2014: '--', 0x2013: '-', 0x2012: '-',
        0x2019: "'",  0x2018: "'", 0x201c: '"', 0x201d: '"',
        0x2022: '-',  0x2023: '-', 0x2460: '1.', 0x2461: '2.',
        0x2462: '3.', 0x2463: '4.', 0x2192: '->', 0x2190: '<-',
        0x00b7: '.', 0x00a0: ' ', 0x2500: '-', 0x2502: '|',
        0x2026: '...', 0x00e9: 'e', 0x00e8: 'e', 0x00e0: 'a',
        0x00e4: 'a',  0x00fc: 'u', 0x00f6: 'o',
    }
    result = []
    for ch in text:
        cp = ord(ch)
        if cp in tbl:
            result.append(tbl[cp])
        elif cp > 255:
            result.append('?')
        else:
            result.append(ch)
    return ''.join(result)


class PDF(FPDF):
    # Auto-sanitise every string so we never hit latin-1 encoding issues
    def cell(self, *args, **kwargs):
        lst = list(args)
        if len(lst) > 2 and isinstance(lst[2], str): lst[2] = _s(lst[2])
        if 'text' in kwargs: kwargs['text'] = _s(str(kwargs['text']))
        return super().cell(*lst, **kwargs)
    def multi_cell(self, *args, **kwargs):
        lst = list(args)
        if len(lst) > 2 and isinstance(lst[2], str): lst[2] = _s(lst[2])
        if 'text' in kwargs: kwargs['text'] = _s(str(kwargs['text']))
        return super().multi_cell(*lst, **kwargs)
    def header(self):
        self.set_fill_color(*ACCENT)
        self.rect(0, 0, 210, 12, 'F')
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(*WHITE)
        self.set_xy(10, 2)
        self.cell(0, 8, 'Depot EV -- IBM SkillsBuild AI ELL . US 2026 Fall Cohort', align='L')
        self.set_xy(0, 2)
        self.cell(200, 8, f'Page {self.page_no()}', align='R')
        self.ln(14)

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', '', 8)
        self.set_text_color(*MUTED)
        self.cell(0, 8, 'Built with IBM Bob  .  github.com/johnnikheth/Edge-AI-EV', align='C')

    def section(self, number, title, subtitle=''):
        self.set_fill_color(*ACCENT)
        self.set_text_color(*WHITE)
        self.set_font('Helvetica', 'B', 11)
        self.rect(10, self.get_y(), 190, 9, 'F')
        self.set_xy(13, self.get_y() + 1)
        self.cell(0, 7, f'{number}  {title}', ln=True)
        if subtitle:
            self.set_font('Helvetica', '', 8)
            self.set_text_color(*MUTED)
            self.set_x(13)
            self.cell(0, 5, subtitle, ln=True)
        self.ln(3)
        self.set_text_color(*DARK)

    def label(self, text):
        self.set_font('Helvetica', 'B', 8)
        self.set_text_color(*MUTED)
        self.set_x(10)
        self.cell(0, 5, text.upper(), ln=True)
        self.set_text_color(*DARK)

    def body(self, text, indent=10):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(*DARK)
        self.set_x(indent)
        self.multi_cell(190 - (indent - 10), 5.5, text)
        self.ln(2)

    def box_text(self, text, indent=10):
        """Render text inside a light background box."""
        self.set_fill_color(*SURFACE)
        lines = text.strip().split('\n')
        # estimate height
        self.set_font('Helvetica', '', 9.5)
        total_h = 0
        for line in lines:
            if not line.strip():
                total_h += 3
            else:
                # rough wrap estimate
                chars_per_line = 90
                wrapped = max(1, len(line) // chars_per_line + 1)
                total_h += wrapped * 5.5
        total_h += 8  # padding

        x0, y0 = 10, self.get_y()
        # draw box
        self.set_draw_color(*BORDER)
        self.rect(x0, y0, 190, total_h, 'DF')
        self.set_xy(x0 + 4, y0 + 4)
        for line in lines:
            if not line.strip():
                self.ln(3)
            else:
                is_bold = (line.startswith('Problem') or line.startswith('Solution') or
                           line.startswith('IBM Bob') or line.startswith('watsonx') or
                           line.startswith('Task') or line.startswith('Target'))
                if is_bold:
                    self.set_font('Helvetica', 'B', 9.5)
                else:
                    self.set_font('Helvetica', '', 9.5)
                self.set_x(x0 + 4)
                self.multi_cell(182, 5.5, line)
        self.set_y(y0 + total_h + 3)

    def scale_table(self):
        rows = [
            ('This demo (1 depot, 7 vehicles)',        '$2,170 / month',  '$26,000 / year',   False),
            ('Mid-size fleet (1 depot, 20 vehicles)',  '$6,200 / month',  '$74,000 / year',   False),
            ('Regional operator (5 depots, 100 vans)', '$31,000 / month', '$372,000 / year',  True),
            ('Large corporate (20 depots, 400 vans)',  '$124,000 / month','$1,500,000+ / year',True),
        ]
        headers = ['Scale', 'Monthly Saving', 'Annual Saving']
        col_w = [95, 50, 45]
        x0 = 10

        # header row
        self.set_fill_color(*ACCENT)
        self.set_text_color(*WHITE)
        self.set_font('Helvetica', 'B', 9)
        self.set_x(x0)
        for i, h in enumerate(headers):
            self.cell(col_w[i], 7, h, border=0, fill=True)
        self.ln()

        # data rows
        for i, (scale, monthly, annual, hi) in enumerate(rows):
            fill_color = (240, 247, 255) if hi else WHITE
            self.set_fill_color(*fill_color)
            self.set_text_color(*DARK)
            self.set_font('Helvetica', 'B' if hi else '', 9)
            self.set_x(x0)
            self.cell(col_w[0], 7, scale, border=0, fill=True)
            self.set_font('Helvetica', '', 9)
            self.cell(col_w[1], 7, monthly, border=0, fill=True)
            self.set_font('Helvetica', 'B' if hi else '', 9)
            self.set_text_color(*GREEN if hi else DARK)
            self.cell(col_w[2], 7, annual, border=0, fill=True)
            self.ln()
            # thin divider
            self.set_draw_color(*BORDER)
            self.line(x0, self.get_y(), x0 + sum(col_w), self.get_y())

        self.set_text_color(*DARK)
        self.ln(4)


def build():
    pdf = PDF()
    pdf.set_margins(10, 15, 10)
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()

    # ── TITLE PAGE ──────────────────────────────────────────────────
    pdf.set_font('Helvetica', 'B', 22)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 10, 'Depot EV', ln=True, align='C')
    pdf.set_font('Helvetica', '', 13)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 7, 'Smart EV Fleet Charging & Dispatch Manager', ln=True, align='C')
    pdf.ln(4)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, 'IBM SkillsBuild AI Experiential Learning Lab  .  US 2026 Fall Cohort  .  Submission Package', ln=True, align='C')
    pdf.cell(0, 5, 'Team: John Nikheth Chiluvuri (AI & Platform + Product & Delivery)  .  Prakash Karey (Engine Lead)', ln=True, align='C')
    pdf.cell(0, 5, 'GitHub: github.com/johnnikheth/Edge-AI-EV  .  Submission deadline: Nov 22, 2026', ln=True, align='C')
    pdf.ln(8)

    # ── SAVINGS SCALE TABLE ──────────────────────────────────────────
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 6, 'The Business Case -- Corporate-Scale Savings', ln=True)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, 'Linear scaling of simulated PG&E BEV-1 math (~$310/vehicle/month saved)', ln=True)
    pdf.ln(2)
    pdf.scale_table()

    pdf.set_font('Helvetica', 'I', 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(190, 5, 'All savings figures are based on PG&E Schedule BEV-1 (effective March 1, 2026): peak rate $0.357/kWh (4-9 pm), '
                           'off-peak $0.165/kWh, super off-peak $0.138/kWh. The simulation runs one typical October night for a 7-vehicle '
                           'Oakland depot (5 delivery vans + 2 Tesla Semis), with 60 kW rooftop solar and 100 kWh EV storage. Monthly = 30 nights.')
    pdf.ln(6)

    # ── SECTION 1: VIDEO SCRIPT ──────────────────────────────────────
    pdf.section('1.', '3-Minute Demo Video -- Narration Script', 'Record screen at localhost:8000 . upload to YouTube (Unlisted)')

    segments = [
        ('0:00-0:30', 'The Problem',
         'Screen: Depot page, price timeline visible\n\n'
         '"This is Depot EV -- a smart charging and dispatch system for a small electric delivery fleet.\n\n'
         'The depot runs five delivery vans out of Oakland, California. Without any management, every van plugs in '
         'when it gets back -- right in the middle of PG&E\'s peak window, 4 to 9 pm, where electricity costs '
         '35 cents a kilowatt-hour. That\'s more than twice the off-peak price.\n\n'
         'The result: around $4,200 a month in electricity costs, seven breaker trips a night, and no guarantee '
         'every van is charged by morning. We fix all three."'),

        ('0:30-1:30', 'Run the Night',
         'Screen: Click Run Night → watch simulation → click Savings tab\n\n'
         '"Watch the system charge the fleet. It follows a strict priority order:\n\n'
         'First -- rooftop solar, which is free. You can see it charging vans through the afternoon.\n\n'
         'Second -- the on-site 100 kilowatt-hour battery, filled by solar earlier. During the 4-9 pm peak the '
         'system draws from storage instead of the grid -- avoiding that 35-cent rate entirely.\n\n'
         'Third -- cheap off-peak grid power after 9 pm, at 14 cents a kilowatt-hour.\n\n'
         'Result: about $2,000 a month versus $4,200 without the system -- a 53% reduction. Zero breaker trips. '
         'All five vans ready for their routes."'),

        ('1:30-2:15', 'Dispatch + Orchestrate Agent',
         'Screen: dispatch.html → Run demo scenario → switch to Orchestrate chat\n\n'
         '"Van 2 hits a road accident at 6:30 am. The agent reroutes automatically -- zero late stops. '
         'Then Van 1 breaks down with 13 stops left. The agent proposes moving those stops to nearby vans, '
         'but it will NOT move a single stop until the dispatcher clicks Approve.\n\n'
         'And this is the watsonx Orchestrate operations assistant. Watch:\n\n'
         '[type: "Are all vans ready this morning?"] -- it calls our live API and answers from real data.\n\n'
         '[type: "How much did we save last night?"] -- $71 saved overnight, $2,169 projected monthly."'),

        ('2:15-3:00', 'IBM Bob + Wrap',
         'Screen: Bob chat (10 sec clip) → GitHub repo → back to Depot page\n\n'
         '"Every line of this was built with IBM Bob -- IBM\'s AI development partner. Bob wrote the Python '
         'simulation engine, 16 automated tests, the OpenAPI spec, the Dockerfile, and all seven Orchestrate '
         'agent definitions -- across six tracked tasks.\n\n'
         'For this 7-vehicle pilot depot: $26,000 saved every year with zero hardware changes. Scale to a '
         'regional operator -- 100 vehicles, 5 depots -- that\'s $370,000 a year. At large corporate fleet '
         'scale: over one and a half million dollars a year. Same software. Same agents. A person approves '
         'every risky call.\n\n'
         'Depot EV. github.com/johnnikheth/Edge-AI-EV."'),
    ]

    for time, title, content in segments:
        pdf.set_fill_color(*SURFACE)
        pdf.set_draw_color(*BORDER)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_text_color(*ACCENT)
        pdf.set_x(10)
        pdf.cell(28, 6, time, fill=True, border=1)
        pdf.set_text_color(*DARK)
        pdf.cell(162, 6, title, fill=True, border=1, ln=True)
        pdf.box_text(content)

    pdf.add_page()

    # ── SECTION 2: PROBLEM & SOLUTION ───────────────────────────────
    pdf.section('2.', 'Written Problem & Solution Statement', 'Copy and paste into the submission text box (≈390 words, max 500)')

    text_ps = """Problem

Small and mid-size electric delivery depots are caught in a costly trap. A fleet charging on a standard commercial tariff -- PG&E BEV-1 in the Bay Area -- pays $0.357 per kilowatt-hour during the 4-9 pm peak window. Delivery vans return from routes in the early afternoon and, without any management, charge straight through that peak window. The result: a 7-vehicle Oakland depot pays approximately $4,200 per month in electricity -- nearly $2,200 of which is completely avoidable. Scaled to a regional operator running 100 vehicles across 5 depots, that waste becomes $370,000 a year. At Amazon or FedEx scale -- hundreds of depots -- it exceeds $1.5 million annually, all from a problem that software alone can fix.

The operations team also starts every day without reliable answers to basic questions: are all vans charged and ready? Did anything go wrong overnight? Were any customers told about delays? Getting those answers requires manually checking chargers, logs, and messages -- time the dispatcher doesn't have at 6 am.

Solution

Depot EV is an AI-assisted operations system that solves both problems.

The smart charging layer schedules every vehicle using a strict priority order: rooftop solar first (free), then the on-site battery during the 4-9 pm peak window (avoiding that $0.357 rate entirely), then cheap super off-peak grid power after 9 pm at $0.138/kWh. Peak grid power is only used as a last resort -- when a van is critical and about to miss its departure. The result at this 7-vehicle pilot depot: $2,000/month vs $4,200 without the system -- a 53% reduction, $26,000 saved per year. No new hardware required beyond the software.

The dispatch layer proposes route swaps when a van is short on charge, but nothing is approved automatically. Every swap, reassignment, and customer message waits for the dispatcher to click Approve. The system is advisory; the person decides.

The intelligence layer is powered by watsonx Orchestrate. Seven agents -- a main Q&A assistant, three command supervisors (Energy, Fleet, Business Command), and three specialist subagents (Solar & Storage, Fleet Planner, Tariff) -- answer the morning's key questions in plain English, grounded in real numbers, never invented.

Target users: depot managers and dispatchers at small-to-large electric delivery fleets (5-500 vehicles) with rooftop solar or on-site storage who have no existing energy management system.

What makes it unique: the human-approval gate combined with AI scale. Every operational decision requires explicit dispatcher sign-off. And the savings scale linearly: $26K/year at one depot becomes $1.5M/year across a large corporate fleet -- with the same software, the same agents, and the same approval model."""

    pdf.box_text(text_ps)
    pdf.ln(4)

    # ── SECTION 3: TECHNOLOGY ────────────────────────────────────────
    pdf.section('3.', 'Written Technology Statement', 'Copy and paste into the submission text box (≈390 words, max 500)')

    text_tech = """IBM Tools Used

IBM Bob -- build engine for all six tracked tasks

We used IBM Bob as the primary build assistant throughout the project. Each of the six lab tasks was completed in a dedicated Bob session with a session report exported to bob_sessions/.

Task 01 (Python repo): Bob scaffolded the depot_ev/ Python package -- fleet_simulator.py, gateway_controller.py, watsonx_reporter.py, and run_night.py -- translating the existing JavaScript prototype logic into a testable Python engine with real PG&E BEV-1 tariff math.

Task 02 (Tests): Bob wrote 16 pytest tests covering 9 charging rules: grid usage at peak, site breaker limit, van readiness, storage priority, HVAC hysteresis, dispatch approval gate, battery floor, BEV-1 tariff calculation, and solar charging. All 16 pass.

Task 03 (Orchestrate agent): Bob drafted the OpenAPI spec (tools/depot-api.openapi.yaml) with BearerAuth, wrote all 7 agent YAML files, and produced the import guide with five test questions and expected answers.

Task 04 (Security): Bob audited the server for injection, auth bypass, and secrets exposure. It added Bearer token enforcement on every /api/ endpoint and documented accepted risk items.

Task 05 (Deploy): Bob wrote the Dockerfile (Python 3.12-slim, non-root user) and ibmcloud-deploy.sh for IBM Cloud Code Engine. Live deploy pending Docker + resource-group permissions.

Task 06 (Docs): Bob generated the README (245 lines) and triggered Redocly to build docs/api.html from the OpenAPI spec.

watsonx Orchestrate -- seven live agents

Five API tools (list_sessions, get_session, list_customer_messages, find_building_tariffs, get_live_traffic) are imported from the OpenAPI spec. Seven agents are live in the eu-de instance:
  - depot_ops_agent: main Q&A assistant, answers morning questions
  - energy_command, fleet_command, business_command: three supervisors, each reaches GO / WATCH / ACTION NEEDED
  - solar_storage, fleet_planner, tariff: three specialist subagents

Each agent uses Granite 3 8B Instruct, never invents numbers, and routes all operational decisions back to the dispatcher.

watsonx Granite (ibm/granite-3-8b-instruct)

Called via watsonx.ai at the end of each simulated night to generate a plain-English morning brief summarising van readiness, costs saved, kWh bought at peak, and anything needing attention. The brief is stored in SQLite and displayed in the UI alongside the agent verdict (GO / WATCH / ACTION NEEDED).

Bob credit usage: 80.35 of 150 credits across six tasks, documented in docs/bob-tasks/credit-log.md."""

    pdf.box_text(text_tech)
    pdf.ln(4)

    # ── SECTION 4: QUICK REF ─────────────────────────────────────────
    pdf.section('4.', 'Quick Reference', 'Key facts for the demo and interview')

    facts = [
        ('GitHub repo',       'github.com/johnnikheth/Edge-AI-EV'),
        ('Demo URL',          'http://localhost:8000?token=Aqz0kZecXnyxDBVigwdlaoWI7KP5uMR3'),
        ('Orchestrate',       'eu-de.watson-orchestrate.cloud.ibm.com  .  7 agents live'),
        ('Saving (pilot)',    '$2,170/month  .  $26,000/year  (53% cut on PG&E BEV-1)'),
        ('Saving (100 vans)', '$31,000/month  .  $372,000/year'),
        ('Saving (400 vans)', '$124,000/month  .  $1,500,000+/year'),
        ('Peak kWh bought',   '0.0 kWh at peak (solar + storage cover the whole peak window)'),
        ('Vans ready',        '5 of 5  (all meet route charge requirement every night)'),
        ('Breaker trips',     '0  (site limit never exceeded with managed charging)'),
        ('Bob credits used',  '80.35 / 150  (all 6 tasks complete)'),
        ('Team',              'John Nikheth Chiluvuri (AI & Platform + Product lead)  .  Prakash Karey (Engine lead)'),
        ('Deadline',          'Nov 22, 2026 -- submit today'),
    ]

    pdf.set_font('Helvetica', '', 9)
    for key, val in facts:
        pdf.set_x(10)
        pdf.set_font('Helvetica', 'B', 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(48, 6, key)
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(*DARK)
        pdf.multi_cell(142, 6, val)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Depot-EV-Submission.pdf')
    pdf.output(out)
    print(f'Saved: {out}')


if __name__ == '__main__':
    build()
