"""Builds the Depot EV solution document (PDF) with reportlab."""
import sys
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether, ListFlowable, ListItem, NextPageTemplate)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon, Circle
from reportlab.graphics.charts.barcharts import HorizontalBarChart

OUT = sys.argv[1]
BLUE = colors.HexColor('#4f6bed'); GREEN = colors.HexColor('#12a150'); RED = colors.HexColor('#d92d20')
ORANGE = colors.HexColor('#e8890c'); PURPLE = colors.HexColor('#a142f4'); SUN = colors.HexColor('#f5b301')
INK = colors.HexColor('#1b1f27'); MUTED = colors.HexColor('#667085'); LINE = colors.HexColor('#e3e6ec')
SOFT = colors.HexColor('#f5f6f8'); NAVY = colors.HexColor('#1f3b73')

ss = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=ss['Heading1'], fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=INK, spaceBefore=6, spaceAfter=10)
H2 = ParagraphStyle('H2', parent=ss['Heading2'], fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=NAVY, spaceBefore=12, spaceAfter=6)
H3 = ParagraphStyle('H3', parent=ss['Heading3'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=INK, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle('B', parent=ss['BodyText'], fontName='Helvetica', fontSize=10, leading=14.2, textColor=INK, spaceAfter=6)
SMALL = ParagraphStyle('S', parent=BODY, fontSize=8.5, leading=11.5, textColor=MUTED)
CELL = ParagraphStyle('C', parent=BODY, fontSize=8.8, leading=11.5, spaceAfter=0)
CELLB = ParagraphStyle('CB', parent=CELL, fontName='Helvetica-Bold')
CALL = ParagraphStyle('Call', parent=BODY, fontSize=10.5, leading=15, textColor=INK, backColor=colors.HexColor('#eef1fd'),
                      borderPadding=(8, 10, 8, 10), borderColor=BLUE, borderWidth=0, leftIndent=0, spaceBefore=4, spaceAfter=12)
# IBM Bob additions are printed in red
REDC = colors.HexColor('#c4161c')
RBODY = ParagraphStyle('RB', parent=BODY, textColor=REDC)
RCELL = ParagraphStyle('RC', parent=CELL, textColor=REDC)
RCELLB = ParagraphStyle('RCB', parent=CELLB, textColor=REDC)
RH1 = ParagraphStyle('RH1', parent=H1, textColor=REDC)
RH2 = ParagraphStyle('RH2', parent=H2, textColor=REDC)
RCALL = ParagraphStyle('RCall', parent=CALL, textColor=REDC, backColor=colors.HexColor('#fdecec'))
RCODE = ParagraphStyle('RCode', parent=RBODY, fontName='Courier', fontSize=8.3, leading=11, backColor=colors.HexColor('#fdf3f3'),
                       borderPadding=(6, 8, 6, 8), spaceBefore=2, spaceAfter=10)
def R(t, s=None): return Paragraph(t, s or RBODY)
# Lab-alignment updates are highlighted in yellow
YEL = colors.HexColor('#fff3a3')
YBODY = ParagraphStyle('YB', parent=BODY, backColor=YEL, borderPadding=(3, 4, 3, 4))
YH1 = ParagraphStyle('YH1', parent=H1, backColor=YEL, borderPadding=(2, 4, 2, 4))
YH2 = ParagraphStyle('YH2', parent=H2, backColor=YEL, borderPadding=(2, 4, 2, 4))
YSMALL = ParagraphStyle('YS', parent=SMALL, backColor=YEL, borderPadding=(2, 4, 2, 4))
def Y(t, s=None): return Paragraph(t, s or YBODY)
def yrow(t, r0, r1=None):
    t.setStyle(TableStyle([('BACKGROUND', (0, r0), (-1, r1 if r1 is not None else r0), YEL)])); return t
def ytable(*a, **k):
    t = table(*a, **k); t.setStyle(TableStyle([('BACKGROUND', (0, 1), (-1, -1), YEL)])); return t
def RC(t, bold=False): return Paragraph(t, RCELLB if bold else RCELL)

def P(t, s=BODY): return Paragraph(t, s)
def bullets(items, style=BODY):
    return ListFlowable([ListItem(P(i, style), leftIndent=12) for i in items],
                        bulletType='bullet', start='•', leftIndent=12, bulletFontSize=8, spaceAfter=6)
def table(rows, widths, header=True, zebra=True, align_right=()):
    data = [[P(c, CELLB if (header and r == 0) else CELL) if isinstance(c, str) else c for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE),
          ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4), ('LEFTPADDING', (0, 0), (-1, -1), 5)]
    if header: st += [('BACKGROUND', (0, 0), (-1, 0), SOFT), ('LINEBELOW', (0, 0), (-1, 0), 1, MUTED)]
    if zebra:
        for r in range(1 if header else 0, len(rows)):
            if r % 2 == 0: st.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#fbfbfd')))
    for c in align_right: st.append(('ALIGN', (c, 0), (c, -1), 'RIGHT'))
    t.setStyle(TableStyle(st)); return t

# ---------- drawings ----------
def arrow(d, x1, y1, x2, y2, color=MUTED, both=False):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.2))
    import math
    def head(xa, ya, xb, yb):
        a = math.atan2(yb - ya, xb - xa); L = 6
        d.add(Polygon([xb, yb, xb - L*math.cos(a - .4), yb - L*math.sin(a - .4), xb - L*math.cos(a + .4), yb - L*math.sin(a + .4)],
                      fillColor=color, strokeColor=color, strokeWidth=0))
    head(x1, y1, x2, y2)
    if both: head(x2, y2, x1, y1)

def box(d, x, y, w, h, title, sub, fill=colors.white, fg=INK, subfg=MUTED):
    d.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=fill, strokeColor=LINE if fill == colors.white else fill, strokeWidth=1))
    d.add(String(x + w/2, y + h/2 + 3, title, fontName='Helvetica-Bold', fontSize=9, fillColor=fg, textAnchor='middle'))
    d.add(String(x + w/2, y + h/2 - 9, sub, fontName='Helvetica', fontSize=7, fillColor=subfg, textAnchor='middle'))

def chip(d, x, y, w, title, sub, col):
    d.add(Rect(x, y, w, 30, rx=4, ry=4, fillColor=colors.white, strokeColor=col, strokeWidth=1.1))
    d.add(String(x + w/2, y + 17, title, fontName='Helvetica-Bold', fontSize=6.6, fillColor=INK, textAnchor='middle'))
    d.add(String(x + w/2, y + 7, sub, fontName='Helvetica', fontSize=5.4, fillColor=MUTED, textAnchor='middle'))

def command(d, x, w, title, col, chips):
    d.add(Rect(x, 168, w, 118, rx=7, ry=7, fillColor=None, strokeColor=col, strokeWidth=1.4, strokeDashArray=[4, 3]))
    d.add(Rect(x + 6, 263, w - 12, 18, rx=4, ry=4, fillColor=col, strokeColor=col))
    d.add(String(x + w/2, 269, title, fontName='Helvetica-Bold', fontSize=8, fillColor=colors.white, textAnchor='middle'))
    for cx, cy, cw, t, sb in chips: chip(d, cx, cy, cw, t, sb, col)

def architecture():
    d = Drawing(500, 340)
    d.add(Rect(5, 304, 490, 30, rx=6, ry=6, fillColor=INK, strokeColor=INK))
    d.add(String(250, 322, 'Depot verdict: GO / WATCH / ACTION NEEDED', fontName='Helvetica-Bold', fontSize=9, fillColor=colors.white, textAnchor='middle'))
    d.add(String(250, 311, 'the worst of the three command conclusions, written into the morning brief', fontName='Helvetica', fontSize=6.5, fillColor=colors.white, textAnchor='middle'))
    command(d, 5, 234, 'Energy Command', BLUE, [(11, 228, 70, 'Power agent', 'cheapest hours, HVAC'), (86, 228, 70, 'Solar & Storage', 'solar, peak, outage'), (161, 228, 70, 'Tariff agent', 'BEV size, rates'),
                                                (11, 192, 70, 'Outage resilience', 'runtime, shed order'), (86, 192, 70, 'Demand response', 'flex kW at peak')])
    command(d, 245, 140, 'Fleet Command', RED, [(250, 228, 63, 'Fleet planner', 'priority, swaps'), (317, 228, 63, 'Dispatch', 'reroute, notify'),
                                                (250, 192, 63, 'Battery health', 'history, cost/van'), (317, 192, 63, 'Charger faults', 'detect, ticket')])
    command(d, 391, 104, 'Business Command', GREEN, [(397, 228, 92, 'Customer comms', 'drafts, escalate, replies'), (397, 192, 92, 'Reporting', 'owner report')])
    for x in (122, 315, 443): arrow(d, x, 286, x, 304)
    names = [('Grid', 'PG&E BEV-1'), ('Solar', 'corporate roof'), ('EV storage', 'outage reserve'), ('Corp. Office', 'HVAC, base load'),
             ('Chargers+vans', 'ready by dawn'), ('Public data', 'OpenEI 511 NREL'), ('Customers', 'delay, moved'), ('watsonx', 'Granite, Orchestrate')]
    for i, (t, sb) in enumerate(names):
        x = 5 + i*61.5
        d.add(Rect(x, 88, 57, 38, rx=5, ry=5, fillColor=colors.white, strokeColor=LINE, strokeWidth=1))
        d.add(String(x + 28.5, 111, t, fontName='Helvetica-Bold', fontSize=6.4, fillColor=INK, textAnchor='middle'))
        d.add(String(x + 28.5, 100, sb, fontName='Helvetica', fontSize=5.2, fillColor=MUTED, textAnchor='middle'))
        arrow(d, x + 28.5, 126, x + 28.5, 168, both=i in (2, 3, 4, 6))
    d.add(Rect(5, 40, 490, 28, rx=5, ry=5, fillColor=SOFT, strokeColor=LINE, strokeDashArray=[3, 2]))
    d.add(String(250, 50, 'server.py + SQLite: sessions, power samples, agent decisions, approvals, maintenance tickets, customer messages, reports',
                 fontName='Helvetica', fontSize=7.2, fillColor=MUTED, textAnchor='middle'))
    d.scale(0.88, 0.88); d.width, d.height = 500*0.88, 340*0.88
    return d

def timeline():
    d = Drawing(500, 58)
    start, end = 13*60, 30*60
    x = lambda m: 5 + (m - start)/(end - start)*490
    segs = [(13*60, 14*60, GREEN, 'Super off-peak'), (14*60, 16*60, BLUE, 'Off-peak'), (16*60, 21*60, RED, 'PEAK  $0.357'),
            (21*60, 30*60, BLUE, 'Off-peak  $0.165')]
    for a, b, c, t in segs:
        d.add(Rect(x(a), 22, x(b) - x(a), 26, fillColor=c, strokeColor=colors.white, strokeWidth=1))
        if b - a >= 120: d.add(String((x(a)+x(b))/2, 31, t, fontName='Helvetica-Bold', fontSize=8, fillColor=colors.white, textAnchor='middle'))
        else: d.add(String((x(a)+x(b))/2, 31, 'Super', fontName='Helvetica-Bold', fontSize=6.5, fillColor=colors.white, textAnchor='middle'))
    for hh in (13, 16, 21, 24, 27, 30):
        d.add(String(x(hh*60), 8, f'{hh%24:02d}:00', fontName='Helvetica', fontSize=7.5, fillColor=MUTED, textAnchor='middle'))
    return d

def cost_chart():
    labels = ['Today: charge on arrival', 'Smart charging only', '+ 60 kW rooftop solar', '+ solar + 100 kWh storage']
    vals = [4212, 2905, 2371, 1998]
    d = Drawing(500, 150)
    c = HorizontalBarChart(); c.x = 150; c.y = 10; c.width = 300; c.height = 130
    c.data = [list(reversed(vals))]; c.categoryAxis.categoryNames = list(reversed(labels))
    c.valueAxis.valueMin = 0; c.valueAxis.valueMax = 4500; c.valueAxis.valueStep = 1000
    c.valueAxis.labels.fontName = 'Helvetica'; c.valueAxis.labels.fontSize = 7; c.valueAxis.labelTextFormat = '$%d'
    c.categoryAxis.labels.fontName = 'Helvetica'; c.categoryAxis.labels.fontSize = 8; c.categoryAxis.labels.dx = -4
    c.categoryAxis.labels.boxAnchor = 'e'
    c.bars.strokeColor = None; c.barWidth = 18
    for i, col in enumerate(reversed([RED, BLUE, SUN, GREEN])): c.bars[(0, i)].fillColor = col
    c.barLabelFormat = '$%d'; c.barLabels.fontName = 'Helvetica-Bold'; c.barLabels.fontSize = 8; c.barLabels.nudge = 16
    d.add(c); return d

# ---------- page templates ----------
def on_page(canv, doc):
    canv.saveState()
    canv.setStrokeColor(LINE); canv.line(0.75*inch, 0.6*inch, letter[0] - 0.75*inch, 0.6*inch)
    canv.setFont('Helvetica', 8); canv.setFillColor(MUTED)
    canv.drawString(0.75*inch, 0.42*inch, 'Depot EV - smart charging, rooftop solar, EV storage and dispatch agents')
    canv.drawRightString(letter[0] - 0.75*inch, 0.42*inch, f'Page {doc.page}')
    canv.restoreState()

def on_cover(canv, doc):
    W, H = letter
    canv.saveState()
    canv.setFillColor(colors.HexColor('#dbe7ff')); canv.rect(0, H*0.42, W, H*0.58, stroke=0, fill=1)
    canv.setFillColor(colors.HexColor('#c9cfd8')); canv.rect(0, H*0.42 - 20, W, 20, stroke=0, fill=1)
    # simple original scene: building with rooftop solar, storage, vans
    base = H*0.42
    canv.setFillColor(colors.white); canv.setStrokeColor(colors.HexColor('#3b4252')); canv.setLineWidth(1.2)
    canv.rect(60, base, 230, 120, stroke=1, fill=1)
    canv.setFillColor(NAVY)
    for i in range(8):
        x = 68 + i*28; p = canv.beginPath(); p.moveTo(x, base + 124); p.lineTo(x + 24, base + 124); p.lineTo(x + 20, base + 138); p.lineTo(x - 4, base + 138); p.close()
        canv.drawPath(p, stroke=1, fill=1)
    canv.setFillColor(colors.HexColor('#dbe7ff'))
    for r in range(3):
        for cidx in range(6): canv.rect(78 + cidx*34, base + 20 + r*32, 20, 16, stroke=1, fill=1)
    canv.setFillColor(colors.white); canv.rect(320, base, 80, 50, stroke=1, fill=1)
    canv.setFillColor(SUN); canv.setFont('Helvetica-Bold', 7); canv.drawCentredString(360, base + 8, 'EV STORAGE')
    canv.circle(W - 80, H - 90, 26, stroke=0, fill=1)
    for i, x in enumerate((430, 500)):
        canv.setFillColor(GREEN); canv.rect(x, base, 6, 34, stroke=0, fill=1)
        canv.setFillColor(colors.white); canv.setStrokeColor(colors.HexColor('#3b4252'))
        p = canv.beginPath(); p.moveTo(x + 12, base); p.lineTo(x + 12, base + 26); p.lineTo(x + 52, base + 26); p.lineTo(x + 62, base + 14); p.lineTo(x + 62, base); p.close()
        canv.drawPath(p, stroke=1, fill=1)
        canv.setFillColor(BLUE); canv.rect(x + 14, base + 10, 46, 2.5, stroke=0, fill=1)
    canv.setStrokeColor(SUN); canv.setLineWidth(2.5); canv.setDash(6, 5)
    canv.line(290, base + 130, 360, base + 52); canv.line(400, base + 25, 430, base + 25)
    canv.restoreState()

doc = BaseDocTemplate(OUT, pagesize=letter, leftMargin=0.75*inch, rightMargin=0.75*inch, topMargin=0.7*inch, bottomMargin=0.8*inch,
                      title='Depot EV - Solution Document', author='Prakash Karey', subject='IBM SkillsBuild MVP: EV fleet depot energy and dispatch')
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='f')
cover_frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, letter[1]*0.40 - doc.bottomMargin, id='c')
doc.addPageTemplates([PageTemplate('cover', [cover_frame], onPage=on_cover), PageTemplate('body', [frame], onPage=on_page)])

S = []
TITLE = ParagraphStyle('T', fontName='Helvetica-Bold', fontSize=26, leading=31, textColor=INK, spaceAfter=8)
SUB = ParagraphStyle('Sub', fontName='Helvetica', fontSize=13, leading=18, textColor=MUTED, spaceAfter=14)
S += [P('Depot EV', TITLE),
      P('Smart charging, rooftop solar, EV storage and AI dispatch for electric delivery fleets', SUB),
      P('MVP solution document &middot; IBM SkillsBuild &middot; October 2026', BODY),
      P('Prepared by Prakash Karey', BODY),
      Y('IBM SkillsBuild AI Experiential Learning Lab &middot; US 2026 Fall Cohort &middot; Team of 3 &middot; cohort theme: to confirm in the lab portal'),
      Spacer(1, 10),
      P('<b>In one line:</b> eleven cooperating agents, led by three command agents, cut a simulated 5-van depot\'s energy bill by about 53% '
        '(from $4,212 to about $2,000 a month) by avoiding PG&amp;E\'s 4-9 pm peak price, using rooftop solar and '
        'EV storage, and keeping every van ready for its route - with a person approving any risky dispatch change.', CALL),
      NextPageTemplate('body'), PageBreak()]

# 1 Executive summary
S += [P('1. Executive summary', H1),
      P('Commercial EV fleets face two cost and reliability problems at the depot. First, utilities charge a premium for '
        'electricity in the evening: on PG&amp;E\'s business EV rate (Schedule BEV), power bought between 4 pm and 9 pm costs '
        '<b>$0.357/kWh, more than twice</b> the off-peak price. Delivery vans return in the early afternoon and, if they charge '
        'the moment they plug in, buy most of their energy in exactly that window. Second, the site\'s grid connection is limited; '
        'when chargers and building HVAC switch on together the depot exceeds its limit and trips the breaker.'),
      P('Depot EV is a working MVP that solves both. A <b>power agent</b> plans each van\'s charging into the cheapest hours, uses '
        'rooftop solar and on-site EV storage when the company has them, controls building HVAC, and never exceeds the site limit. '
        'A <b>dispatch agent</b> runs the delivery day from the overnight result, handles traffic, accidents and breakdowns, notifies '
        'customers, and asks a dispatcher before reassigning stops or rescheduling customers. <b>IBM watsonx.ai (Granite)</b> writes '
        'the operational briefs and customer messages.'),
      P('The solution has since grown into a hierarchy of <b>eleven agents</b> led by three <b>command agents</b> - Energy, Fleet and Business '
        'Command - whose conclusions combine into one <b>depot verdict</b>: GO, WATCH or ACTION NEEDED (section 5A).'),
      P('Key results (simulated, one typical October night for 5 vans, 50 kW site limit):', H3),
      table([['Measure', 'Without the system', 'With the system'],
             ['Monthly energy bill (charging + building)', '$4,212', 'about $2,000 (53% less)'],
             ['Charging energy bought at peak price', '179 kWh per night', 'about 1 kWh per night'],
             ['Breaker trips (site over its 50 kW limit)', '7 per night', '0'],
             ['Vans ready for their routes', '5 of 5', '5 of 5 in every scenario tested'],
             ['Building HVAC energy', '118 kWh per night', '98 kWh per night'],
             ['Grid outage during the peak', 'chargers and building down', 'depot keeps running on solar + storage']],
            [2.6*inch, 1.9*inch, 2.5*inch]),
      Spacer(1, 6),
      P('The single biggest saving needs no new equipment: <b>smart charging alone saves about $1,300 a month</b> ($4,212 to $2,905). '
        'Rooftop solar and EV storage add further savings, and their best size depends on installed-cost quotes, which the app can '
        'evaluate (section 7.3).'),
      R('<b>IBM Bob (added - shown in red throughout).</b> The team has IBM Bob through IBM SkillsBuild with 150 credits. Bob is IBM\'s AI '
        'development partner: it is used to <b>build, test, secure and deploy</b> this solution - turning the working prototype into the Python '
        'repository the coach asked for, writing automated tests for the agents\' rules, scanning for security issues and preparing an IBM Cloud '
        'deployment. watsonx.ai Granite remains the AI that runs inside the app. Section 14 has the plan and the credit budget.', RCALL),
      Y('<b>What this is.</b> A working simulation built on real PG&amp;E prices and public data - not a hardware pilot. Chargers, vans, solar, '
        'storage and building temperature are simulated; monthly figures repeat one typical October night 30 times, exported solar earns nothing '
        'and no equipment costs are included.'),
      Spacer(1, 4),
      Y('<b>Lab alignment and next steps.</b> Built for the IBM SkillsBuild AI Experiential Learning Lab (US 2026 Fall). IBM Bob builds the '
        'production pieces (six tracked tasks, session reports in <font face="Courier">bob_sessions/</font>), watsonx Granite and a watsonx '
        'Orchestrate operations agent run in the solution, and a person approves risky decisions. A team of three delivers it by November 22 '
        '(sections 15-17).'),
      ]

# 2 Problem
S += [P('2. The problem', H1),
      P('MVP user story', H3),
      P('<i>"As a depot manager, I want the system to dynamically throttle charger output when facility demand spikes, and receive an '
        'automated morning summary from watsonx confirming all vehicles are ready without tripping the breaker."</i>'),
      P('What costs fleet owners money today', H3),
      bullets(['<b>Peak-price charging.</b> Vans return around 13:00-14:30 at 15-20% battery and need roughly 40-55 kWh each. '
               'Charging on arrival at 7.7 kW runs straight through the 4-9 pm peak.',
               '<b>Demand and capacity limits.</b> Five 7.7 kW chargers plus a 30 kW HVAC load exceed a 50 kW service. The result is '
               'breaker trips, or an expensive service upgrade.',
               '<b>Wasted on-site energy.</b> Corporate rooftop solar produces in the afternoon, when no one plans charging around it, and '
               'surplus is exported with little or no credit.',
               '<b>Disruption on the road.</b> Traffic, accidents and breakdowns make deliveries late. Customers are not told, and stops '
               'are not rebalanced across the fleet.'])]

# 3 Solution overview
S += [P('3. Solution overview', H1),
      P('The solution is a small set of cooperating parts. Everything runs from one local Python server with a SQLite database; the '
        'web pages are plain HTML and JavaScript.'),
      architecture(),
      P('Figure 1 - System at a glance: eleven agents in three command containers report to one depot verdict. Arrows show the flow of power and decisions.', SMALL),
      yrow(table([['Part', 'What it does'],
             ['Power agent (Depot page)', 'Plans charging by price, runs solar and EV storage, controls HVAC, keeps the site under its limit.'],
             ['Dispatch agent (Dispatch page)', 'Runs the delivery day, chooses wait vs reroute, proposes stop reassignments for approval, notifies customers.'],
             ['Command agents (Energy, Fleet, Business)', 'Three supervisor agents. Each reads its member agents and reaches one conclusion; the worst of the three is the depot verdict (section 5A).'],
             ['Specialist agents', 'Solar &amp; Storage, Tariff, Outage resilience, Demand response, Fleet planner, Battery health, Charger faults, Customer communications and Reporting (section 5A).'],
             ['watsonx.ai Granite', 'Writes the morning depot brief, the end-of-day dispatch brief and customer message wording.'],
             ['Server + SQLite', 'Serves the pages, stores every session, proxies public data and watsonx calls.'],
             ['Public data', 'PG&amp;E BEV tariff, OpenEI tariffs, NREL PVWatts solar, Open-Meteo weather, 511 traffic, OpenStreetMap.'],
             [P('watsonx Orchestrate operations agent', CELLB), P('Answers questions like "Are all vans ready?" and "How much did we save?" from saved sessions through a read-only API (section 15).', CELL)],
             [RC('IBM Bob (development)', True), RC('Builds and hardens the solution: Python repository, automated tests, security scanning, IBM Cloud deployment and docs (section 14). Not part of the running app.')]],
            [1.9*inch, 5.1*inch]), 6),
      P('The power and dispatch agents are linked in a loop: the battery each van has at the end of the delivery day is where the depot night starts, '
        'and the charge each van reaches overnight is where the next delivery day starts.'),
      PageBreak()]

# 4 Power agent
S += [P('4. The power agent (Depot)', H1),
      P('The depot is simulated from 13:00, when vans start returning, to 06:00, after the last departure. The agent works in 15-minute '
        'slots and re-plans every hour and whenever a van arrives or conditions change.'),
      P('4.1 The price the agent plans around', H2),
      timeline(),
      P('Figure 2 - PG&amp;E Schedule BEV prices across the depot night. Super off-peak is 9 am-2 pm, so only 13:00-14:00 falls in the window.', SMALL),
      P('4.2 Charging planner - cheapest energy first', H2),
      P('For each van, in order of earliest departure, the planner places the energy the route needs into the cheapest available slots:'),
      ListFlowable([ListItem(P(t), leftIndent=14) for t in [
          '<b>Rooftop solar</b> (free) while the sun is up.',
          '<b>Stored solar during the peak</b>, if the site has EV storage (treated as already paid for).',
          '<b>Super off-peak</b> grid power ($0.138/kWh), then <b>off-peak</b> ($0.165/kWh).',
          '<b>Peak</b> grid power ($0.357/kWh) only if a van would otherwise miss its departure.']],
          bulletType='1', bulletFormat='%s.', leftIndent=16, spaceAfter=6),
      P('Among hours with the same price it picks the least-loaded slot, which spreads charging out. That keeps the site under its limit '
        'and keeps the BEV monthly subscription (charged per 10 kW block) small. After the route requirement is met, vans are topped up '
        'towards 90% only with cheap or free energy - never at peak and never from storage.'),
      P('The route requirement is calculated from the route itself: stops x battery used per stop + return trip + 10% safety floor + 5% '
        'reserve. For example, Van 1 (22 stops at 2.8% each, 6% to return) needs 83%.'),
      P('4.3 Real-time load balancing', H2),
      bullets(['Available power each step = site limit - building load + rooftop solar + EV storage (if any).',
               'If vans want more than that, a <b>critical</b> van (less than 90 minutes of slack before departure) is charged first, then the '
               'remaining route requirements share the rest, then top-ups. A van below 6 A is paused rather than trickle-charged.',
               'If a van falls behind its plan, it is charged at full power until it catches up - even at peak price if necessary.']),
      P('4.4 Rooftop solar and EV storage', H2),
      P('The site setup asks whether the corporate building has rooftop solar and whether the site has EV storage (an on-site battery). '
        'Anything the site does not have is switched off and shown as "Not installed".'),
      table([['Situation', 'What the agent does'],
             ['Sun is up', 'Solar goes to charging vans first, then fills EV storage. Once storage is full (or at its charge limit) the surplus is pushed to the Corporate Office alongside the grid. Only the remainder is exported (not credited).'],
             ['Before 4 pm', 'Storage is held, filled by solar and - if allowed - topped up with super off-peak / off-peak grid power.'],
             ['4-9 pm peak', 'Storage powers the vans\' required charging first, then the building with whatever is left.'],
             ['Site would exceed its limit', 'Storage discharges to keep the site under the limit, at any time.'],
             ['Grid outage', 'Solar and storage (including the reserve) power the depot at any hour, peak included. In an outage solar serves the loads first so storage depletes more slowly. HVAC is shed and the most urgent vans charge first.'],
             ['Power returns', 'EV storage is recharged from rooftop solar plus the grid, at any hour, until it is full again.'],
             ['No storage installed', 'Charging simply waits for off-peak hours; solar is used directly.']],
            [1.7*inch, 5.3*inch]),
      P('Why vans get first claim on stored energy: when HVAC was forced on (38 kW building load), an earlier version let the building '
        'drain storage at peak. The vans that were planned to charge from storage then had only 12 kW of grid capacity overnight and three '
        'missed their routes. Giving vans priority fixed this in every scenario, at a cost of about $7 a night in normal conditions.', SMALL),
      P('4.5 HVAC control', H2),
      P('The agent follows the rule set for this project: when the building thermostat triggers HVAC, the agent <b>stops it as soon as the '
        'inside is comfortable</b> and <b>re-triggers it only when the temperature falls 5% below the actual temperature at which it was '
        'triggered</b>. Example: trigger at 20.0 &deg;C, stop at 21 &deg;C, re-trigger at 19.0 &deg;C. Each "off" period frees 30 kW for '
        'charging. In the simulation HVAC used 98 kWh per night instead of 118 kWh on a standard thermostat (on at 20 &deg;C, off at 22.5 &deg;C).'),
      PageBreak()]

# 5 Dispatch agent
S += [P('5. The dispatch agent (Dispatch)', H1),
      P('The delivery day starts at 04:30 with each van\'s battery from the overnight depot result. Vans follow simulated routes '
        '(stops placed around a depot near Oakland, CA) with a 30-minute delivery window per stop.'),
      P('5.1 What it decides by itself (low risk)', H2),
      table([['Event', 'Options compared', 'Rule'],
             ['Heavy traffic', 'Wait (+15 min) or reroute (+8 min, +2% battery)', 'Pick the option that keeps battery above the 10% floor and finishes by 14:00, then the fewest late stops, then the shortest delay.'],
             ['Accident / road closure', 'Wait (+35 min) or reroute (+12 min, +3% battery)', 'Same rule. Example: Van 2 rerouted - 0 late stops instead of 14.'],
             ['Live 511 incident', 'Treated as traffic or accident', 'Applied to a van if the incident is within 1.5 km of one of its next six stops.'],
             ['Any delay of 10+ min', '-', 'Affected customers get a delay message with the new ETA.']],
            [1.3*inch, 2.0*inch, 3.7*inch]),
      P('5.2 What it asks a person first (higher risk)', H2),
      bullets(['<b>Reassigning stops</b> to another van - after a breakdown, or when a van cannot finish above the battery floor.',
               '<b>Offering customers a reschedule</b> when no van has enough battery and time.',
               '<b>Pre-departure check</b> - a van that left the depot under-charged gets a proposal before it starts its route.']),
      P('The agent builds a concrete plan - which stop goes to which van, the distance from that van\'s route, and the new ETA - using the '
        'nearest van that can take the stop and still return above 15% battery before 14:00. The day pauses until the dispatcher clicks '
        '<b>Approve</b> or <b>Reject</b> (for example "Keep stops on Van 2" or "Reschedule all instead"). Every decision is logged for audit.'),
      P('5.3 Customer messages', H2),
      P('Three message types: running late (with new ETA), moved to another van (with new ETA), and reschedule offered. When watsonx is '
        'connected, Granite rewrites one template per event in a friendly tone (placeholders are checked so names and times stay correct); '
        'otherwise a built-in template is used. Messages are stored and shown on the Customers page - they are not sent by SMS or email in the MVP.'),
      P('5.4 Example demo day (with the overnight result linked)', H2),
      table([['Time', 'Event', 'Agent decision'],
             ['06:30', 'Van 2 hits an accident', 'Reroute: +12 min, 0 late stops (waiting would make 14 late). Customers informed.'],
             ['07:00', 'Truck 3 in heavy traffic', 'Chosen by the rule; customers with 10+ min delay informed.'],
             ['08:00', 'Van 1 breaks down, 13 stops left', 'Proposes moving all 13 stops to the nearest vans with spare battery. Dispatcher approves.'],
             ['14:00', 'Day complete', '94 of 94 stops delivered, 0 late. Brief generated; batteries feed the next depot night.']],
            [0.7*inch, 2.0*inch, 4.3*inch]),
      P('If the vans were under-charged overnight (for example HVAC forced on and no storage), the pre-departure check proposes '
        'rescheduling 2-3 stops per van so each returns above the floor; rejecting it leaves vans returning with 1-6% battery.', SMALL),
      PageBreak()]

# 5A Agent hierarchy
S += [P('5A. Command agents and specialist agents', H1),
      P('Eleven agents each own one decision. Three <b>command agents</b> sit above them: each reads its agents, reaches one conclusion - '
        '<b>GO</b>, <b>WATCH</b> or <b>ACTION NEEDED</b> - and the worst of the three becomes the <b>depot verdict</b> shown on the Agents tab, '
        'as a chip on the Depot page and in the morning brief. In the app the member agents are rule-based (depot-engine.js) and the commands '
        'are computed on the Depot page; read-only watsonx Orchestrate versions of the commands are in the agents/ folder.'),
      table([['Command', 'Agents', 'ACTION NEEDED when', 'WATCH when'],
             ['Energy Command', 'Power, Solar &amp; Storage, Tariff, Outage resilience, Demand response', 'Breaker trip, or an outage with storage under 20% or no storage', 'Outage, storage refilling, or more than 5 kWh bought at peak'],
             ['Fleet Command', 'Fleet planner, Dispatch, Battery health, Charger faults', 'A van is short of its route charge and no safe route swap exists', 'Swap proposals awaiting approval, vans at risk, open charger faults'],
             ['Business Command', 'Customer communications, Reporting', 'A customer draft is unapproved and the late van departs within 2 hours', 'Drafts awaiting approval, or a customer asked to reschedule']],
            [1.1*inch, 2.0*inch, 2.0*inch, 1.9*inch]),
      Spacer(1, 6),
      table([['Agent', 'What it does', 'Who decides'],
             ['Power', 'Plans each van\'s charge into the cheapest hours, keeps the site under its limit, runs HVAC.', 'Agent'],
             ['Solar &amp; Storage', 'Routes solar (vans, then storage, then the Corporate Office), holds storage for the peak and outages, refills it from solar + grid after an outage.', 'Agent'],
             ['Tariff', 'Sizes the BEV subscription from tonight\'s plan and compares the Corporate Office meter rate with alternatives.', 'Recommends only'],
             ['Outage resilience', 'Estimates how long storage and solar can carry the site, sheds HVAC, ranks vans by urgency.', 'Agent'],
             ['Demand response', 'Estimates the flexibility the site could offer at peak and measures the grid power actually avoided (simulated).', 'Simulated - not enrolled'],
             ['Fleet planner', 'Ranks vans by urgency; when a van cannot reach its route charge, proposes swapping routes with a lighter-route van.', 'Dispatcher approves'],
             ['Dispatch', 'Reroutes or waits on traffic; moving stops or rescheduling customers waits for approval (section 5).', 'Dispatcher approves'],
             ['Battery health', 'Cost per van and per stop, power delivered vs requested, and trends across saved nights (SQLite): falling arrival battery, rising cost per stop, slow charging.', 'Flags only'],
             ['Charger faults', 'Detects a plugged-in van that cannot draw power, opens a maintenance ticket, tracks downtime and tells the planner.', 'Agent opens ticket'],
             ['Customer communications', 'Drafts a heads-up for customers of late vans, escalates when departure is within 2 hours, records replies the dispatcher logs.', 'Dispatcher approves'],
             ['Reporting', 'Writes the daily and monthly fleet-owner report (depot verdict, savings, vans ready, tickets) and queues it.', 'Queued - nothing is emailed']],
            [1.3*inch, 4.3*inch, 1.4*inch]),
      P('Tested in simulation: a charger fault on Van 4 was detected and ticketed and Fleet Command moved to WATCH; a grid outage moved Energy '
        'Command to WATCH with a runtime estimate and, once power returned, storage was refilled from solar + grid; an unapproved customer draft '
        'inside the 2-hour window escalated Business Command to ACTION NEEDED. The headline results in section 7 were re-checked after the '
        'solar-routing change and still hold: $4,212 to about $2,000 a month, peak-priced charging 179 to 1 kWh a night, breaker trips 7 to 0, '
        '5 of 5 vans ready.', SMALL),
      PageBreak()]

# 6 Tariff
S += [P('6. Electricity prices used', H1),
      P('EV charging meter - PG&amp;E Schedule BEV, option BEV-1', H2),
      P('BEV-1 is PG&amp;E\'s business EV rate for a meter dedicated to EV charging, up to 100 kW. Prices are the same every day of the year. '
        'Figures are taken from PG&amp;E\'s tariff sheet, rates effective March 1, 2026 (Advice 7846-E).'),
      table([['Period', 'Hours (every day)', 'Total $/kWh'],
             ['Peak', '4 pm - 9 pm', '$0.35711'],
             ['Off-peak', '9 pm - 9 am and 2 pm - 4 pm', '$0.16510'],
             ['Super off-peak', '9 am - 2 pm', '$0.13844'],
             ['Subscription', 'per 10 kW block per month (replaces demand charges)', '$12.41'],
             ['Overage', 'per kW above the subscription', '$2.48']],
            [1.6*inch, 3.6*inch, 1.8*inch], align_right=(2,)),
      P('Building meter', H2),
      P('The building (HVAC and base load) stays on its own commercial tariff. The default is PG&amp;E B-10 Medium General Demand Service '
        '(secondary voltage) from the OpenEI Utility Rate Database: $0.191-$0.339/kWh, with the higher rate applied 4-9 pm in the model. '
        'Users can pick any tariff the database lists for the depot location (47 found for Oakland).'),
      P('Note: PG&amp;E\'s business EV rates are not in the OpenEI database (only residential EV rates are), which is why BEV-1 is built in '
        'from the tariff sheet.', SMALL)]

# 7 Results
S += [P('7. Results', H1),
      P('All figures come from the app\'s own engine: one typical October night in Oakland, 5 vans, 50 kW site limit, 8 kW building base '
        'load, power-agent HVAC. Monthly = 30 nights like this + the BEV subscription. Only costs that differ between scenarios are compared.'),
      P('7.1 Monthly bill by setup', H2),
      cost_chart(),
      P('Figure 3 - Monthly energy bill. All setups kept 5 of 5 vans ready.', SMALL),
      table([['Setup', 'Monthly bill', 'Peak kWh / night', 'Notes'],
             ['Today: vans charge on arrival', '$4,212', '179', '7 breaker trips per night'],
             ['Smart charging only (no new equipment)', '$2,905', '0', 'All charging moved to off-peak'],
             ['+ 60 kW rooftop solar', '$2,371', '2', '103 kWh of solar charges vans directly'],
             ['EV storage only (100 kWh), cheap-grid top-up', '$2,883', '1', 'Small gain without solar'],
             ['60 kW solar + 100 kWh EV storage', 'about $2,000', '1', '76 kWh from storage at peak'],
             ['Same, with HVAC forced on all night', '$4,874 (vs $7,054)', '1', 'All vans still ready; 0 trips'],
             ['Same, grid outage 16:30-18:30', 'about $1,920', '1', 'Depot keeps running; all vans ready']],
            [2.5*inch, 1.3*inch, 1.1*inch, 2.1*inch], align_right=(1, 2)),
      P('7.2 What drives the saving', H2),
      bullets(['<b>Moving charging out of the peak</b> - the largest single effect, worth about $1,300 a month with no new equipment.',
               '<b>Free rooftop solar</b> charging vans in the afternoon and powering the building - about $530 a month more at 60 kW.',
               '<b>Stored solar used at the peak</b> - about $370 a month more with 100 kWh of storage.',
               '<b>HVAC control</b> - about 20 kWh a night less, and no breaker trips when HVAC and chargers coincide.']),
      P('7.3 Sizing solar and storage', H2),
      P('The Depot page runs the night for 25 combinations of rooftop solar (0-120 kW) and storage (0-200 kWh). Bigger systems keep '
        'lowering the bill, with diminishing returns once solar exceeds what vans, building and storage can absorb (the largest tested, '
        '120 kW + 200 kWh, reaches about $1,310 a month). Because operating savings always favour the largest system, the right size depends '
        'on cost: entering installed-cost quotes ($ per kW of solar, $ per kWh of storage) makes the tool show the size with the fastest '
        'payback. No equipment prices are assumed in this document; incentives, seasonal variation and the value of outage backup are not '
        'included in the payback.'),
      PageBreak()]

# 8 UX
S += [P('8. The application', H1),
      P('Five web pages share one design: a full-width header with an original illustration as background (corporate building with rooftop '
        'solar, EV storage, chargers and vans - drawn in code, no third-party images), a plain-English status line, three or four headline '
        'numbers, and details in tabs.'),
      table([['Page', 'What the user sees'],
             ['Depot', 'Status ("Peak price until 21:00 - EV storage supplying 13 kW"), money saved, price now, vans ready. Price timeline with a "now" marker. '
                       'Live energy-flow diagram (rooftop solar, grid, storage, building, chargers). Van list with battery bar, route requirement and planned charging times. '
                       'Tabs: Savings, Power over time, Corporate Office &amp; HVAC, Size your system, Agents, Activity, Rates &amp; brief. A solar question card on the page (a drop-down of sizes, or no solar) and a Site setup pop-up cover rooftop solar, EV storage and site limits. The Agents tab shows the depot verdict, the three command agents and every agent\'s latest decisions, with controls to approve route swaps and customer drafts and to simulate a charger fault.'],
             ['Dispatch', 'Status, stops delivered, late, customers notified. Approval panel when the agent needs a decision. Large live route map beside a vehicle list. '
                          'Tabs: Agent decisions, What could go wrong? (event buttons), Fleet table, Daily brief.'],
             ['Customers', 'Message counts by type, filter buttons, search, and message cards.'],
             ['History', 'Totals across saved sessions; session list with a detail view (savings, power chart, van table, brief, logs).'],
             ['Architecture', 'System diagram with the command agents, public data sources, MVP scope and this document.']],
            [1.1*inch, 5.9*inch]),
      P('9. Data and technology', H1),
      yrow(table([['Source', 'Used for', 'Access'],
             ['PG&amp;E Schedule BEV tariff sheet', 'EV charging prices and subscription', 'Built in (effective Mar 1, 2026)'],
             ['OpenEI Utility Rate Database', 'Building tariff', 'Live; DEMO_KEY or OPENEI_API_KEY'],
             ['NREL PVWatts v8', 'Hourly solar output for the location', 'NREL_API_KEY; clear-day fallback if blocked'],
             ['Open-Meteo', 'Outdoor temperature', 'No key; typical-day fallback if blocked'],
             ['511 SF Bay', 'Live traffic incidents', 'Free token in SF511_API_KEY'],
             ['OpenStreetMap / CARTO', 'Map tiles', 'No key'],
             ['IBM watsonx.ai (Granite)', 'Briefs and customer wording', 'WATSONX_API_KEY + WATSONX_PROJECT_ID'],
             [P('watsonx Orchestrate', CELLB), P('Operations agent answering questions from saved data', CELL), P('Lab environment; imports agents/ and tools/ files', CELL)],
             [RC('IBM Bob', True), RC('Writing, testing, scanning and deploying the code'), RC('IBM SkillsBuild access, 150 credits')]],
            [2.1*inch, 2.4*inch, 2.5*inch]), 8),
      Spacer(1, 6),
      P('Technology: Python standard library server (no external packages) with SQLite; HTML/CSS/JavaScript pages; Leaflet for the map. '
        'The energy engine (depot-engine.js) has no page code, so the Depot page and the sizing explorer run exactly the same logic. '
        'Stored per session: power samples, agent decisions, approvals, customer messages and the watsonx brief.'),
      PageBreak()]

# 10 Assumptions / limits, 11 roadmap
S += [P('10. Assumptions and limitations', H1),
      bullets(['<b>Simulation, not hardware.</b> Chargers, vans, solar output, storage, building temperature, routes and stop locations are simulated.',
               '<b>One typical night.</b> Monthly figures repeat one October night 30 times; real bills vary with season, weather and routes.',
               '<b>Two meters.</b> Chargers are on a dedicated BEV meter (required for that rate); the building stays on its commercial tariff. '
               'Solar and storage are modelled as able to serve both.',
               '<b>No export credit.</b> Surplus solar exported to the grid is valued at $0.',
               '<b>Outage backup</b> requires specific inverter and transfer-switch hardware at a real site.',
               '<b>Network fallbacks.</b> Where NREL PVWatts or Open-Meteo are blocked, a clear October day and a typical temperature curve are used; the page says so.',
               '<b>Customer messages and owner reports</b> are stored and displayed, not sent. Customer replies are logged by the dispatcher, not received.',
               '<b>Demand response</b> is simulated: it reports the grid power the system avoided at peak but is not enrolled in any utility program and uses no program rates.',
               '<b>Charger power</b> is 7.7 kW (32 A at 240 V) per van; routes use straight lines between stops, not road routing.']),
      P('11. Roadmap', H1),
      yrow(table([['Next step', 'Why'],
             ['Connect real chargers (OCPP) and vehicle telematics', 'Replace simulated charging and battery data with live data.'],
             ['Seasonal and multi-utility tariffs', 'Accurate monthly and annual savings outside October and PG&amp;E territory.'],
             ['Installed-cost quotes and incentives in the sizing tool', 'Turn operating savings into a payback and investment decision.'],
             ['Road-snapped routing and real delivery manifests', 'Realistic ETAs and reroutes.'],
             ['Send customer messages and owner reports (SMS / email / Teams) with opt-in', 'Close the loop with customers and the fleet owner; the agents already draft and queue them.'],
             ['Enrol in a real utility demand-response program', 'Turn the simulated peak flexibility into revenue.'],
             ['Deploy on IBM Cloud with authentication', 'Multi-depot, multi-user operation.'],
             [RC('Python repository built with IBM Bob (fleet_simulator, gateway_controller, watsonx_reporter)'), RC('Matches the coach\'s required repo structure; uses IBM tooling end to end.')],
             [RC('Automated tests and Semgrep security scan with IBM Bob'), RC('Protects the agents\' rules as the code changes; fixes issues before anyone else uses it.')],
             [RC('IBM Cloud deployment pipeline generated with IBM Bob'), RC('Moves the app from a laptop to a shareable URL, with API keys kept as secrets.')],
             [P('watsonx Orchestrate operations agent on the deployed URL', CELL), P('Lets the depot manager ask about readiness, savings and customers in plain English (section 15).', CELL)]],
            [3.2*inch, 3.8*inch]), 10),
      P('12. How to run it', H1),
      P('From the <font face="Courier">ev-depot-mvp</font> folder:'),
      P('<font face="Courier" size="9">python3 server.py</font> &nbsp;then open <font face="Courier" size="9">http://localhost:8000</font>'),
      P('Optional keys, set before starting the server: <font face="Courier" size="8.5">WATSONX_API_KEY</font>, '
        '<font face="Courier" size="8.5">WATSONX_PROJECT_ID</font> (real Granite text), <font face="Courier" size="8.5">SF511_API_KEY</font> '
        '(live traffic), <font face="Courier" size="8.5">NREL_API_KEY</font> and <font face="Courier" size="8.5">OPENEI_API_KEY</font> '
        '(higher rate limits). Without them the app runs fully with clearly labelled fallbacks.'),
      P('13. Suggested 2-3 minute demo', H1),
      yrow(table([['Time', 'Show'],
             ['0:00-0:30', 'The problem: the price timeline on the Depot page - peak 4-9 pm at $0.357/kWh, vans returning at 13:00.'],
             ['0:30-1:30', 'Depot: run the night. Point out solar charging vans, storage covering the peak, "Cold snap" or forced HVAC with no breaker trip, '
                           'and the Savings tab (about $2,000 vs $4,212 a month).'],
             ['1:30-2:15', 'Dispatch: Run demo scenario - accident rerouted automatically, breakdown approval panel, customer messages, watsonx brief.'],
             [P('(in 1:30-2:15)', CELL), P('Ask the watsonx Orchestrate agent "Are all vans ready this morning?" and "How much did we save last night?"', CELL)],
             [RC('2:15-2:30'), RC('IBM Bob building the solution: a 10-15 second clip of Bob generating gateway_controller.py or its tests, then next steps from the roadmap.')]],
            [1.0*inch, 6.0*inch]), 4),
      ]

# 14 IBM Bob (all red)
S += [PageBreak(), R('14. Using IBM Bob (IBM SkillsBuild, 150 credits)', RH1),
      R('IBM Bob is IBM\'s AI development partner, generally available since April 28, 2026. It works across the software lifecycle - planning, '
        'coding, testing, documentation and deployment - with an <b>Architect Mode</b> for designing systems, a <b>Code Mode</b> for writing and '
        'changing code, and built-in <b>Semgrep</b> security scanning. In this project Bob is the <b>development</b> tool; '
        '<b>watsonx.ai Granite</b> stays the AI inside the running app. Together they show IBM tooling both building and powering the solution.'),
      R('14.1 Task plan and credit budget', RH2),
      ytable([[RC('#', True), RC('Task', True), RC('Bob mode', True), RC('Owner', True), RC('Week', True), RC('Credits', True)],
             [RC('1'), RC('Python repository: fleet_simulator.py, gateway_controller.py, watsonx_reporter.py, ported from depot-engine.js'), RC('Architect, then Code'), RC('Engine lead'), RC('Oct 19-25'), RC('35')],
             [RC('2'), RC('Automated tests for the agents\' rules (14.2)'), RC('Code'), RC('Engine lead'), RC('Oct 26-Nov 1'), RC('25')],
             [RC('3'), RC('watsonx Orchestrate operations agent: check and import agents/ and tools/ files'), RC('Code'), RC('AI &amp; Platform lead'), RC('Oct 26-Nov 1'), RC('25')],
             [RC('4'), RC('Security scan (Semgrep), fixes, sign-in'), RC('Code + Semgrep'), RC('Engine lead'), RC('Nov 2-8'), RC('15')],
             [RC('5'), RC('IBM Cloud deployment (needed so Orchestrate can reach the API)'), RC('Architect, then Code'), RC('AI &amp; Platform lead'), RC('Nov 2-8'), RC('25')],
             [RC('6'), RC('README and API documentation'), RC('Code'), RC('Product &amp; Delivery lead'), RC('Nov 9-15'), RC('10')],
             [RC(''), RC('Reserve for fixes and re-runs', True), RC(''), RC(''), RC(''), RC('15')],
             [RC(''), RC('Total', True), RC(''), RC(''), RC(''), RC('150', True)]],
            [0.3*inch, 2.6*inch, 1.0*inch, 1.2*inch, 0.95*inch, 0.65*inch], zebra=False, align_right=(5,)),
      Y('<b>Graded evidence:</b> each task is one Bob session, and each session report is exported to <font face="Courier">bob_sessions/</font>. '
        'Credits are logged per task in <font face="Courier">docs/bob-tasks/credit-log.md</font>; ready-to-paste task briefs with acceptance '
        'criteria are in <font face="Courier">docs/bob-tasks/</font>. The lab permits Claude and Antigravity, which were used for the prototype; '
        'Bob is used for these tracked build steps.'),
      R('The credit amounts are a <b>planned split of the 150 credits, not Bob\'s price list</b> - we don\'t yet know how many credits each '
        'task uses. Run task 1 first, check how many credits it actually consumed, and rescale the remaining tasks. Tasks 1-3 matter most '
        'for the MVP submission; 4-6 can wait if credits run short.', ParagraphStyle('rs', parent=SMALL, textColor=REDC)),
      R('14.2 Tests Bob should write', RH2),
      ListFlowable([ListItem(R(t), leftIndent=12) for t in [
          '<b>No peak charging:</b> on a normal night, charging buys almost no grid power between 16:00 and 21:00 unless a van is critical.',
          '<b>Site limit:</b> total grid import never exceeds the site limit (0 breaker trips) in any scenario.',
          '<b>Every van ready:</b> all vans reach their route requirement by departure - including forced HVAC and a peak-time outage.',
          '<b>Storage priority:</b> during the peak, EV storage serves the vans\' required charge before the building; top-ups never use storage.',
          '<b>No storage, no use:</b> when the site setup says "no EV storage", storage is never used.',
          '<b>HVAC rule:</b> HVAC stops at the comfortable temperature and re-triggers only 5% below the actual trigger temperature.',
          '<b>Approval required:</b> the dispatch agent never reassigns stops or reschedules customers without approval (unless switched off).',
          '<b>Wait vs reroute:</b> a reroute that would take the battery below the 10% floor is never chosen.',
          '<b>Costs:</b> BEV-1 prices and subscription blocks are applied correctly per period.']],
          bulletType='bullet', start='•', leftIndent=12, bulletFontSize=8, bulletColor=REDC, spaceAfter=6),
      R('14.3 Starter prompts', RH2),
      R('Task 1 (Architect Mode):', ParagraphStyle('rb', parent=RBODY, fontName='Helvetica-Bold', spaceAfter=2)),
      R('Read depot-engine.js, dispatch.html and server.py. Design a Python package with fleet_simulator.py (vans plug in, report state of '
        'charge), gateway_controller.py (the charging planner, load balancer, EV storage and HVAC rules - same behaviour as depot-engine.js) and '
        'watsonx_reporter.py (sends the session summary to watsonx Granite and prints the brief). Keep the existing server API unchanged.', RCODE),
      R('Task 2 (Code Mode):', ParagraphStyle('rb2', parent=RBODY, fontName='Helvetica-Bold', spaceAfter=2)),
      R('Write pytest tests for gateway_controller.py covering every rule in section 14.2 of the solution PDF. Use the five-van fleet from '
        'common.js and the PG&amp;E BEV-1 prices. Each test runs one simulated night and asserts the rule.', RCODE),
      R('Task 4 (Code Mode + Semgrep):', ParagraphStyle('rb3', parent=RBODY, fontName='Helvetica-Bold', spaceAfter=2, backColor=YEL)),
      R('Scan server.py and the HTML/JS pages. Fix input validation on the /api endpoints, make sure API keys are never sent to the browser '
        'or logged, and add a simple sign-in so only the depot team can use the app.', RCODE),
      R('14.4 Making 150 credits go further', RH2),
      ListFlowable([ListItem(R(t), leftIndent=12) for t in [
          'Give Bob the existing files as context instead of describing the logic - the behaviour is already written and tested.',
          'Plan once in Architect Mode, then implement file by file in Code Mode; keep each request to one file or one feature.',
          'Review each change before asking for another; avoid regenerating whole files to fix small issues.',
          'Check the credit balance after each task and stop at the reserve (<font backColor="#fff3a3">15 credits</font>) to keep room for fixes.',
          '<font backColor="#fff3a3">Ready-to-paste briefs for all six tasks, with owners, weeks and acceptance criteria, are in docs/bob-tasks/.</font>']],
          bulletType='bullet', start='•', leftIndent=12, bulletFontSize=8, bulletColor=REDC, spaceAfter=6),
      R('Source: IBM newsroom, "Introducing IBM Bob: AI Development Partner..." (April 28, 2026) and IBM\'s Project Bob announcement. Feature '
        'details come from IBM materials; productivity claims in those materials are IBM-reported.', ParagraphStyle('rsrc', parent=SMALL, textColor=REDC)),
      ]

# 15-17 lab alignment (yellow)
S += [PageBreak(), Y('15. watsonx Orchestrate operations agent', YH1),
      Y('A read-only operations agent on watsonx Orchestrate lets the depot manager and dispatcher ask about the operation in plain English. '
        'It reads saved depot nights, delivery days and customer messages through the Depot EV API, and answers with real numbers. It never '
        'approves, reassigns, reschedules or changes charging - people make those decisions in the app.'),
      Spacer(1, 6),
      ytable([['Tool (operationId)', 'What the agent uses it for'],
              ['list_sessions', 'Find the latest depot night or delivery day'],
              ['get_session', 'Vans ready, cost with and without the system, peak kWh, HVAC, agent decisions, approvals, the watsonx brief'],
              ['list_customer_messages', 'Delay, moved-to-another-van and reschedule messages'],
              ['find_building_tariffs', 'Commercial tariffs near the depot (OpenEI)'],
              ['get_live_traffic', 'Active 511 incidents near the depot']],
             [2.0*inch, 5.0*inch]),
      Spacer(1, 6),
      Y('<b>Example questions:</b> "Are all vans ready this morning?" &middot; "How much did we save last night?" &middot; "How much did we buy at '
        'peak?" &middot; "Which customers were told about delays today?" &middot; "Is there live traffic near the depot?"'),
      Spacer(1, 4),
      Y('<b>Files:</b> <font face="Courier">agents/depot_ops_agent.yaml</font> (operations assistant), <font face="Courier">energy_command.yaml</font>, <font face="Courier">fleet_command.yaml</font> and <font face="Courier">business_command.yaml</font> (read-only command agents with the same GO / WATCH / ACTION NEEDED rules) and '
        '<font face="Courier">tools/depot-api.openapi.yaml</font> (API tools). Orchestrate runs in IBM Cloud, so the API must be reachable '
        'from the internet - a temporary secure tunnel for testing, the IBM Cloud deployment (Bob task 5) for the demo. Field names are '
        'checked against the lab\'s Orchestrate version in Bob task 3.'),

      PageBreak(), Y('16. Alignment with the AI Experiential Learning Lab', YH1),
      Y('The official build and submission instructions are released inside the lab portal; the table below combines the public lab page '
        '(dates, IBM Bob and watsonx tools) with practices seen in another Fall 2026 team\'s public repository. Items marked "confirm" '
        'should be checked against the portal.', YSMALL),
      Spacer(1, 6),
      ytable([['Lab expectation', 'How Depot EV meets it', 'Status'],
              ['IBM Bob as the build tool', 'Six tracked Bob tasks: Python repo, tests, Orchestrate agent, security, deploy, docs', 'Planned Oct 19 - Nov 15'],
              ['Bob session reports (graded in other teams\' repos)', 'One exported report per task in bob_sessions/, credits logged', 'Planned; confirm format'],
              ['watsonx products', 'Granite for briefs and customer messages; Orchestrate operations agent', 'Granite ready; Orchestrate planned'],
              ['Agentic AI with a person in control', 'Agents act on low-risk choices; reassigning and rescheduling need approval', 'Done'],
              ['Real industry use case', 'EV delivery fleet: peak prices, site limits, solar and storage, delivery disruption', 'Done'],
              ['Team of 1-5 with a technical member', 'Team of 3: two technical leads plus a product and delivery lead', 'Done'],
              ['Cohort theme', 'Energy, sustainability and logistics', 'Confirm in portal'],
              ['Portfolio-ready project', 'Working app, solution PDF, GitHub repo with README (Bob task 6)', 'App and PDF done; repo planned'],
              ['Lab timeline', 'Submit by Nov 20 (lab ends Nov 22, results Dec 10)', 'Planned']],
             [2.1*inch, 3.5*inch, 1.4*inch]),

      Spacer(1, 10), Y('17. Team, roles and roadmap', YH1),
      ytable([['Role', 'Name', 'Owns'],
              ['Engine lead (technical)', '[Name]', 'Charging, storage and HVAC logic; Python repo (Bob 1); tests (Bob 2); security (Bob 4)'],
              ['AI &amp; Platform lead (technical)', '[Name]', 'watsonx Granite connection; Orchestrate agent (Bob 3); IBM Cloud deploy (Bob 5); Bob credit log'],
              ['Product &amp; Delivery lead', '[Name]', 'Business case, solution PDF, demo script and video, docs (Bob 6), mentor contact, submission']],
             [1.9*inch, 1.0*inch, 4.1*inch]),
      Spacer(1, 10),
      ytable([['Week', 'Dates', 'Milestone', 'Owner(s)'],
              ['1', 'Oct 19-25', 'Confirm theme and submission rules in the portal; GitHub repo; Bob 1 Python repo', 'All; Engine lead'],
              ['2', 'Oct 26-Nov 1', 'Bob 2 tests; Bob 3 Orchestrate agent (via tunnel); watsonx Granite keys connected', 'Engine; AI &amp; Platform'],
              ['3', 'Nov 2-8', 'Bob 4 security; Bob 5 IBM Cloud deploy; Orchestrate on the deployed URL', 'Engine; AI &amp; Platform'],
              ['4', 'Nov 9-15', 'Bob 6 docs; final PDF; record the 2-3 minute video; mentor review', 'Product &amp; Delivery; all'],
              ['5', 'Nov 16-22', 'Buffer and fixes; submit by Nov 20 (deadline Nov 22)', 'All']],
             [0.5*inch, 1.0*inch, 3.9*inch, 1.6*inch]),
      Spacer(1, 8),
      Y('<b>Working agreements:</b> a weekly 30-minute check-in that updates the plan and the Bob credit log; one Bob task per session with '
        'its report exported; every change reviewed by a second team member before merge. The same plan is kept in '
        '<font face="Courier">docs/TEAM_PLAN.md</font>.'),
      ]

# Appendix
S += [P('Appendix - fleet used in the simulation', H2),
      table([['Van', 'Battery', 'Returns', 'Battery on return', 'Stops', 'Packages', 'Departs', 'Needs'],
             ['Van 1', '80 kWh', '13:00', '16%', '22', '60', '05:00', '83%'],
             ['Van 2', '80 kWh', '13:15', '18%', '16', '45', '05:45', '69%'],
             ['Truck 3', '100 kWh', '13:30', '20%', '24', '110', '04:30', '64%'],
             ['Van 4', '80 kWh', '14:00', '17%', '14', '38', '05:45', '63%'],
             ['Van 5', '60 kWh', '14:30', '15%', '18', '52', '05:30', '79%']],
            [0.8*inch, 0.8*inch, 0.8*inch, 1.1*inch, 0.6*inch, 0.8*inch, 0.8*inch, 0.7*inch]),
      P('When a Dispatch day has been run, each van returns with the battery it actually had left; the table shows the defaults.', SMALL)]

doc.build(S)
print('wrote', OUT)
