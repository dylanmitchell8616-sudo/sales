# Realside AI — Audience Strategy & Retargeting Framework

---

## Meta Ads Audience Architecture

### Tier 1: Cold Audiences (Top of Funnel)

#### Audience A: Interest Stack — All Trades
- **Age:** 30–60
- **Gender:** Male
- **Location:** United States
- **Interests (AND/OR stacking):**
  - Small business owners OR Business page admins
  - AND: Home services, HVAC, Plumbing, Roofing, Electrical, Landscaping, Auto repair, General contracting
- **Exclusions:** Exclude all custom audiences (website visitors, video viewers, existing leads, customers)
- **Budget allocation:** 30% of cold budget
- **Notes:** Broad enough for Meta to optimize, specific enough to hit trades owners

#### Audience B: Interest Stack — Vertical-Specific (Create one per vertical)
- **HVAC audience:** Interests = HVAC + Air conditioning + Heating + Furnace + Small business owners
- **Plumbing audience:** Interests = Plumbing + Plumber + Drain cleaning + Small business owners
- **Roofing audience:** Interests = Roofing + Roofing contractor + Storm damage repair + Small business owners
- **Electrical audience:** Interests = Electrician + Electrical contractor + Electrical wiring + Small business owners
- **Why separate:** You can test which vertical converts cheapest, then scale the winner
- **Budget allocation:** 30% of cold budget (split evenly or weight toward priority verticals)

#### Audience C: Lookalike — Customer List (1%)
- **Source:** Upload customer list (emails + phone numbers) — minimum 100 contacts
- **Lookalike %:** 1% (start narrow, expand later)
- **Location:** United States
- **Budget allocation:** 20% of cold budget
- **Notes:** This is usually your best-performing cold audience once you have enough data. Start with interest stacks until you have 100+ customers.

#### Audience D: Lookalike — Demo Bookers (1%)
- **Source:** Custom audience of everyone who's booked a demo (even if they didn't close)
- **Lookalike %:** 1%
- **Location:** United States
- **Budget allocation:** 10% of cold budget

#### Audience E: Broad — Let Meta Optimize
- **Age:** 30–60
- **Gender:** Male
- **Location:** United States
- **Interests:** NONE — fully broad
- **Exclusions:** Exclude all custom audiences
- **Budget allocation:** 10% of cold budget
- **Notes:** This sounds crazy but broad targeting with strong creative often outperforms interest stacking at scale. Test it with your best-performing ad. Meta's algorithm will find the right people.

---

### Tier 2: Warm Audiences (Middle of Funnel)

#### Audience F: Video Viewers — 50%+ Watched
- **Source:** Custom audience from video ad engagement
- **Criteria:** People who watched 50% or more of any video ad
- **Window:** Last 30 days
- **Why:** They were interested enough to watch half your video. They know who you are. Hit them with proof and testimonials.

#### Audience G: Video Viewers — 75%+ Watched
- **Source:** Custom audience from video ad engagement
- **Criteria:** People who watched 75% or more of any video ad
- **Window:** Last 60 days
- **Why:** These are highly engaged. They're close. Push them with direct CTA and urgency.

#### Audience H: Website Visitors — All Pages
- **Source:** Meta Pixel — all website visitors
- **Window:** Last 30 days
- **Exclusions:** Exclude people who already booked (thank you page visitors)
- **Why:** They clicked through but didn't book. Retarget with objection-busting content and proof.

#### Audience I: Page Engagers
- **Source:** Facebook page + Instagram profile engagement
- **Criteria:** Anyone who interacted with your page (liked, commented, shared, clicked, messaged)
- **Window:** Last 60 days
- **Why:** They've engaged with your brand but haven't converted. Warm and familiar.

#### Audience J: Lead Form Openers (Didn't Submit)
- **Source:** Lead gen form engagement
- **Criteria:** Opened the form but didn't complete it
- **Window:** Last 30 days
- **Why:** These people were one tap away from booking. High intent, just need a nudge.

---

### Tier 3: Hot Audiences (Bottom of Funnel)

#### Audience K: Demo/Pricing Page Visitors
- **Source:** Meta Pixel — visitors to /demo or /pricing pages
- **Window:** Last 14 days
- **Exclusions:** Exclude booked demos (thank you page visitors)
- **Why:** Highest intent website visitors. They were checking pricing or trying to book. Hard close.

#### Audience L: Lead Form Openers — Recent
- **Source:** Lead gen form engagement
- **Criteria:** Opened form but didn't submit
- **Window:** Last 7 days (tighter window = hotter intent)
- **Why:** Very recent, very high intent. Hit them with urgency or scarcity.

#### Audience M: CRM Contacts — Not Booked
- **Source:** Upload list of leads from CRM who never booked a demo
- **Window:** Ongoing (refresh monthly)
- **Why:** They gave you their info somewhere. Retarget to re-engage.

---

## Retargeting Ad Strategy by Tier

### Warm Retargeting (Audiences F–J)
**Goal:** Build trust, handle objections, show proof

**Best ad types:**
- Testimonial video (customer talking about results)
- Case study static image (before/after numbers)
- "How it works" carousel (3 slides: Build → Plug In → Runs Your Phones)
- Objection-buster copy ("Won't my customers know it's AI?")

**Frequency cap:** 2–3 impressions per day max
**Duration:** Retarget for 30 days, then rotate creative

### Hot Retargeting (Audiences K–M)
**Goal:** Get the booking. Direct CTA. Remove friction.

**Best ad types:**
- Simple image or text card with strong CTA
- Short video (15 sec) — just the offer and the link
- Urgency/scarcity messaging ("10 spots this month")
- Direct testimonial quote + "Book now"

**Frequency cap:** 3–4 impressions per day (higher frequency OK for hot audience)
**Duration:** Retarget for 14 days, then rotate creative

---

## Audience Refresh Schedule

| Task | Frequency |
|------|-----------|
| Refresh customer list upload | Monthly |
| Refresh CRM non-booked leads list | Monthly |
| Update lookalike audiences | Every 60 days (as source audience grows) |
| Review audience overlap (Ads Manager tool) | Every 2 weeks |
| Prune underperforming audiences | Weekly (kill anything spending with no results after 2x CPA) |
| Rebuild video viewer audiences for new creatives | Every time you launch new video ads |

---

## Exclusion Rules (Critical — prevents wasted spend)

| Audience | Exclude From |
|----------|-------------|
| Existing customers | ALL campaigns (cold, warm, hot) |
| Demo bookers (booked & showed) | ALL campaigns |
| All warm/hot audiences | Cold campaigns (don't pay cold CPMs for people who already know you) |
| All hot audiences | Warm campaigns (don't retarget hot leads with warm content) |

**How to enforce:** Use the Audience Exclusion feature in each ad set. Check this every time you create a new campaign or ad set.

---

## Scaling Playbook

### Phase 1: Test ($3K–$5K/month)
- Run 3–5 cold ad sets with different audiences
- Run 1 warm retargeting ad set
- Run 1 hot retargeting ad set
- Identify winning audience + winning creative combo
- **Goal:** Find your baseline CPL (cost per demo booked)

### Phase 2: Validate ($5K–$10K/month)
- Double down on winning cold audience
- Test 2 new verticals as separate ad sets
- Expand lookalike from 1% to 2%
- Add new creative (fresh angles, new videos)
- **Goal:** Confirm CPL holds as you scale

### Phase 3: Scale ($10K–$25K/month)
- Horizontal scaling: duplicate winning ad sets to new audiences
- Vertical scaling: increase budget on winners by 20% every 3 days
- Launch broad targeting with best creative
- Build lookalike off 75% video viewers
- Add geo-targeting campaigns for specific metro areas with high density of target businesses
- **Goal:** Maximize volume while keeping CPA under target

### Phase 4: Diversify ($25K+/month)
- Add YouTube ads (pre-roll with demo video)
- Test Google Ads (search intent: "answering service for HVAC")
- Add LinkedIn (for larger companies / operations managers — secondary ICP)
- Launch referral program for existing customers
- Test direct mail to complement digital
- **Goal:** Multi-channel acquisition machine
