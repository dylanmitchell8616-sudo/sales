# Meeting Booking Ideas with Claude Code + Clay

## 1. Signal-Based Prospecting (Warm Outbound)

**Use Clay to surface buying signals, then Claude Code to act on them instantly.**

- **New hires in target roles**: Use Clay's `current_role_max_months_since_start_date` filter to find new VPs/Directors/Heads of at target accounts who joined in the last 90 days. New leaders are 3x more likely to buy — they have budget and mandate to make changes.
- **Headcount growth spikes**: Enrich accounts with `Headcount Growth` to find companies scaling fast. Growing teams = growing pain points = budget.
- **Recent funding rounds**: Use `Latest Funding` enrichment to identify companies that just raised. They have cash to spend and pressure to deploy it.
- **Open job postings**: Use `Open Jobs` enrichment to find companies hiring for roles your product replaces or augments. If they're hiring 5 SDRs, they might need your sales tool instead.
- **Tech stack changes**: Use `Tech Stack` enrichment to find companies using a competitor or complementary tool. Build outreach around switching costs or integration value.

## 2. Account Research Automation

**Before every outreach, auto-research the account so messaging is hyper-relevant.**

- Build a script that takes a list of target accounts, uses Clay to pull `Recent News`, `Company Competitors`, `Revenue Model`, and `Website Traffic`, then uses Claude to generate a 2-sentence personalized opener per account.
- Use `ask-question-about-accounts` on your Salesforce accounts to identify stalled deals that need re-engagement. Ask: "Which accounts had positive Gong calls but no follow-up in 30 days?"

## 3. Multi-Threading into Accounts

**Don't just email one person — build a contact map and multi-thread.**

- Use `find-and-enrich-contacts-at-company` to find 3-5 stakeholders per target account (the economic buyer, the champion, the end user, the blocker).
- Enrich each with `Email` + `Summarize Work History` + `Find Thought Leadership`.
- Use Claude Code to generate tailored messages for each persona:
  - VP gets the ROI pitch
  - Director gets the operational efficiency angle
  - End user gets the "make your life easier" angle
  - Write a sequence where you reference what their colleague said

## 4. Trigger-Based Outreach Sequences

**Build automation scripts in this repo that fire outreach based on events.**

- `job_change_outreach.py` — Daily: find contacts who changed jobs in last 7 days using Clay, generate congratulations + soft pitch email with Claude.
- `competitor_displacement.py` — Weekly: find companies using a competitor via Tech Stack enrichment, generate displacement messaging.
- `expansion_signal.py` — Weekly: find existing customers with headcount growth or new funding, generate expansion/upsell outreach.
- `event_follow_up.py` — After conferences: enrich attendee lists with Clay, generate personalized follow-ups referencing the event.

## 5. ICP Scoring & Prioritization

**Use Clay enrichment + Claude analysis to rank your pipeline.**

- Enrich all accounts with `Annual Revenue`, `Headcount Growth`, `Tech Stack`, `Open Jobs`.
- Write a Claude Code script that scores each account against your ICP criteria and outputs a ranked list.
- Focus meeting-booking efforts on the top 20% instead of spray-and-pray.

## 6. Thought Leadership-Based Outreach

**Find what prospects actually care about, then reference it.**

- Use `Find Thought Leadership` on contacts to surface their LinkedIn posts, articles, podcast appearances.
- Use Claude to craft outreach that references their specific POV: "Saw your post about X — we help companies solve exactly that."
- This approach gets 3-5x higher reply rates than generic outreach.

## 7. Warm Intro Mapping

**Use Clay data to find paths to warm introductions.**

- Enrich contacts with `Summarize Work History` to find shared employers, schools, or connections.
- Use `school_names` filter to find prospects who went to the same school as your team.
- Script that cross-references your team's LinkedIn networks against target contacts.

## 8. Re-Engagement Campaigns

**Mine your existing CRM for low-hanging fruit.**

- Use `get-my-accounts` to pull your Salesforce book of business.
- Use `ask-question-about-accounts` to identify: "Which accounts had engagement but went cold in the last 6 months?"
- Enrich those accounts with `Recent News` to find a new reason to reach out.
- Claude generates re-engagement email: "Hey, saw [recent news]. When we last spoke you were dealing with [pain point]. Has that changed?"

## 9. Competitive Intelligence Outreach

**Target customers of competitors who are vulnerable.**

- Use `Company Competitors` and `Company Customers` enrichments to map the competitive landscape.
- Find companies using competitors that recently had outages, price increases, or bad press (via `Recent News`).
- Generate displacement messaging that's timely and relevant.

## 10. Automated Meeting Prep Briefs

**Not about booking — about converting booked meetings to closed deals.**

- Before every meeting, auto-generate a 1-page brief using Clay enrichment:
  - Company overview (revenue, funding, headcount)
  - Key stakeholders and their backgrounds
  - Recent news and trigger events
  - Competitive landscape
  - Suggested talking points
- Higher conversion from meeting → opportunity means each booked meeting is worth more, so you need fewer.

---

## Quick Wins to Start Today

1. **Run a new hire search** on your top 10 target accounts (people who started in last 90 days)
2. **Enrich your stale pipeline** with Recent News to find re-engagement hooks
3. **Multi-thread** your top 5 deals by finding 3 more contacts per account
4. **Score your book** against ICP criteria to focus efforts
