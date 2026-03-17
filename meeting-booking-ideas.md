# Meeting Booking Ideas — Fully Automated with Claude Code

Everything below can be built as scripts in this repo and run on autopilot with Claude Code + cron/GitHub Actions. No Clay, no manual enrichment — just web scraping, public APIs, and Claude.

---

## 1. Prospect Website Scraper + Personalized Email Generator

**Script: `prospect_researcher.py`**

- Takes a CSV of target company domains
- Uses web fetching to scrape their homepage, /about, /blog, /careers pages
- Claude analyzes the content and generates a hyper-personalized cold email per company referencing their actual product, recent blog posts, or job openings
- Outputs a CSV of ready-to-send emails

**Why it books meetings:** Every email references something real and specific about the company. No generic templates.

---

## 2. Job Board Monitor → Outreach Generator

**Script: `job_signal_monitor.py`**

- Scrapes public job boards (LinkedIn jobs, Indeed, company career pages) for keywords related to your product space
- If a company posts a job for "Sales Operations Manager" and you sell sales tooling — that's a buying signal
- Claude generates outreach: "Saw you're hiring a Sales Ops Manager — companies in that stage usually struggle with X. We solve that so your new hire can hit the ground running."
- Run daily via cron, outputs new leads + draft emails

**Why it books meetings:** You're reaching out at the exact moment they have the pain.

---

## 3. LinkedIn/Twitter Content Monitor → Warm Outreach

**Script: `social_listener.py`**

- Monitors public RSS feeds, blog posts, or social profiles of target prospects
- When a prospect posts about a topic related to your product, Claude generates a reply or email that references their specific take
- "Your post about [topic] resonated — we've seen the same thing with our customers. Would love to share what's working."

**Why it books meetings:** Referencing someone's own content is the highest-converting cold outreach pattern.

---

## 4. Automated ICP List Builder from Public Data

**Script: `icp_list_builder.py`**

- Scrapes public directories, YC company lists, ProductHunt launches, Crunchbase (free tier), G2 categories
- Filters by your ICP criteria (industry, size signals from employee count on LinkedIn, tech keywords on their site)
- Claude scores and ranks each company, writes a one-liner on why they're a fit
- Outputs a prioritized prospecting list with personalized angles

**Why it books meetings:** You always have a fresh, ranked list to work from instead of guessing who to target.

---

## 5. Competitor Review Mining → Displacement Outreach

**Script: `competitor_review_miner.py`**

- Scrapes public review sites (G2, Capterra, TrustRadius) for negative reviews of your competitors
- Identifies common pain points and the companies leaving those reviews
- Claude generates displacement emails: "Saw your team has been struggling with [specific pain from review] on [Competitor]. We built [Product] specifically to fix that."

**Why it books meetings:** You're targeting people who already expressed dissatisfaction with the status quo. They're pre-qualified.

---

## 6. Conference/Event Attendee Outreach

**Script: `event_outreach.py`**

- Scrapes public speaker lists, attendee lists, sponsor lists from conference websites
- Cross-references with your target accounts
- Claude generates pre-event or post-event outreach: "Saw you're speaking at [Event] about [Topic] — would love to connect while we're both there."
- Can also scrape session recordings/summaries after the event for follow-up hooks

**Why it books meetings:** Events create natural conversation starters and time pressure.

---

## 7. News/PR Trigger Outreach

**Script: `news_trigger.py`**

- Monitors Google News, RSS feeds, or press release sites for target accounts
- Triggers on: funding announcements, product launches, leadership changes, acquisitions, expansions
- Claude generates timely outreach tied to the news: "Congrats on the Series B — companies at your stage usually start hitting [pain point]. Happy to share how [similar company] handled it."
- Run daily, auto-generates drafts

**Why it books meetings:** Timeliness is everything. Reaching out within 48 hours of a trigger event dramatically increases reply rates.

---

## 8. Automated Follow-Up Sequence Writer

**Script: `followup_generator.py`**

- Takes your existing outreach CSV (who you emailed, when, what you said)
- Claude generates a 3-5 touch follow-up sequence for each prospect, each email adding new value (case study, relevant insight, social proof)
- Spaces them out on a schedule, outputs calendar-ready send dates
- Each follow-up is unique — not "just bumping this to the top of your inbox"

**Why it books meetings:** Most meetings are booked on follow-up 3-5, not email 1. Automating follow-ups with real value keeps the pipeline moving.

---

## 9. Case Study Matcher

**Script: `case_study_matcher.py`**

- Maintains a library of your case studies/customer stories (stored as markdown in this repo)
- When prospecting, Claude matches each prospect to the most relevant case study based on industry, company size, pain point
- Generates outreach that leads with the matched story: "We helped [Similar Company] do [Result]. Your team at [Prospect] looks like you're in a similar spot."

**Why it books meetings:** Social proof from a similar company is the #1 objection killer.

---

## 10. Inbound Lead Research + Instant Response Drafts

**Script: `inbound_responder.py`**

- When a new inbound lead comes in (via webhook, form submission CSV, or email parse), Claude instantly:
  - Scrapes their website and LinkedIn
  - Identifies their likely pain points
  - Drafts a personalized response that references their company specifically
  - Suggests 3 meeting times based on your calendar availability
- Speed-to-lead is the #1 predictor of inbound conversion. This gets you from form fill to personalized reply in under 60 seconds.

**Why it books meetings:** Responding in <5 minutes makes you 100x more likely to connect vs. responding in 30 minutes.

---

## How to Run These

Each script can be:
- Run manually: `python prospect_researcher.py --input targets.csv`
- Scheduled via cron: `0 8 * * * cd /home/user/sales && python news_trigger.py`
- Triggered by GitHub Actions on a schedule
- Chained together: news_trigger → followup_generator → output ready-to-send emails

All outputs go to CSV files you can import into your email tool or CRM.

---

## Recommended Build Order (Start Here)

1. **Prospect Website Scraper** (#1) — immediate ROI, personalized emails today
2. **Follow-Up Sequence Writer** (#8) — multiply your existing outreach effort
3. **News Trigger Outreach** (#7) — daily warm leads on autopilot
4. **Job Board Monitor** (#2) — intent-based prospecting
5. **Competitor Review Mining** (#5) — pre-qualified displacement targets
