# Realside AI — Landing Page Wireframe & Copy

**URL:** realside.ai/demo
**Purpose:** Convert ad traffic into booked demo calls
**Design:** Mobile-first. Clean. Fast-loading. No navigation menu (remove exit points).

---

## SECTION 1: Hero (Above the Fold)

### Layout:
- Full-width background: dark navy or charcoal
- Left side: headline + subhead + CTA
- Right side: embedded video (30-sec voice agent call demo) or phone mockup showing the agent in action

### Copy:

**Headline (Default — rotate based on ad source):**
> Stop Losing Jobs to Voicemail. Start Booking Them Automatically.

**Vertical-specific headline variants (match to ad):**
- HVAC: "Your AI Dispatcher That Never Misses a Call"
- Plumbing: "Every Emergency Call Answered. Every Job Booked. 24/7."
- Roofing: "Capture Every Storm Lead Without Hiring Another Person"
- General: "Every Call Answered. Every Lead Followed Up. No Staff Required."

**Subhead:**
> AI voice agents built for service businesses. We answer your calls, qualify leads, and book jobs — day, night, weekends, holidays. Sounds like a real person. Works with your existing tools.

**CTA Button:** Book Your Free 15-Minute Demo
**Sub-CTA text:** No contracts. No commitment. Just a live walkthrough.

**Trust bar (below CTA):**
> "Works with ServiceTitan, Jobber, Housecall Pro, and more"
> [Logos of integration partners]

---

## SECTION 2: Pain Point Block

### Layout:
- 3-column layout (stacks on mobile)
- Each column has an icon + stat + one-liner

### Copy:

**Column 1:**
📞 **30–40% of your calls go unanswered**
Every missed call is a job your competitor gets instead.

**Column 2:**
⏱️ **If you don't call back in 5 minutes, you lose 80% of leads**
Speed wins. Our voice agent answers in 1 ring.

**Column 3:**
🌙 **After-hours calls go to voicemail — and voicemail doesn't book jobs**
Our agent works 24/7. Nights, weekends, holidays. No exceptions.

---

## SECTION 3: How It Works

### Layout:
- 3-step horizontal flow (stacks on mobile)
- Clean icons or simple illustrations

### Copy:

**Step 1: We Build It**
We create a custom voice agent trained on your business — your services, your service area, your booking process.

**Step 2: We Plug It In**
We integrate with your existing tools (ServiceTitan, Jobber, Housecall Pro, etc.) and set up your call routing. No IT team needed.

**Step 3: It Runs Your Phones**
Every inbound call gets answered, qualified, and booked — automatically. You get the details in real time.

**Below the steps:**
> Setup takes 5–7 days. Most businesses are ROI-positive within 2 weeks.

**CTA Button:** Book Your Free Demo

---

## SECTION 4: Live Demo Audio

### Layout:
- Centered section with waveform audio player
- Quote card below the player

### Copy:

**Section header:**
> Hear It For Yourself

**Description:**
> This is a real call handled by one of our voice agents for an HVAC company. Not scripted. Not staged. Press play.

[Audio player — embedded call recording]

**Quote below:**
> "I listened to the first call recording and thought it was my office manager. It wasn't. It was the AI." — {{client_name}}, {{company_name}}

---

## SECTION 5: Results / Social Proof

### Layout:
- 3 stat cards in a row
- Below: 2–3 testimonial cards with photo, name, company, quote

### Stats:

| Stat | Label |
|------|-------|
| $8K–$25K/mo | Revenue recovered from missed calls |
| 24/7/365 | Calls answered — no holidays, no sick days |
| < 1 ring | Average answer time |

### Testimonials:

**Testimonial 1:**
> "We were missing 35 calls a week. Now every single one gets answered. We added $18K in revenue the first month."
> — [Name], [HVAC Company], [City, State]

**Testimonial 2:**
> "I thought my customers would hate talking to AI. Turns out they just want someone to pick up. Our booking rate is up 40%."
> — [Name], [Plumbing Company], [City, State]

**Testimonial 3:**
> "We booked 23 extra jobs last month. All from calls we used to miss. I don't know why I didn't do this sooner."
> — [Name], [Roofing Company], [City, State]

*(Replace with real testimonials as they come in. Until then, use "Results from early clients" framing or remove section.)*

---

## SECTION 6: Integration Logos

### Layout:
- Simple horizontal logo bar
- Light gray background

### Copy:

**Header:** Works With the Tools You Already Use

[Logos: ServiceTitan, Jobber, Housecall Pro, Google Calendar, Zapier, QuickBooks]

---

## SECTION 7: FAQ

### Layout:
- Accordion-style FAQ
- Clean, minimal

### Questions & Answers:

**Q: Will my customers know they're talking to AI?**
A: Most can't tell. Our voice agents are trained on thousands of real service calls. They greet naturally, ask the right questions, and handle conversations the way your best front-desk person would. And honestly — customers care more about getting helped fast than who's helping them.

**Q: How much does it cost?**
A: It depends on your call volume and setup, but it's a fraction of what you'd pay a full-time receptionist — and it works 24/7 with no sick days, no overtime, and no training period. We'll walk you through pricing on the demo call.

**Q: What if the AI can't handle a call?**
A: If a call is too complex or the caller asks for a real person, the voice agent routes it directly to you or your team. It's not replacing you — it's making sure no call ever goes unanswered.

**Q: How long does setup take?**
A: 5–7 business days from kickoff to live. We handle everything — building the agent, integrating with your tools, testing, and going live. You don't need any technical skills.

**Q: Does it work with my CRM / scheduling software?**
A: Yes. We integrate with ServiceTitan, Jobber, Housecall Pro, Google Calendar, and most other tools used by service businesses. If you use something else, we'll figure it out.

**Q: What if I already have a receptionist?**
A: Great — the voice agent handles the calls she can't get to. When she's on another line, on break, or after hours, the AI picks up. Think of it as her 24/7 backup.

**Q: Is there a contract?**
A: [Adjust based on your actual terms.] We keep things simple. No long-term lock-ins. We earn your business every month.

---

## SECTION 8: Final CTA Block

### Layout:
- Full-width, high-contrast background (brand color or dark)
- Centered text + CTA button

### Copy:

**Headline:**
> Every Missed Call Is a Missed Job. Let's Fix That.

**Subhead:**
> Book a free 15-minute demo. We'll show you exactly how the voice agent works for your business. No pressure. No pitch deck. Just proof.

**CTA Button:** Book Your Free Demo

**Below button:**
> Takes 15 minutes. Most people book before the demo is over.

---

## Technical Requirements

- [ ] **Mobile-first responsive design** (90%+ traffic from Meta ads is mobile)
- [ ] **Page load < 3 seconds** (compress images, lazy load video)
- [ ] **No top navigation** (remove exit points — the only action is booking)
- [ ] **Meta Pixel installed** with events: PageView, ViewContent, Lead, Schedule
- [ ] **UTM parameter handling** — pass through to booking form for attribution
- [ ] **Calendly or Cal.com embed** — inline, not popup (reduces friction)
- [ ] **Thank you page redirect** after booking (for conversion tracking + pixel firing)
- [ ] **Heatmap tracking** (Hotjar or Microsoft Clarity) — see where people drop off
- [ ] **A/B test ready** — ability to swap headlines for ad-matching variants
